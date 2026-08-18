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
    code:     str
    location: str
    message:  str
 
 
class RetryContext(BaseModel):
    attempt:                  int
    valid:                    bool = False
    errors:                   List[RetryError] = []
    correction_instructions:  Optional[str] = None
 
 
class ReverseWorkflowRequest(BaseModel):
    workflow_id:    str
    workflow_name:  str
    retry_context:  Optional[RetryContext] = None
 
 
class ReverseWorkflowResponse(BaseModel):
    raw_output: Optional[str] = None
    error:      Optional[str] = None
    prompt:     Optional[str] = None


RecommendResponse.model_rebuild()
GenerateResponse.model_rebuild()
