"""FastAPI application — AI Playbook Recommender for Shuffle SOAR."""
import asyncio
import logging

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from config import get_settings
from database import init_db
from routes.recommend import router as recommend_router
from routes.generate import router as generate_router
from routes.other import (
    auth_router, feedback_router, health_router,
    playbooks_router, search_router,
)

settings = get_settings()

# ── Logging ───────────────────────────────────────────────────────────────────
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    )
)
logger = structlog.get_logger()

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Hybrid RAG + Semi-Agentic Shuffle SOAR Playbook Recommendation System",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus ────────────────────────────────────────────────────────────────
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

# ── Routes ────────────────────────────────────────────────────────────────────
PREFIX = "/api/v1"

app.include_router(recommend_router, prefix=PREFIX)
app.include_router(generate_router, prefix=PREFIX)
app.include_router(search_router, prefix=PREFIX)
app.include_router(feedback_router, prefix=PREFIX)
app.include_router(playbooks_router, prefix=PREFIX)
app.include_router(auth_router, prefix=PREFIX)
app.include_router(health_router)  # /health at root


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("Starting up", version=settings.app_version, env=settings.app_env)

    # Init database tables
    await init_db()
    logger.info("Database tables ready")

    # Ensure Qdrant collections exist
    from sqlalchemy.ext.asyncio import AsyncSession
    from database import AsyncSessionLocal
    from services.retrieval import RetrievalService

    async with AsyncSessionLocal() as db:
        svc = RetrievalService(db)
        try:
            await svc.ensure_collections()
        except Exception as e:
            logger.warning("Qdrant not ready yet, collections will be created on first use", error=str(e))

    # Seed default admin user if no users exist
    await _seed_admin()

    # Start background Shuffle sync
    asyncio.create_task(_background_shuffle_sync())

    logger.info("Startup complete")


async def _seed_admin():
    from sqlalchemy import text
    from database import AsyncSessionLocal
    from auth import hash_password
    import uuid, secrets

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
        if count == 0:
            api_key = secrets.token_hex(32)
            await db.execute(
                text("""
                    INSERT INTO users (id, username, hashed_password, api_key, role)
                    VALUES (:id, 'admin', :pw, :key, 'admin')
                """),
                {"id": str(uuid.uuid4()), "pw": hash_password("admin"), "key": api_key},
            )
            await db.commit()
            logger.info("Default admin created", username="admin", password="admin",
                        api_key=api_key[:8] + "...")


async def _background_shuffle_sync():
    """Background task: sync playbooks from Shuffle every N minutes."""
    import asyncio
    from database import AsyncSessionLocal
    from services.shuffle_sync import ShuffleSyncService

    await asyncio.sleep(30)  # Wait for services to stabilize
    while True:
        try:
            async with AsyncSessionLocal() as db:
                svc = ShuffleSyncService(db)
                await svc.sync_all()
        except Exception as e:
            logger.error("Background Shuffle sync error: %s", e)
        await asyncio.sleep(settings.shuffle_sync_interval_minutes * 60)
