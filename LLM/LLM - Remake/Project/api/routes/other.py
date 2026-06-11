import json
"""Search, Feedback, Playbooks, Auth, and Health routes."""
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, get_current_user, hash_password, require_admin, verify_password
from config import get_settings
from database import get_db
from schemas import (
    FeedbackRequest, FeedbackResponse,
    HealthResponse, LoginRequest, PlaybookCreate,
    PlaybookDetail, PlaybookSummary,
    SearchRequest, SearchResponse, SearchResult,
    ServiceStatus, TokenResponse,
)
from services.llm import get_llm_client
from services.retrieval import RetrievalService

settings = get_settings()
_start_time = time.time()

# ── Search ────────────────────────────────────────────────────────────────────

search_router = APIRouter(prefix="/search", tags=["search"])


@search_router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Direct hybrid search without LLM generation. Fast, keyword + semantic."""
    svc = RetrievalService(db)
    candidates = await svc.hybrid_search(
        query=request.query,
        top_k=request.top_k,
        category=request.category,
        integrations=request.integrations,
    )
    results = [
        SearchResult(
            id=c.playbook_id, name=c.name, description=c.description,
            category=c.category, integrations=c.integrations,
            tags=c.tags, score=round(c.final_score, 3),
        )
        for c in candidates
    ]
    return SearchResponse(query=request.query, results=results, total=len(results))


# ── Feedback ──────────────────────────────────────────────────────────────────

feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])


@feedback_router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    req: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await db.execute(
        text("""
            INSERT INTO feedback (query, session_id, recommended_playbook_id,
                                  confidence_score, accepted, analyst_id, intent, use_refinement)
            VALUES (:query, :session_id, :pb_id, :score, :accepted, :analyst_id, :intent, :refine)
        """),
        {
            "query": req.query,
            "session_id": req.session_id,
            "pb_id": req.recommended_playbook_id,
            "score": req.confidence_score,
            "accepted": req.accepted,
            "analyst_id": req.analyst_id or user.get("username"),
            "intent": req.intent,
            "refine": req.use_refinement,
        },
    )
    return FeedbackResponse(status="ok", message="Feedback recorded. Thank you!")


# ── Playbooks CRUD ────────────────────────────────────────────────────────────

playbooks_router = APIRouter(prefix="/playbooks", tags=["playbooks"])


@playbooks_router.get("", response_model=list[PlaybookSummary])
async def list_playbooks(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    filters = ["is_active = true"]
    params: dict = {"limit": limit, "offset": offset}
    if category:
        filters.append("category ILIKE :category")
        params["category"] = f"%{category}%"

    result = await db.execute(
        text(f"SELECT * FROM playbooks WHERE {' AND '.join(filters)} ORDER BY name LIMIT :limit OFFSET :offset"),
        params,
    )
    rows = result.fetchall()
    return [
        PlaybookSummary(
            id=r.id, name=r.name, description=r.description or "",
            category=r.category or "", integrations=r.integrations or [],
            tags=r.tags or [], is_active=r.is_active,
        )
        for r in rows
    ]


@playbooks_router.post("", response_model=PlaybookDetail, status_code=201)
async def create_playbook(
    pb: PlaybookCreate,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(require_admin),
):
    import uuid
    pid = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO playbooks (id, name, description, use_cases, integrations, triggers,
                                   tags, category, shuffle_workflow_id, shuffle_json, confidence_threshold)
            VALUES (:id,:name,:desc,:use_cases,:integrations,:triggers,:tags,:category,:wf_id,:json::jsonb,:thresh)
        """),
        {
            "id": pid, "name": pb.name, "desc": pb.description,
            "use_cases": pb.use_cases, "integrations": pb.integrations,
            "triggers": pb.triggers, "tags": pb.tags,
            "category": pb.category, "wf_id": pb.shuffle_workflow_id,
            "json": json.dumps(pb.shuffle_json), "thresh": pb.confidence_threshold,
        },
    )
    svc = RetrievalService(db)
    await svc.index_playbook(
        pid, pb.name, pb.description, pb.category,
        pb.integrations, pb.use_cases, pb.tags,
    )
    result = await db.execute(text("SELECT * FROM playbooks WHERE id = :id"), {"id": pid})
    return result.fetchone()


@playbooks_router.get("/{playbook_id}", response_model=PlaybookDetail)
async def get_playbook(
    playbook_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    result = await db.execute(
        text("SELECT * FROM playbooks WHERE id = :id AND is_active = true"),
        {"id": playbook_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return row


# ── Auth ──────────────────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM users WHERE username = :u AND is_active = true"),
        {"u": req.username},
    )
    user = result.fetchone()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(
        {"sub": user.username, "role": user.role},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    return TokenResponse(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


# ── Health ────────────────────────────────────────────────────────────────────

health_router = APIRouter(tags=["health"])


@health_router.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)):
    services = []

    # Postgres
    try:
        t0 = time.perf_counter()
        await db.execute(text("SELECT 1"))
        services.append(ServiceStatus(name="postgres", status="ok",
                                       latency_ms=int((time.perf_counter() - t0) * 1000)))
    except Exception as e:
        services.append(ServiceStatus(name="postgres", status="down", detail=str(e)))

    # Qdrant
    try:
        import httpx as hx
        t0 = time.perf_counter()
        async with hx.AsyncClient(timeout=3) as c:
            r = await c.get(f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz")
        services.append(ServiceStatus(name="qdrant", status="ok" if r.status_code == 200 else "degraded",
                                       latency_ms=int((time.perf_counter() - t0) * 1000)))
    except Exception as e:
        services.append(ServiceStatus(name="qdrant", status="down", detail=str(e)))

    # Ollama
    llm = get_llm_client()
    ollama_ok = await llm.is_healthy()
    services.append(ServiceStatus(name="ollama", status="ok" if ollama_ok else "down"))

    overall = "ok" if all(s.status == "ok" for s in services) else "degraded"
    return HealthResponse(
        status=overall,
        version=settings.app_version,
        services=services,
        uptime_seconds=round(time.time() - _start_time, 1),
    )
