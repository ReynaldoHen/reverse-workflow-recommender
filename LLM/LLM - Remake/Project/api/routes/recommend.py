from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from schemas import RecommendRequest, RecommendResponse
from services.recommendation import RecommendationService

router = APIRouter(prefix="/recommend", tags=["recommend"])


@router.post("", response_model=RecommendResponse)
async def recommend(
    request: RecommendRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> RecommendResponse:
    """
    Main recommendation endpoint.

    - Classifies query intent
    - Runs hybrid retrieval (semantic + keyword + metadata)
    - Reranks with BGE cross-encoder
    - Generates structured recommendation via Llama 3.1 8B
    - Optionally runs semi-agentic refinement (`use_refinement: true`)
    """
    svc = RecommendationService(db)
    return await svc.recommend(request)
