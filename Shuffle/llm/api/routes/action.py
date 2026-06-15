from fastapi import APIRouter, Depends
from ..auth import current_user
from ..schemas import ActionRequest, ActionRecommendation
from ..services.action_recommender import action_recommender

router = APIRouter(prefix="/action", tags=["action"])


@router.post("/recommend", response_model=ActionRecommendation)
async def recommend_action(req: ActionRequest, user: str = Depends(current_user)):
    data = await action_recommender.recommend(
        trigger="error" if req.error_detail else "generation_not_possible",
        reason=req.error_detail or "No automated workflow available for this context.",
        context=req.context, error_detail=req.error_detail)
    return ActionRecommendation(**data)
