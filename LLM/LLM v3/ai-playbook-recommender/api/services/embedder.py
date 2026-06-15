"""BGE-M3 text embeddings via sentence-transformers, async-safe."""
import asyncio
from functools import lru_cache
from ..config import get_settings

settings = get_settings()


@lru_cache
def _model():
    # Imported lazily so the container starts even before the model is cached.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embedding_model)


class Embedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()   # FIX: get_event_loop() is deprecated
        return await loop.run_in_executor(None, self._encode, texts)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vecs = _model().encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]


embedder = Embedder()
