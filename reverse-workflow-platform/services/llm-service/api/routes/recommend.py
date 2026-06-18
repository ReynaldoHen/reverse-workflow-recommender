from fastapi import APIRouter, Depends
from ..schemas import RecommendRequest, RecommendResponse, PlaybookHit
from ..services.recommendation import recommender
from ..services.explainer import explainer
from ..services.action_recommender import action_recommender

router = APIRouter(prefix="/recommend", tags=["recommend"])


@router.post("", response_model=RecommendResponse)
async def recommend(req: RecommendRequest):
    try:
        raw = await recommender.recommend(req.query, top_k=req.top_k, category=req.category)
    except Exception as exc:
        action = await action_recommender.recommend(
            trigger="error", reason="Recommendation pipeline failed",
            context=req.query, error_detail=str(exc))
        return RecommendResponse(query=req.query, results=[], fallback_action=action,
                                 notes="Recommendation failed; see fallback action.")

    if not raw:
        action = await action_recommender.recommend(
            trigger="generation_not_possible",
            reason="No playbook matched the query above the confidence floor.",
            context=req.query)
        return RecommendResponse(query=req.query, results=[], fallback_action=action,
                                 notes="No confident match found.")

    results = []
    for r in raw:
        hit = PlaybookHit(**r)
        if req.explain:
            ex = await explainer.explain(r)
            hit.explanation = ex["summary"]
        results.append(hit)
    return RecommendResponse(query=req.query, results=results)
