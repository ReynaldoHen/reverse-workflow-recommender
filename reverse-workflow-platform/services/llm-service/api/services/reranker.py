"""Cross-encoder reranking with BGE-Reranker-v2-m3 (optional)."""
import asyncio
from functools import lru_cache
from ..config import get_settings

settings = get_settings()


@lru_cache
def _model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.reranker_model)


class Reranker:
    async def rerank(self, query: str, docs: list[str]) -> list[float]:
        if not settings.enable_reranker or not docs:
            return [0.0] * len(docs)
        loop = asyncio.get_running_loop()   # FIX: get_event_loop() is deprecated
        pairs = [[query, d] for d in docs]
        scores = await loop.run_in_executor(None, _model().predict, pairs)
        return [float(s) for s in scores]


reranker = Reranker()
