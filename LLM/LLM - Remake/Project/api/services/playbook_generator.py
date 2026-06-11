"""
Playbook Generation Service — Natural Language → Shuffle SOAR Workflow.

Full pipeline:
  1. Analyst describes the workflow in plain English
  2. LLM generates our intermediate workflow schema (with steps + connections)
  3. ShuffleTranslator converts intermediate → Shuffle-native JSON
  4. Validates the output locally and optionally with Shuffle API
  5. Saves to DB and/or deploys to Shuffle

This is the "reverse function": instead of recommending existing playbooks,
it generates brand-new, deployment-ready Shuffle workflows.
"""
import json
import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services.llm import get_llm_client
from services.shuffle_translator import ShuffleTranslator

logger = logging.getLogger(__name__)
settings = get_settings()


class PlaybookGeneratorService:
    """Generates Shuffle-compatible playbooks from natural language."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()
        self.translator = ShuffleTranslator()

    async def generate(
        self,
        description: str,
        environment: str = "Cloud",
        target_integrations: list[str] = None,
        dry_run: bool = True,
    ) -> dict:
        """
        Full pipeline: NL description → validated Shuffle workflow.

        Steps:
          1. LLM generates intermediate JSON
          2. Validate intermediate structure
          3. Translate to Shuffle-native JSON
          4. Validate Shuffle format
          5. (Optional) Save to DB
          6. Return result

        Args:
            description:          NL description of the desired workflow
            environment:          Cloud / On-Prem / Hybrid
            target_integrations:  List of preferred app names
            dry_run:              If True, don't save to DB

        Returns:
            dict with intermediate, shuffle_workflow, validation results, and status
        """
        if target_integrations is None:
            target_integrations = []

        # ── Step 1: LLM generates intermediate JSON ───────────────────────────
        logger.info("Generating workflow from: %s", description[:80])
        intermediate = await self._generate_intermediate(
            description, environment, target_integrations
        )

        # ── Step 2: Validate intermediate ─────────────────────────────────────
        intermediate_validation = self._validate_intermediate(intermediate)
        if not intermediate_validation["valid"]:
            return {
                "success": False,
                "workflow": None,
                "shuffle_workflow": None,
                "validation": intermediate_validation,
                "errors": intermediate_validation["errors"],
            }

        # ── Step 3: Translate to Shuffle format ───────────────────────────────
        shuffle_workflow = self.translator.translate(intermediate)

        # ── Step 4: Validate Shuffle format ───────────────────────────────────
        shuffle_validation = self.translator._validate_locally(shuffle_workflow)

        # ── Step 5: Save to DB unless dry_run ────────────────────────────────
        playbook_id = None
        if not dry_run:
            playbook_id = await self._save_playbook(
                intermediate, shuffle_workflow, description, target_integrations
            )

        return {
            "success": True,
            "playbook_id": playbook_id,
            "workflow": intermediate,            # our intermediate schema
            "shuffle_workflow": shuffle_workflow, # Shuffle-native JSON ← deploy this
            "validation": intermediate_validation,
            "shuffle_validation": shuffle_validation,
            "dry_run": dry_run,
            "errors": [],
        }

    # ── LLM intermediate generation ───────────────────────────────────────────

    async def _generate_intermediate(
        self, description: str, environment: str, integrations: list[str]
    ) -> dict:
        """Use LLM to generate intermediate workflow JSON."""

        registry_hint = ""
        if integrations:
            registry_hint = (
                f"Preferred integrations: {', '.join(integrations)}. "
                "Use these app names exactly when appropriate."
            )

        system_prompt = f"""You are an expert Shuffle SOAR workflow designer.
Generate a complete security automation workflow JSON from the natural language description.

{registry_hint}
Environment: {environment}

OUTPUT FORMAT — respond ONLY with valid JSON, no markdown, no preamble:
{{
  "workflow_name": "<short descriptive name>",
  "workflow_description": "<1-2 sentence description>",
  "workflow_metadata": {{
    "environment": "{environment}",
    "version": "1.0",
    "generated_by": "LLM"
  }},
  "steps": [
    {{
      "step_id": "<uuid4>",
      "label": "<human readable label>",
      "app_name": "<shuffle_app_name>",
      "app_id": "<uuid4>",
      "app_version": "1.0.0",
      "action_name": "<action>",
      "category": "<Detection|Enrichment|Response|Notification|Ticketing|Utility>",
      "purpose": "<why this step>",
      "is_start_node": true,
      "position": {{"x": 100, "y": 100}},
      "parameters": [{{"name": "<param>", "value": "<value>", "required": true}}]
    }}
  ],
  "connections": [
    {{
      "source": "<step_id>",
      "target": "<step_id>",
      "relationship": "CONNECTS_TO",
      "condition": "on_success",
      "label": ""
    }}
  ]
}}

