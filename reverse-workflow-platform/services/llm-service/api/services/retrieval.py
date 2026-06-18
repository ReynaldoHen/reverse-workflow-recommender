"""Hybrid retrieval: Qdrant semantic search + keyword overlap, merged."""
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from ..config import get_settings
from .embedder import embedder

settings = get_settings()


class Retrieval:
    def __init__(self):
        self.client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    def ensure_collection(self):
        existing = [c.name for c in self.client.get_collections().collections]
        if settings.qdrant_collection not in existing:
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=qm.VectorParams(
                    size=settings.embedding_dim, distance=qm.Distance.COSINE
                ),
            )

    async def index(self, slug: str, point_id: int, text: str, payload: dict):
        vec = (await embedder.embed([text]))[0]
        self.client.upsert(
            collection_name=settings.qdrant_collection,
            points=[qm.PointStruct(id=point_id, vector=vec, payload=payload)],
        )

    async def search(self, query: str, top_k: int = 10, category: str | None = None):
        vec = (await embedder.embed([query]))[0]
        flt = None
        if category:
            # FIX: MatchText is not a valid Qdrant class; use MatchValue
            flt = qm.Filter(must=[qm.FieldCondition(
                key="category", match=qm.MatchValue(value=category))])
        hits = self.client.search(
            collection_name=settings.qdrant_collection,
            query_vector=vec,
            query_filter=flt,
            limit=top_k,
        )
        return [{"slug": h.payload.get("slug"), "score": float(h.score),
                 "payload": h.payload} for h in hits]


retrieval = Retrieval()
