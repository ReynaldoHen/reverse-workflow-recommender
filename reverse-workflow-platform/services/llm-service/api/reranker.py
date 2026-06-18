"""Cross-encoder reranking with BGE-Reranker-v2-m3 (optional)."""
import asyncio
import logging
import time
from functools import lru_cache
from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@lru_cache
def _model():
    from sentence_transformers import CrossEncoder
    logger.info("[reranker] loading %s (this blocks until done — watch for "
                "the 'loaded' line below; if it never appears, it's stuck "
                "downloading/connecting, not just 'slow CPU')", settings.reranker_model)
    t0 = time.monotonic()
    model = CrossEncoder(settings.reranker_model)
    logger.info("[reranker] loaded %s in %.1fs", settings.reranker_model, time.monotonic() - t0)
    return model


class Reranker:
    async def rerank(self, query: str, docs: list[str]) -> list[float]:
        if not settings.enable_reranker or not docs:
            return [0.0] * len(docs)
        loop = asyncio.get_running_loop()   # FIX: get_event_loop() is deprecated
        pairs = [[query, d] for d in docs]
        scores = await loop.run_in_executor(None, _model().predict, pairs)
        return [float(s) for s in scores]


reranker = Reranker()