RULES:
- All step_id and app_id values MUST be valid UUID4 strings
- First step MUST have "is_start_node": true
- All connections MUST reference existing step_ids
- Use realistic app names: virustotal, slack, jira, microsoft_sentinel, splunk,
  crowdstrike, palo_alto, aws, active_directory, email, webhook, elasticsearch
- condition values: "always", "on_success", "on_failure"
- Generate 3-8 steps with logical flow

Generate the workflow now:
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Create a Shuffle SOAR workflow for: {description}"},
        ]

        msg = await self.llm.chat(messages, temperature=0.1, json_mode=True)
        raw = msg.get("content", "{}")

        try:
            result = json.loads(raw)
            return result
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"LLM returned invalid JSON. Raw: {raw[:300]}")

    # ── Intermediate validation ───────────────────────────────────────────────

    def _validate_intermediate(self, workflow: dict) -> dict:
        """Validate intermediate workflow structure."""
        errors = []
        warnings = []

        for field in ["workflow_name", "workflow_description", "steps", "connections"]:
            if not workflow.get(field):
                errors.append(f"Missing required field: {field}")

        if errors:
            return {"valid": False, "errors": errors, "warnings": warnings}

        steps = workflow.get("steps", [])
        step_ids = set()

        if not steps:
            errors.append("Workflow has no steps")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Check for start node
        start_nodes = [s for s in steps if s.get("is_start_node")]
        if not start_nodes:
            warnings.append("No is_start_node=true; first step will be used as start")

        for step in steps:
            sid = step.get("step_id")
            if not sid:
                errors.append("Step missing step_id")
                continue
            if not self._is_uuid(sid):
                errors.append(f"Invalid UUID step_id: {sid}")
            step_ids.add(sid)
            for field in ["label", "app_name", "action_name"]:
                if not step.get(field):
                    errors.append(f"Step {sid[:8]}... missing '{field}'")

        for conn in workflow.get("connections", []):
            if conn.get("source") not in step_ids:
                errors.append(f"Connection source not found: {conn.get('source', 'MISSING')}")
            if conn.get("target") not in step_ids:
                errors.append(f"Connection target not found: {conn.get('target', 'MISSING')}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "step_count": len(steps),
            "connection_count": len(workflow.get("connections", [])),
        }

    @staticmethod
    def _is_uuid(val: str) -> bool:
        try:
            uuid.UUID(val)
            return True
        except (ValueError, AttributeError):
            return False

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _save_playbook(
        self,
        intermediate: dict,
        shuffle_workflow: dict,
        original_description: str,
        integrations: list[str],
    ) -> str:
        """Save generated workflow to playbooks table."""
        playbook_id = shuffle_workflow.get("id", str(uuid.uuid4()))

        await self.db.execute(
            text("""
                INSERT INTO playbooks (
                    id, name, description, category, integrations,
                    shuffle_json, shuffle_workflow_id, is_active, created_at
                )
                VALUES (
                    :id, :name, :desc, :category, :integrations,
                    :json::jsonb, :wf_id, true, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    shuffle_json = EXCLUDED.shuffle_json,
                    updated_at = NOW()
            """),
            {
                "id": playbook_id,
                "name": intermediate.get("workflow_name", "Generated Workflow"),
                "desc": original_description,
                "category": "Generated",
                "integrations": integrations or [],
                "json": json.dumps(shuffle_workflow),
                "wf_id": playbook_id,
            },
        )
        await self.db.commit()
        logger.info("Saved generated playbook: %s", playbook_id)
        return playbook_id

    async def get_playbook(self, playbook_id: str) -> Optional[dict]:
        """Retrieve a generated playbook from the DB."""
        result = await self.db.execute(
            text("""
                SELECT id, name, description, shuffle_json, created_at
                FROM playbooks WHERE id = :id AND category = 'Generated'
            """),
            {"id": playbook_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "shuffle_workflow": row.shuffle_json,
            "created_at": str(row.created_at),
        }

    async def deploy_to_shuffle(self, playbook_id: str) -> dict:
        """Export a saved playbook to Shuffle."""
        pb = await self.get_playbook(playbook_id)
        if not pb:
            return {"success": False, "error": "Playbook not found"}
        workflow = pb["shuffle_workflow"]
        if isinstance(workflow, str):
            workflow = json.loads(workflow)
        return await self.translator.deploy_to_shuffle(workflow)
