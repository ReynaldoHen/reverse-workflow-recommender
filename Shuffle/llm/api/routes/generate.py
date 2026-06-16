import logging
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends
from ..auth import current_user
from ..schemas import GenerateRequest, GenerateResponse, ReverseWorkflowRequest, ReverseWorkflowResponse
from ..database import get_db, GeneratedWorkflow
from ..services.playbook_generator import playbook_generator, generate_reverse_from_graph
from ..services.shuffle_client import shuffle_client
from ..services.action_recommender import action_recommender

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/generate", tags=["generate"])


# =============================================================================
# POST /generate/playbook
# Forward pipeline: NL description → intermediate JSON → Shuffle JSON
# =============================================================================

@router.post("/playbook", response_model=GenerateResponse)
async def generate_playbook(req: GenerateRequest, db=Depends(get_db), user: str = Depends(current_user)):
    try:
        result = await playbook_generator.generate(req.description, req.target_integrations)
    except Exception as exc:
        action = await action_recommender.recommend(
            trigger="error", reason="Generation raised an exception",
            context=req.description, error_detail=str(exc))
        return GenerateResponse(success=False, error=str(exc), fallback_action=action)

    # Reverse generation not possible -> recommend an action
    if not result.get("success"):
        action = await action_recommender.recommend(
            trigger="generation_not_possible", reason=result.get("error", "unknown"),
            context=req.description)
        return GenerateResponse(success=False, intermediate=result.get("intermediate"),
                                error=result.get("error"), fallback_action=action)

    wf = result["shuffle_workflow"]
    deployed, deployment_id = False, None
    if not req.dry_run:
        row = GeneratedWorkflow(description=req.description,
                                intermediate_json=result["intermediate"],
                                shuffle_json=wf, status="saved")
        db.add(row); db.commit()

    if req.deploy_to_shuffle:
        try:
            dep = await shuffle_client.deploy_workflow(wf)
            deployed = dep.get("deployed", False)
            deployment_id = dep.get("deployment_id")
            if not deployed and dep.get("mode") not in ("offline",):
                action = await action_recommender.recommend(
                    trigger="deployment_failed", reason=dep.get("detail", "deploy failed"),
                    context=req.description)
                return GenerateResponse(success=True, intermediate=result["intermediate"],
                                        shuffle_workflow=wf, fallback_action=action)
        except Exception as exc:
            action = await action_recommender.recommend(
                trigger="deployment_failed", reason="Deploy raised an exception",
                context=req.description, error_detail=str(exc))
            return GenerateResponse(success=True, intermediate=result["intermediate"],
                                    shuffle_workflow=wf, fallback_action=action, error=str(exc))

    return GenerateResponse(success=True, intermediate=result["intermediate"],
                            shuffle_workflow=wf, deployed=deployed, deployment_id=deployment_id)


# =============================================================================
# POST /generate/reverse
# Dipanggil oleh reverse-workflow-service (Node.js) di Step 5.
# Workflow graph sudah tersimpan di Neo4j (Step 4 oleh Node.js).
# =============================================================================

@router.post("/reverse", response_model=ReverseWorkflowResponse)
async def generate_reverse_workflow(
    req: ReverseWorkflowRequest,
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    """
    Pipeline (ditangani Python):
      1. Query Neo4j → ambil Action nodes yang disimpan Node.js di Step 4
      2. RAG retrieval → cari playbook serupa (BGE-M3 + reranker)
      3. Build system prompt  = graph context + RAG examples + retry errors (jika ada)
      4. Call Ollama → raw JSON string
      5. Return raw_output ke Node.js untuk parsing + validasi + import Shuffle
    """
    logger.info(
        "[/generate/reverse] workflow_id=%s  attempt=%s",
        req.workflow_id,
        req.retry_context.attempt if req.retry_context else 1,
    )
    try:
        raw_output = await generate_reverse_from_graph(
            workflow_id=req.workflow_id,
            workflow_name=req.workflow_name,
            retry_context=req.retry_context,
            db=db,
        )
        return ReverseWorkflowResponse(raw_output=raw_output)
    except Exception as exc:
        logger.error("[/generate/reverse] Error: %s", exc, exc_info=True)
        return ReverseWorkflowResponse(error=str(exc))


# =============================================================================
# GET /generate/registry
# =============================================================================

@router.get("/registry")
async def registry(user: str = Depends(current_user)):
    from ..services.app_registry import app_registry
    return {"apps": app_registry.all()}