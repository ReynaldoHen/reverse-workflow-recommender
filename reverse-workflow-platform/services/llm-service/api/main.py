"""FastAPI entrypoint: routes, startup, background Shuffle sync."""
import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .database import init_models
from .services.shuffle_sync import run_sync_loop
from .routes import generate, other

settings = get_settings()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("playbook-api")

# Surface an admin API key in the logs on first boot (thesis convenience).
BOOT_API_KEY = secrets.token_hex(16)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_models()
    log.info("admin api_key (login admin/admin for JWT): %s", BOOT_API_KEY)
    task = asyncio.create_task(run_sync_loop())   # background Shuffle sync
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, version="6.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PREFIX = f"/api/{settings.api_version}"
for r in (generate.router, other.router):
    app.include_router(r, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "shuffle_connected": settings.shuffle_connected}
