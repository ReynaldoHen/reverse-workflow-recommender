import logging
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends
from ..auth import current_user
from ..schemas import ReverseWorkflowRequest, ReverseWorkflowResponse
from ..database import get_db
from ..services.playbook_generator import generate_reverse_from_graph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/generate", tags=["generate"])

@router.post("/reverse", response_model=ReverseWorkflowResponse)
async def generate_reverse_workflow(
    req: ReverseWorkflowRequest,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    logger.info(
        "[/generate/reverse] workflow_id=%s  attempt=%s",
        req.workflow_id,
        req.retry_context.attempt if req.retry_context else 1,
    )
    try:
        raw_output, prompt_used = await generate_reverse_from_graph(
            workflow_id=req.workflow_id,
            workflow_name=req.workflow_name,
            retry_context=req.retry_context,
            db=db,
        )

        if raw_output is None:
            return ReverseWorkflowResponse(
                error="generate_reverse_from_graph returned None"
            )

        return ReverseWorkflowResponse(raw_output=str(raw_output), prompt=prompt_used)

    except Exception as exc:
        logger.error("[/generate/reverse] Error: %s", exc, exc_info=True)
        return ReverseWorkflowResponse(error=str(exc))


@router.get("/registry")
async def registry(user: str = Depends(current_user)):
    from ..services.app_registry import app_registry
    return {"apps": app_registry.all()}
