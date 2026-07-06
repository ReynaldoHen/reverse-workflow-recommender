"""Pydantic request/response models."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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
    confidence: str
    explanation: Optional[str] = None
    steps: Optional[list[dict]] = None


class RecommendResponse(BaseModel):
    query: str
    results: list[PlaybookHit]
    fallback_action: Optional["ActionRecommendation"] = None
    notes: Optional[str] = None


class ExplainResponse(BaseModel):
    slug: str
    name: str
    summary: str
    step_explanations: list[dict]


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
    fallback_action: Optional["ActionRecommendation"] = None
    error: Optional[str] = None


class ActionRecommendation(BaseModel):
    trigger: str
    reason: str
    recommended_actions: list[dict]
    closest_playbook: Optional[str] = None


class ActionRequest(BaseModel):
    context: str
    error_detail: Optional[str] = None
    attempted_description: Optional[str] = None


class FeedbackRequest(BaseModel):
    query: str
    playbook_slug: str
    helpful: bool
    rank: Optional[int] = None


class RetryError(BaseModel):
    """Single validation error forwarded from Node.js on retry attempts."""
    code:     str
    location: str
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
    workflow_id:    str
    workflow_name:  str
    retry_context:  Optional[RetryContext] = None
 
 
class ReverseWorkflowResponse(BaseModel):
    """
    Response back to reverse-workflow-service.
    raw_output is the Ollama response string (may contain markdown code fences —
    Node.js strips them before JSON.parse()).
    """
    raw_output: Optional[str] = None
    error:      Optional[str] = None
    prompt:     Optional[str] = None


RecommendResponse.model_rebuild()
GenerateResponse.model_rebuild()
