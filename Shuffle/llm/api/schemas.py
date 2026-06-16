"""Pydantic request/response models."""
from typing import Any, Dict, List, Optional
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


# ---------- Reverese Workflow Service ----------
class RetryError(BaseModel):
    """Single validation error forwarded from Node.js on retry attempts."""
    code:     str            # e.g. "MISSING_FIELD", "INVALID_ACTION_NAME", "IMPORT_ERROR"
    location: str            # e.g. "actions[0]", "root", "llm_service"
    message:  str
 
 
class RetryContext(BaseModel):
    """
    Populated by Node.js when forwarding validation errors back to the LLM.
    Null on the first attempt; present on retries so the LLM can self-correct.
    """
    attempt:                  int
    valid:                    bool = False
    errors:                   List[RetryError] = []
    correction_instructions:  Optional[str] = None
 
 
class ReverseWorkflowRequest(BaseModel):
    """
    Request from reverse-workflow-service (Node.js) at Step 5.
    The workflow graph must already be saved to Neo4j (done at Step 4).
    """
    workflow_id:    str                      # Shuffle workflow UUID
    workflow_name:  str                      # Human-readable name
    retry_context:  Optional[RetryContext] = None  # None on first call
 
 
class ReverseWorkflowResponse(BaseModel):
    """
    Response back to reverse-workflow-service.
    raw_output is the Ollama response string (may contain markdown code fences —
    Node.js strips them before JSON.parse()).
    """
    raw_output: Optional[str] = None   # Raw Ollama output on success
    error:      Optional[str] = None   # Error message on failure


RecommendResponse.model_rebuild()
GenerateResponse.model_rebuild()
