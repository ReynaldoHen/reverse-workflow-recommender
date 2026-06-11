from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ── Playbook schemas ──────────────────────────────────────────────────────────

class PlaybookCreate(BaseModel):
    name: str
    description: str
    use_cases: list[str] = []
    integrations: list[str] = []
    triggers: list[str] = []
    tags: list[str] = []
    category: str = ""
    shuffle_workflow_id: str = ""
    shuffle_json: dict = {}
    confidence_threshold: float = 0.75


class PlaybookSummary(BaseModel):
    id: str
    name: str
    description: str
    category: str
    integrations: list[str]
    tags: list[str]
    is_active: bool


class PlaybookDetail(PlaybookSummary):
    use_cases: list[str]
    triggers: list[str]
    shuffle_workflow_id: str
    shuffle_json: dict
    confidence_threshold: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Recommendation schemas ────────────────────────────────────────────────────

class AnalystContext(BaseModel):
    """Optional environment context for semi-agentic refinement."""
    available_integrations: list[str] = Field(
        default=[],
        description="Apps/integrations available in the analyst's Shuffle environment"
    )
    api_keys_configured: list[str] = Field(
        default=[],
        description="Integrations for which API keys are already configured"
    )
    team: Optional[str] = None
    environment: Optional[str] = None  # e.g. "azure", "aws", "on-prem"


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    session_id: Optional[str] = None
    conversation_history: list[dict] = []
    analyst_context: Optional[AnalystContext] = None
    use_refinement: bool = Field(
        default=False,
        description="Enable semi-agentic refinement (adds ~3s latency)"
    )
    top_k: int = Field(default=3, ge=1, le=10)


class AgentVerification(BaseModel):
    compatible: bool
    missing_integrations: list[str]
    customization_required: bool
    customization_steps: list[str]
    config_gaps: list[dict]
    coverage_pct: float


class RecommendedPlaybook(BaseModel):
    id: str
    name: str
    description: str
    category: str
    integrations: list[str]
    confidence_score: float
    reasoning: str
    modifications: list[str]
    agent_verification: Optional[AgentVerification] = None


class RecommendResponse(BaseModel):
    query: str
    intent: str
    recommended_playbooks: list[RecommendedPlaybook]
    fallback_message: str = ""
    session_id: Optional[str] = None
    used_refinement: bool = False
    latency_ms: int = 0


# ── Search schemas ────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    category: Optional[str] = None
    integrations: Optional[list[str]] = None
    top_k: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    id: str
    name: str
    description: str
    category: str
    integrations: list[str]
    tags: list[str]
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


# ── Feedback schemas ──────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    recommended_playbook_id: str
    confidence_score: float
    accepted: bool
    analyst_id: Optional[str] = None
    intent: Optional[str] = None
    use_refinement: bool = False


class FeedbackResponse(BaseModel):
    status: str
    message: str


# ── Auth schemas ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Health schemas ────────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    name: str
    status: str  # "ok" | "degraded" | "down"
    latency_ms: Optional[int] = None
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    services: list[ServiceStatus]
    uptime_seconds: float
