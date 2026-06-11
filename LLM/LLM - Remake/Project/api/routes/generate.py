"""
Playbook Generation Routes — Natural Language → Shuffle SOAR Workflow.

Endpoints:
  POST   /api/v1/generate/playbook            — Generate new playbook from NL
  GET    /api/v1/generate/playbook/{id}        — Retrieve saved playbook
  POST   /api/v1/generate/playbook/{id}/deploy — Deploy saved playbook to Shuffle
  POST   /api/v1/generate/validate             — Validate Shuffle JSON structure
  GET    /api/v1/generate/registry             — List known Shuffle apps
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from services.app_registry import get_app_registry
from services.playbook_generator import PlaybookGeneratorService

router = APIRouter(prefix="/generate", tags=["generate"])


# ── Request / Response Models ──────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    """Request to generate a new Shuffle-compatible playbook."""

    description: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Natural language description of the desired workflow",
        json_schema_extra={
            "example": (
                "Create a workflow that investigates phishing emails: "
                "extract URLs, check with VirusTotal, block malicious senders, "
                "create a Jira ticket, and alert the SOC via Slack."
            )
        },
    )
    environment: str = Field(
        default="Cloud",
        description="Deployment environment: Cloud, On-Prem, or Hybrid",
    )
    target_integrations: list[str] = Field(
        default=[],
        description="Specific Shuffle apps the workflow should use",
        json_schema_extra={"example": ["virustotal", "slack", "jira"]},
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "If true (default), validate and return but do NOT save to database. "
            "Set to false to persist the generated workflow."
        ),
    )
    deploy_to_shuffle: bool = Field(
        default=False,
        description="After generation, POST the workflow to Shuffle immediately.",
    )


class GenerateResponse(BaseModel):
    """Response from the playbook generation endpoint."""

    success: bool
    playbook_id: str | None = None
    workflow: dict | None = None            # Our intermediate schema
    shuffle_workflow: dict | None = None    # Shuffle-native JSON — deploy this
    validation: dict | None = None          # Intermediate structure validation
    shuffle_validation: dict | None = None  # Shuffle format validation
    deploy_result: dict | None = None       # Set if deploy_to_shuffle=true
    dry_run: bool = True
    errors: list[str] = []
    message: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/playbook", response_model=GenerateResponse, status_code=200)
async def generate_playbook(
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> GenerateResponse:
    """
    **Generate a new Shuffle-compatible playbook from natural language.**

    ### What happens:
    1. LLM reads the description and generates intermediate workflow JSON
    2. App Registry resolves real Shuffle app IDs
    3. Translator converts to Shuffle-native deployment format
    4. Both formats validated (structure + Shuffle compatibility)
    5. Optionally saved and/or deployed

    ### Output:
    - `workflow` — Our intermediate schema (for review)
    - `shuffle_workflow` — **Shuffle-native JSON** (import/deploy this)

    ### Example descriptions:
    ```
    "Respond to ransomware: isolate endpoint via CrowdStrike,
     take snapshot, create P1 ticket in Jira, alert SOC via Slack"
    ```
    """
    svc = PlaybookGeneratorService(db)

    try:
        result = await svc.generate(
            description=req.description,
            environment=req.environment,
            target_integrations=req.target_integrations,
            dry_run=req.dry_run,
        )

        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Workflow generation or validation failed",
                    "errors": result.get("errors", []),
                    "validation": result.get("validation"),
                },
            )

        deploy_result = None
        if req.deploy_to_shuffle and result.get("shuffle_workflow"):
            translator = svc.translator
            deploy_result = await translator.deploy_to_shuffle(result["shuffle_workflow"])

        msg_parts = []
        if req.dry_run:
            msg_parts.append("Workflow validated (not saved — set dry_run=false to persist)")
        else:
            msg_parts.append(f"Workflow saved with ID: {result.get('playbook_id')}")
        if deploy_result:
            if deploy_result.get("success"):
                msg_parts.append(
                    f"Deployed to Shuffle: {deploy_result.get('shuffle_workflow_id')}"
                )
            else:
                msg_parts.append(f"Deploy failed: {deploy_result.get('error')}")

        return GenerateResponse(
            success=True,
            playbook_id=result.get("playbook_id"),
            workflow=result.get("workflow"),
            shuffle_workflow=result.get("shuffle_workflow"),
            validation=result.get("validation"),
            shuffle_validation=result.get("shuffle_validation"),
            deploy_result=deploy_result,
            dry_run=req.dry_run,
            errors=[],
            message=" | ".join(msg_parts),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Generation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal generation error: {str(e)}",
        )


@router.get("/playbook/{playbook_id}", response_model=dict)
async def get_generated_playbook(
    playbook_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    """Retrieve a previously generated and saved playbook with its Shuffle JSON."""
    svc = PlaybookGeneratorService(db)
    pb = await svc.get_playbook(playbook_id)
    if not pb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated playbook not found. Did you set dry_run=false?",
        )
    return pb


@router.post("/playbook/{playbook_id}/deploy", response_model=dict)
async def deploy_playbook_to_shuffle(
    playbook_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    """
    **Deploy a previously generated playbook to Shuffle SOAR.**

    Requires SHUFFLE_API_URL and SHUFFLE_API_KEY to be set in .env.
    The playbook must have been saved first (dry_run=false).
    """
    svc = PlaybookGeneratorService(db)
    result = await svc.deploy_to_shuffle(playbook_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Deploy failed"),
        )
    return result


@router.post("/validate", response_model=dict)
async def validate_workflow(
    workflow: dict,
    _user: dict = Depends(get_current_user),
) -> dict:
    """
    **Validate a Shuffle workflow JSON without generating or saving it.**

    Useful for validating manually edited workflows or custom exports.
    Checks both structure and Shuffle compatibility.
    """
    from services.shuffle_translator import ShuffleTranslator
    translator = ShuffleTranslator()
    result = translator._validate_locally(workflow)
    return {
        "valid": result.get("compatible", False),
        "source": result.get("source", "local"),
        "errors": result.get("errors", []),
    }


@router.get("/registry", response_model=dict)
async def list_app_registry(
    _user: dict = Depends(get_current_user),
) -> dict:
    """
    **List all known Shuffle apps in the built-in registry.**

    These are the apps the generator can resolve to real IDs.
    Includes app_id, display_name, category, and available actions.
    """
    registry = get_app_registry()
    apps = registry.all_apps()
    return {
        "total": len(apps),
        "apps": [
            {
                "app_key": a["app_key"],
                "display_name": a.get("display_name", a["app_key"]),
                "app_id": a.get("app_id"),
                "category": a.get("category", ""),
                "description": a.get("description", ""),
                "actions": list(a.get("actions", {}).keys()),
            }
            for a in apps
        ],
    }


# ── Logger for this module ────────────────────────────────────────────────────
import logging
logger = logging.getLogger(__name__)
