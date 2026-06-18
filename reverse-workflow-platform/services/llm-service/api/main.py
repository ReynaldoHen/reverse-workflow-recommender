"""FastAPI entrypoint: routes, startup, background Shuffle sync."""
import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .database import init_models
from .services.retrieval import retrieval
from .services.embedder import embedder
from .services.reranker import reranker
from .services.shuffle_sync import run_sync_loop
from .routes import recommend, explain, generate, action, other

settings = get_settings()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("playbook-api")

# Surface an admin API key in the logs on first boot (thesis convenience).
BOOT_API_KEY = secrets.token_hex(16)


async def _warmup_models():
    """Load embedder + reranker in the background so a slow/cold model
    load (or a model download, if not cached) never blocks the app from
    accepting connections. Runs as a fire-and-forget task from lifespan.
    selama container tidak di-rebuild/recreate tidak perlu download ulang"""
    try:
        log.info("[warmup] embedding model (%s)...", settings.embedding_model)
        t0 = time.monotonic()
        await embedder.embed(["warmup"])
        log.info("[warmup] embedding model ready in %.1fs", time.monotonic() - t0)

        log.info("[warmup] reranker model (%s)...", settings.reranker_model)
        t0 = time.monotonic()
        await reranker.rerank("warmup", ["warmup"])
        log.info("[warmup] reranker model ready in %.1fs", time.monotonic() - t0)

        log.info("[warmup] complete — embedder + reranker are warm.")
    except Exception as exc:
        log.warning("[warmup] failed (will lazy-load on first real request instead): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_models()
    try:
        retrieval.ensure_collection()
    except Exception as exc:
        log.warning("Qdrant not ready yet: %s", exc)

    # Fire-and-forget: do NOT await this. Startup must not block on model
    # load/download — uvicorn needs to open port 8000 right away so other
    # services (auth/login, /health, /docs) aren't hit with ECONNREFUSED.
    asyncio.create_task(_warmup_models())

    log.info("admin api_key (login admin/admin for JWT): %s", BOOT_API_KEY)
    task = asyncio.create_task(run_sync_loop())   # background sync, no __new__ hack
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, version="6.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PREFIX = f"/api/{settings.api_version}"
for r in (recommend.router, explain.router, generate.router, action.router, other.router):
    app.include_router(r, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "shuffle_connected": settings.shuffle_connected}