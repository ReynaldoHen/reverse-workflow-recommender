"""Recommendation service: wires hybrid retrieval → reranker → LLM."""
import json
import logging
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from schemas import (
    AnalystContext, RecommendRequest, RecommendResponse,
    RecommendedPlaybook, AgentVerification,
)
from services.embedder import get_embedding_service
from services.llm import get_llm_client
from services.reranker import get_reranker_service
from services.retrieval import RetrievalService
from services.semi_agentic import SemiAgenticService

logger = logging.getLogger(__name__)
settings = get_settings()


class RecommendationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.retrieval = RetrievalService(db)
        self.reranker = get_reranker_service()
        self.llm = get_llm_client()

    async def recommend(self, request: RecommendRequest) -> RecommendResponse:
        start = time.perf_counter()

        # ── 1. Intent classification ─────────────────────────────────────────
        intent = await self.llm.classify_intent(request.query)
        logger.info("Query intent: %s | query=%s", intent, request.query[:80])

        # ── 2. Hybrid retrieval ──────────────────────────────────────────────
        candidates = await self.retrieval.hybrid_search(
            query=request.query,
            top_k=settings.retrieval_top_k,
        )

        if not candidates:
            elapsed = int((time.perf_counter() - start) * 1000)
            return RecommendResponse(
                query=request.query,
                intent=intent,
                recommended_playbooks=[],
                fallback_message=(
                    "No playbooks found in the knowledge base. "
                    "Try broadening your query or adding playbooks via the ingest script."
                ),
                session_id=request.session_id,
                used_refinement=False,
                latency_ms=elapsed,
            )

        # ── 3. Rerank ────────────────────────────────────────────────────────
        reranked = await self.reranker.rerank(
            request.query, candidates, top_k=settings.rerank_top_k
        )

        # ── 4. LLM recommendation ────────────────────────────────────────────
        candidate_dicts = [
            {
                "id": c.playbook_id,
                "name": c.name,
                "description": c.description,
                "category": c.category,
                "integrations": c.integrations,
                "use_cases": c.use_cases,
                "score": c.final_score,
            }
            for c in reranked
        ]

        llm_result = await self.llm.recommend(
            query=request.query,
            intent=intent,
            candidates=candidate_dicts,
            conversation_history=request.conversation_history,
            top_k=request.top_k,
        )

        # ── 5. Enrich recommendation with playbook metadata ──────────────────
        score_map = {pid: s for pid, s in zip(
            llm_result.get("recommended_playbooks", []),
            llm_result.get("confidence_scores", [])
        )}
        reasoning_map = {pid: r for pid, r in zip(
            llm_result.get("recommended_playbooks", []),
            llm_result.get("reasoning", [])
        )}
        candidate_meta = {c.playbook_id: c for c in reranked}

        recommended = []
        for pid in llm_result.get("recommended_playbooks", [])[:request.top_k]:
            if pid not in candidate_meta:
                continue
            meta = candidate_meta[pid]
            recommended.append(RecommendedPlaybook(
                id=pid,
                name=meta.name,
                description=meta.description,
                category=meta.category,
                integrations=meta.integrations,
                confidence_score=score_map.get(pid, meta.final_score),
                reasoning=reasoning_map.get(pid, ""),
                modifications=llm_result.get("modifications", []),
            ))

        # ── 6. Optional semi-agentic refinement ──────────────────────────────
        used_refinement = False
        if request.use_refinement and request.analyst_context and recommended:
            agent = SemiAgenticService(self.db)
            recommended = await agent.refine(recommended, request.analyst_context)
            used_refinement = True

        # ── 7. Fallback check ────────────────────────────────────────────────
        fallback_msg = llm_result.get("fallback_message", "")
        if not recommended:
            fallback_msg = (
                "No confident matches found. Try adding more detail about the "
                "specific integrations or threat type you need to handle."
            )
        elif all(r.confidence_score < settings.confidence_warn_threshold for r in recommended):
            fallback_msg = (
                f"Low confidence matches returned. Consider refining your query "
                f"or enabling semi-agentic refinement for better accuracy."
            )

        # ── 8. Persist session history ───────────────────────────────────────
        if request.session_id:
            await self._update_session(
                request.session_id, request.query,
                [r.model_dump() for r in recommended]
            )

        elapsed = int((time.perf_counter() - start) * 1000)
        logger.info("Recommendation complete in %d ms | %d results", elapsed, len(recommended))

        return RecommendResponse(
            query=request.query,
            intent=intent,
            recommended_playbooks=recommended,
            fallback_message=fallback_msg,
            session_id=request.session_id,
            used_refinement=used_refinement,
            latency_ms=elapsed,
        )

    async def _update_session(self, session_id: str, query: str, results: list):
        """Append turn to session conversation history."""
        await self.db.execute(
            text("""
                INSERT INTO sessions (id, conversation_history, updated_at)
                VALUES (:sid, :history::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE
                SET conversation_history = (
                    SELECT jsonb_agg(elem)
                    FROM (
                        SELECT elem FROM jsonb_array_elements(sessions.conversation_history) elem
                        UNION ALL
                        SELECT :new_turn::jsonb
                    ) sub
                ),
                updated_at = NOW()
            """),
            {
                "sid": session_id,
                "history": "[]",
                "new_turn": json.dumps({
                    "role": "user",
                    "content": query,
                    "results": [r.get("id", "") for r in results[:1]],
                }),
            }
        )
