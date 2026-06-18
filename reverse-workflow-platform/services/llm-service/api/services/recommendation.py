"""Forward pipeline: retrieve -> rerank -> LLM rationale -> ranked playbooks."""
import json
from .retrieval import retrieval
from .reranker import reranker
from .llm import llm

CONFIDENCE_BANDS = [(0.75, "high"), (0.5, "medium"), (0.0, "low")]


def _confidence(score: float) -> str:
    for threshold, label in CONFIDENCE_BANDS:
        if score >= threshold:
            return label
    return "low"


class Recommender:
    async def recommend(self, query: str, top_k: int = 3, category: str | None = None):
        candidates = await retrieval.search(query, top_k=max(top_k * 3, 10), category=category)
        if not candidates:
            return []

        docs = [f"{c['payload'].get('name','')}. {c['payload'].get('description','')}"
                for c in candidates]
        rerank_scores = await reranker.rerank(query, docs)
        for c, rs in zip(candidates, rerank_scores):
            # Blend semantic + cross-encoder score (normalised)
            c["final"] = 0.4 * c["score"] + 0.6 * _sigmoid(rs)

        ranked = sorted(candidates, key=lambda c: c["final"], reverse=True)[:top_k]
        results = []
        for c in ranked:
            p = c["payload"]
            results.append({
                "slug": p.get("slug"),
                "name": p.get("name"),
                "category": p.get("category"),
                "description": p.get("description"),
                "score": round(c["final"], 4),
                "confidence": _confidence(c["final"]),
                "steps": p.get("steps"),
            })
        return results

    async def rationale(self, query: str, results: list[dict]) -> str:
        # FIX: use json.dumps, never repr(), to build the prompt payload
        summary = json.dumps(
            [{"name": r["name"], "description": r["description"]} for r in results]
        )
        system = ("You are a SOC automation assistant. Briefly explain, in 2-3 "
                  "sentences, why the recommended playbooks fit the analyst's situation.")
        prompt = f"Analyst situation: {query}\nCandidate playbooks (JSON): {summary}"
        try:
            return await llm.complete(prompt, system=system)
        except Exception:
            return "Recommendations ranked by semantic similarity and cross-encoder relevance."


def _sigmoid(x: float) -> float:
    import math
    return 1 / (1 + math.exp(-x))


recommender = Recommender()
