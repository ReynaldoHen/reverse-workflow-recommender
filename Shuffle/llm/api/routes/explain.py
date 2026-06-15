from fastapi import APIRouter, Depends, HTTPException
from ..auth import current_user
from ..schemas import ExplainResponse
from ..database import get_db, Playbook
from ..services.explainer import explainer

router = APIRouter(prefix="/explain", tags=["explain"])


@router.get("/{slug}", response_model=ExplainResponse)
async def explain(slug: str, db=Depends(get_db), user: str = Depends(current_user)):
    pb = db.query(Playbook).filter_by(slug=slug).first()
    if not pb:
        raise HTTPException(404, f"Playbook '{slug}' not found")
    data = await explainer.explain({
        "slug": pb.slug, "name": pb.name, "description": pb.description, "steps": pb.steps,
    })
    return ExplainResponse(slug=data["slug"], name=data["name"],
                           summary=data["summary"], step_explanations=data["step_explanations"])
