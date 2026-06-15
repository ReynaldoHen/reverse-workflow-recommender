from fastapi import APIRouter, Depends
from ..auth import current_user
from ..schemas import GenerateRequest, GenerateResponse
from ..database import get_db, GeneratedWorkflow
from ..services.playbook_generator import playbook_generator
from ..services.shuffle_client import shuffle_client
from ..services.action_recommender import action_recommender

router = APIRouter(prefix="/generate", tags=["generate"])


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


@router.get("/registry")
async def registry(user: str = Depends(current_user)):
    from ..services.app_registry import app_registry
    return {"apps": app_registry.all()}
