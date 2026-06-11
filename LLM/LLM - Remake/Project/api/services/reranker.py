"""Cross-encoder reranker using BGE-Reranker-v2-m3."""
import asyncio
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

_reranker = None


def _load_reranker():
    global _reranker
    if _reranker is None:
        logger.info("Loading BAAI/bge-reranker-v2-m3...")
        from FlagEmbedding import FlagReranker
        _reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)
        logger.info("Reranker loaded.")
    return _reranker


class RerankerService:
    async def rerank(self, query: str, candidates: list, top_k: int = 5) -> list:
        """
        Rerank RetrievalCandidate list using cross-encoder.
        Returns candidates sorted by reranker score, limited to top_k.
        """
        if not candidates:
            return []

        passages = [f"{c.name}. {c.description}" for c in candidates]
        scores = await asyncio.get_running_loop().run_in_executor(
            None, self._score_sync, query, passages
        )

        for candidate, score in zip(candidates, scores):
            candidate.final_score = float(score)

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates[:top_k]

    def _score_sync(self, query: str, passages: list[str]) -> list[float]:
        reranker = _load_reranker()
        pairs = [[query, p] for p in passages]
        return reranker.compute_score(pairs, normalize=True)


@lru_cache(maxsize=1)
def get_reranker_service() -> RerankerService:
    return RerankerService()
