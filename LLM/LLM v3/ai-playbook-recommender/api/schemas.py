"""Pydantic request/response models."""
from typing import Optional, Any
from pydantic import BaseModel, Field


# ---------- Auth ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Recommend (forward) ----------
class RecommendRequest(BaseModel):
    query: str = Field(..., description="Analyst's natural-language situation")
    top_k: int = 3
    category: Optional[str] = None
    explain: bool = True


class PlaybookHit(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    score: float
    confidence: str               # high | medium | low
    explanation: Optional[str] = None
    steps: Optional[list[dict]] = None


class RecommendResponse(BaseModel):
    query: str
    results: list[PlaybookHit]
    fallback_action: Optional["ActionRecommendation"] = None
    notes: Optional[str] = None


# ---------- Explain ----------
class ExplainResponse(BaseModel):
    slug: str
    name: str
    summary: str
    step_explanations: list[dict]   # {order, title, what, why}


# ---------- Generate (reverse) ----------
class GenerateRequest(BaseModel):
    description: str
    target_integrations: list[str] = []
    dry_run: bool = True
    deploy_to_shuffle: bool = False


class GenerateResponse(BaseModel):
    success: bool
    intermediate: Optional[dict] = None
    shuffle_workflow: Optional[dict] = None
    deployed: bool = False
    deployment_id: Optional[str] = None
    # When generation is not possible OR an error occurred, we recommend an action
    fallback_action: Optional["ActionRecommendation"] = None
    error: Optional[str] = None


# ---------- Action Recommender ----------
class ActionRecommendation(BaseModel):
    trigger: str                    # generation_not_possible | error | deployment_failed
    reason: str
    recommended_actions: list[dict] # {priority, action, detail}
    closest_playbook: Optional[str] = None


class ActionRequest(BaseModel):
    context: str
    error_detail: Optional[str] = None
    attempted_description: Optional[str] = None


# ---------- Feedback ----------
class FeedbackRequest(BaseModel):
    query: str
    playbook_slug: str
    helpful: bool
    rank: Optional[int] = None


RecommendResponse.model_rebuild()
GenerateResponse.model_rebuild()
