import json
from fastapi import APIRouter, Depends, HTTPException
from ..auth import current_user, authenticate, create_token
from ..schemas import (LoginRequest, TokenResponse, FeedbackRequest)
from ..database import get_db, Playbook, Feedback
from ..services.shuffle_client import shuffle_client

router = APIRouter(tags=["other"])


@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    if not authenticate(req.username, req.password):
        raise HTTPException(401, "Invalid credentials")
    return TokenResponse(access_token=create_token(req.username))


@router.get("/playbooks")
async def list_playbooks(db=Depends(get_db), user: str = Depends(current_user)):
    rows = db.query(Playbook).all()
    return [{"slug": p.slug, "name": p.name, "category": p.category,
             "apps": p.apps} for p in rows]


@router.post("/playbooks")
async def add_playbook(payload: dict, db=Depends(get_db), user: str = Depends(current_user)):
    pb = Playbook(
        slug=payload["slug"], name=payload["name"], category=payload["category"],
        description=payload["description"], steps=payload.get("steps", []),
        apps=payload.get("apps", []),
        # FIX: json round-trip ensures valid JSON in the JSONB column, not dict repr
        shuffle_json=json.loads(json.dumps(payload.get("shuffle_json"))) if payload.get("shuffle_json") else None,
    )
    db.add(pb); db.commit()
    return {"status": "ingested", "slug": pb.slug}


@router.post("/feedback")
async def feedback(req: FeedbackRequest, db=Depends(get_db), user: str = Depends(current_user)):
    db.add(Feedback(query=req.query, playbook_slug=req.playbook_slug,
                    helpful=1 if req.helpful else 0, rank=req.rank))
    db.commit()
    return {"status": "recorded"}


@router.get("/shuffle/status")
async def shuffle_status(user: str = Depends(current_user)):
    return await shuffle_client.health()
