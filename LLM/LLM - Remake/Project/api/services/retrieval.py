"""Hybrid retrieval: semantic (Qdrant) + keyword (PostgreSQL) + metadata scoring."""
import logging
from dataclasses import dataclass
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services.embedder import get_embedding_service

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class RetrievalCandidate:
    playbook_id: str
    name: str
    description: str
    category: str
    integrations: list[str]
    tags: list[str]
    use_cases: list[str]
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    metadata_score: float = 0.0
    final_score: float = 0.0


class RetrievalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedder = get_embedding_service()
        self.qdrant = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )

    async def hybrid_search(
        self,
        query: str,
        top_k: int = 20,
        category: Optional[str] = None,
        integrations: Optional[list[str]] = None,
    ) -> list[RetrievalCandidate]:
        """Run semantic + keyword + metadata retrieval, fuse scores."""

        # ── 1. Semantic search (Qdrant) ──────────────────────────────────────
        query_vec = await self.embedder.embed_single(query)
        qdrant_filter = self._build_qdrant_filter(category, integrations)

        hits = await self.qdrant.search(
            collection_name=settings.qdrant_collection_playbooks,
            query_vector=query_vec,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )

        semantic_map: dict[str, float] = {}
        for h in hits:
            pid = h.payload.get("playbook_id")
            if pid:
                semantic_map[pid] = float(h.score)

        # ── 2. Keyword search (PostgreSQL full-text / ILIKE) ─────────────────
        keyword_map = await self._keyword_search(query, top_k, category, integrations)

        # ── 3. Metadata relevance (integration overlap boost) ────────────────
        all_ids = list(set(list(semantic_map.keys()) + list(keyword_map.keys())))
        if not all_ids:
            return []

        meta_map = await self._metadata_score(all_ids, query, integrations)

        # ── 4. Fetch full playbook data ──────────────────────────────────────
        rows = await self._fetch_playbooks(all_ids)

        # ── 5. Fuse scores ───────────────────────────────────────────────────
        candidates = []
        for row in rows:
            pid = row["id"]
            sem = semantic_map.get(pid, 0.0)
            kw = keyword_map.get(pid, 0.0)
            meta = meta_map.get(pid, 0.0)

            final = (
                settings.semantic_weight * sem
                + settings.keyword_weight * kw
                + settings.metadata_weight * meta
            )

            candidates.append(
                RetrievalCandidate(
                    playbook_id=pid,
                    name=row["name"],
                    description=row["description"] or "",
                    category=row["category"] or "",
                    integrations=row["integrations"] or [],
                    tags=row["tags"] or [],
                    use_cases=row["use_cases"] or [],
                    semantic_score=sem,
                    keyword_score=kw,
                    metadata_score=meta,
                    final_score=final,
                )
            )

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates[:top_k]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_qdrant_filter(
        self, category: Optional[str], integrations: Optional[list[str]]
    ) -> Optional[Filter]:
        conditions = []
        if category:
            conditions.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if integrations:
            conditions.append(
                FieldCondition(key="integrations", match=MatchAny(any=integrations))
            )
        return Filter(must=conditions) if conditions else None

    async def _keyword_search(
        self,
        query: str,
        top_k: int,
        category: Optional[str],
        integrations: Optional[list[str]],
    ) -> dict[str, float]:
        """BM25-style search via PostgreSQL ts_rank."""
        params: dict = {"query": query, "limit": top_k}
        filters = ["is_active = true"]

        if category:
            filters.append("category ILIKE :category")
            params["category"] = f"%{category}%"

        if integrations:
            filters.append("integrations && :integrations")
            params["integrations"] = integrations

        where = " AND ".join(filters)
        sql = text(f"""
            SELECT id,
                   ts_rank(
                       to_tsvector('english', coalesce(name,'') || ' ' || coalesce(description,'') ||
                                  ' ' || coalesce(array_to_string(tags,' '),'') ||
                                  ' ' || coalesce(array_to_string(integrations,' '),'') ||
                                  ' ' || coalesce(array_to_string(use_cases,' '),'')
                       ),
                       plainto_tsquery('english', :query)
                   ) AS rank
            FROM playbooks
            WHERE {where}
              AND to_tsvector('english', coalesce(name,'') || ' ' || coalesce(description,''))
                  @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """)

        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        max_rank = max((r.rank for r in rows), default=1.0)
        return {r.id: r.rank / max_rank for r in rows} if rows else {}

    async def _metadata_score(
        self,
        playbook_ids: list[str],
        query: str,
        requested_integrations: Optional[list[str]],
    ) -> dict[str, float]:
        """Score based on integration overlap between query keywords and playbook."""
        result = await self.db.execute(
            text("SELECT id, integrations FROM playbooks WHERE id = ANY(:ids)"),
            {"ids": playbook_ids},
        )
        rows = result.fetchall()
        query_words = set(query.lower().split())
        scores: dict[str, float] = {}

        for row in rows:
            pb_integrations = [i.lower() for i in (row.integrations or [])]
            overlap = sum(1 for i in pb_integrations if any(w in i for w in query_words))
            req_overlap = 0
            if requested_integrations:
                req_lower = [r.lower() for r in requested_integrations]
                req_overlap = sum(1 for i in pb_integrations if i in req_lower)

            max_possible = max(len(pb_integrations), 1)
            scores[row.id] = min((overlap + req_overlap * 2) / max_possible, 1.0)

        return scores

    async def _fetch_playbooks(self, ids: list[str]) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT id, name, description, category, integrations, tags, use_cases
                FROM playbooks WHERE id = ANY(:ids) AND is_active = true
            """),
            {"ids": ids},
        )
        return [dict(r._mapping) for r in result.fetchall()]

    async def index_playbook(self, playbook_id: str, name: str, description: str,
                              category: str, integrations: list[str],
                              use_cases: list[str], tags: list[str]):
        """Embed and upsert a playbook into Qdrant."""
        text_to_embed = f"{name}. {description}. Use cases: {', '.join(use_cases)}. Integrations: {', '.join(integrations)}"
        vector = await self.embedder.embed_single(text_to_embed)

        from qdrant_client.models import PointStruct
        import uuid
        point_id = str(uuid.uuid4())

        await self.qdrant.upsert(
            collection_name=settings.qdrant_collection_playbooks,
            points=[PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "playbook_id": playbook_id,
                    "name": name,
                    "category": category,
                    "integrations": integrations,
                    "tags": tags,
                }
            )]
        )
        return point_id

    async def ensure_collections(self):
        """Create Qdrant collections if they don't exist."""
        from qdrant_client.models import VectorParams, Distance
        existing = {c.name for c in (await self.qdrant.get_collections()).collections}

        for col in [settings.qdrant_collection_playbooks, settings.qdrant_collection_actions]:
            if col not in existing:
                await self.qdrant.create_collection(
                    collection_name=col,
                    vectors_config=VectorParams(
                        size=settings.qdrant_vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {col}")
