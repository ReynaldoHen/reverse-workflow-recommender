"""BGE-M3 embedding service — dense 1024-dim vectors."""
import asyncio
import logging
from functools import lru_cache
from typing import Union

import numpy as np

logger = logging.getLogger(__name__)

_model = None


def _load_model():
    """Lazy-load BGE-M3 (downloads ~2 GB on first run, cached in volume)."""
    global _model
    if _model is None:
        logger.info("Loading BAAI/bge-m3 embedding model...")
        from FlagEmbedding import BGEM3FlagModel
        _model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
        logger.info("Embedding model loaded.")
    return _model


class EmbeddingService:
    """Wraps BGE-M3 with async interface and batch support."""

    def __init__(self):
        self._loop = None

    async def embed(self, texts: Union[str, list[str]]) -> list[list[float]]:
        """Embed one or more texts. Returns list of 1024-dim vectors."""
        if isinstance(texts, str):
            texts = [texts]
        return await asyncio.get_running_loop().run_in_executor(
            None, self._embed_sync, texts
        )

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        model = _load_model()
        result = model.encode(
            texts,
            batch_size=12,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        vecs = result["dense_vecs"]
        # Normalise
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs = vecs / np.where(norms == 0, 1, norms)
        return vecs.tolist()

    async def embed_single(self, text: str) -> list[float]:
        vecs = await self.embed([text])
        return vecs[0]


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
