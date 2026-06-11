"""
Shuffle Translator — Natural Language → Shuffle SOAR Deployment Format.

This module is the core of the work plan's "Translator Engine":
  LLM intermediate format → Shuffle-native workflow JSON

The translator:
  1. Receives our intermediate workflow schema (NL-derived)
  2. Resolves real Shuffle app_ids from the App Registry
  3. Outputs proper Shuffle workflow JSON ready for import/execution
  4. Optionally deploys directly to a Shuffle instance

Shuffle Workflow JSON structure:
{
  "id": "<uuid>",
  "name": "<string>",
  "description": "<string>",
  "start": "<action_id>",
  "actions": [...],
  "branches": [...],
  "triggers": [...],
  "tags": [...],
  "owner": "",
  "org_id": ""
}
"""
import json
import logging
import uuid
from typing import Optional

import httpx

from config import get_settings
from services.app_registry import get_app_registry

logger = logging.getLogger(__name__)
settings = get_settings()


class ShuffleTranslator:
    """
    Translates our intermediate workflow format → Shuffle-native JSON.

    The intermediate format (output from playbook_generator.py) uses our
    custom schema with app_name, action_name, parameters, and connections.

    The Shuffle native format uses:
    - actions[].id (UUID)
    - actions[].app_id (real Shuffle app UUID)
    - actions[].app_name
    - actions[].action (action identifier)
    - actions[].parameters (list of {name, value} dicts)
    - branches[].source_id + destination_id (step connections)
    - triggers[] (workflow entry points)
    """

    def __init__(self):
        self.registry = get_app_registry()

    # ── Main entry point ──────────────────────────────────────────────────────

    def translate(self, intermediate: dict) -> dict:
        """
        Translate intermediate workflow JSON → Shuffle native format.

        Args:
            intermediate: Our workflow schema with steps[] and connections[]

        Returns:
            Shuffle-native workflow JSON dict
        """
        workflow_id = str(uuid.uuid4())
        steps = intermediate.get("steps", [])
        connections = intermediate.get("connections", [])

        # ── Build Shuffle actions ─────────────────────────────────────────────
        actions = []
        action_id_map: dict[str, str] = {}  # intermediate step_id → shuffle action id

        for i, step in enumerate(steps):
            step_id = step.get("step_id", str(uuid.uuid4()))
            app_name = step.get("app_name", "http_request")
            action_name = step.get("action_name", "execute")

            # Resolve real app_id from registry
            app_entry = self.registry.resolve_app(app_name)
            if app_entry:
                real_app_id = app_entry["app_id"]
                real_app_name = app_entry["app_key"]
                # Resolve real action name
                action_entry = self.registry.resolve_action(app_name, action_name)
                real_action = action_entry.get("action_key", action_name) if action_entry else action_name
            else:
                # Unknown app — use deterministic ID + keep names as-is
                real_app_id = self.registry.get_app_id(app_name)
                real_app_name = app_name
                real_action = action_name
                logger.debug("Unknown app '%s' — using generated ID", app_name)

            # Build parameter list
            params = self._build_parameters(
                step.get("parameters", []),
                app_name=real_app_name,
                action_name=real_action,
            )

            # Compute position (vertical stack by default)
            pos_x = step.get("position", {}).get("x", 100)
            pos_y = step.get("position", {}).get("y", 100 + i * 200)

            shuffle_action = {
                "id": step_id,
                "app_id": real_app_id,
                "app_name": real_app_name,
                "app_version": step.get("app_version", "1.0.0"),
                "label": step.get("label", f"Step {i+1}"),
                "name": real_action,
                "action": real_action,
                "parameters": params,
                "position": {"x": pos_x, "y": pos_y},
                "priority": 0,
                "authentication_id": "",
                "environment": step.get(
                    "environment",
                    intermediate.get("workflow_metadata", {}).get("environment", "Shuffle")
                ),
                "is_valid": True,
                "errors": [],
            }
            actions.append(shuffle_action)
            action_id_map[step_id] = step_id  # IDs stay same in this translation

        # ── Build Shuffle branches (connections) ─────────────────────────────
        branches = []
        for conn in connections:
            src = conn.get("source", "")
            tgt = conn.get("target", "")
            if not src or not tgt:
                continue

            condition_str = conn.get("condition", "always")
            shuffle_condition = self._map_condition(condition_str)

            branch = {
                "id": str(uuid.uuid4()),
                "source_id": src,
                "destination_id": tgt,
                "label": conn.get("label", ""),
                "conditions": shuffle_condition,
                "has_errors": False,
            }
            branches.append(branch)

        # ── Identify start node ───────────────────────────────────────────────
        start_nodes = [s for s in steps if s.get("is_start_node")]
        start_action_id = (
            start_nodes[0]["step_id"] if start_nodes
            else (steps[0]["step_id"] if steps else "")
        )

        # ── Build Shuffle triggers ────────────────────────────────────────────
        triggers = self._build_triggers(intermediate, start_action_id)

        # ── Assemble final Shuffle workflow ───────────────────────────────────
        metadata = intermediate.get("workflow_metadata", {})
        shuffle_workflow = {
            "id": workflow_id,
            "name": intermediate.get("workflow_name", "Generated Workflow"),
            "description": intermediate.get("workflow_description", ""),
            "start": start_action_id,
            "actions": actions,
            "branches": branches,
            "triggers": triggers,
            "tags": self._extract_tags(intermediate),
            "owner": "",
            "org_id": "",
            "execution_environment": metadata.get("environment", "Shuffle"),
            "workflow_variables": [],
            "generated_by": metadata.get("generated_by", "LLM"),
            "version": metadata.get("version", "1.0"),
            "_metadata": {
                "generated_from": "ai_playbook_recommender",
                "intermediate_schema_version": "1.0",
                "translation_engine": "ShuffleTranslator",
                "app_registry": "offline+online",
            },
        }

        logger.info(
            "Translated workflow '%s': %d actions, %d branches",
            shuffle_workflow["name"],
            len(actions),
            len(branches),
        )
        return shuffle_workflow

    # ── Parameter builder ─────────────────────────────────────────────────────

    def _build_parameters(
        self, raw_params: list[dict], app_name: str, action_name: str
    ) -> list[dict]:
        """
        Convert intermediate parameters → Shuffle parameter format.
        Adds registry-suggested parameters if none provided.
        """
        shuffle_params = []

        # Use provided parameters
        for p in raw_params:
            if not p.get("name"):
                continue
            shuffle_params.append({
                "name": p["name"],
                "value": str(p.get("value", "")),
                "required": bool(p.get("required", False)),
                "configuration": False,
                "tags": None,
                "schema": {"type": "string"},
            })

        # If no parameters, add registry hints
        if not shuffle_params:
            action_entry = self.registry.resolve_action(app_name, action_name)
            if action_entry:
                for pname in action_entry.get("parameters", []):
                    shuffle_params.append({
                        "name": pname,
                        "value": f"${{{pname}}}",  # template variable
                        "required": True,
                        "configuration": False,
                        "tags": None,
                        "schema": {"type": "string"},
                    })

        return shuffle_params

    # ── Condition mapping ─────────────────────────────────────────────────────

    def _map_condition(self, condition: str) -> list[dict]:
        """
        Map intermediate condition strings → Shuffle branch conditions.
        Shuffle uses a conditions array with filter objects.
        """
        condition_lower = condition.lower()

        if "always" in condition_lower or not condition_lower:
            return []  # Empty = always execute

        if "success" in condition_lower:
            return [{
                "condition": {"value": "EXECUTION_ARGUMENT", "operator": "=", "not": False},
                "source": {"parameter": {"value": "success"}, "type": "variable"},
            }]

        if "failure" in condition_lower or "fail" in condition_lower:
            return [{
                "condition": {"value": "EXECUTION_ARGUMENT", "operator": "=", "not": True},
                "source": {"parameter": {"value": "success"}, "type": "variable"},
            }]

        # Passthrough for custom condition strings
        return [{"raw_condition": condition}]

    # ── Trigger builder ───────────────────────────────────────────────────────

    def _build_triggers(self, intermediate: dict, start_action_id: str) -> list[dict]:
        """Build Shuffle trigger definition from workflow metadata."""
        trigger_type = "manual"  # default

        # Infer from metadata or first step label
        steps = intermediate.get("steps", [])
        if steps:
            first_label = steps[0].get("label", "").lower()
            first_app = steps[0].get("app_name", "").lower()
            if "webhook" in first_label or "webhook" in first_app:
                trigger_type = "webhook"
            elif "schedule" in first_label or "cron" in first_label:
                trigger_type = "schedule"

        if trigger_type == "webhook":
            return [{
                "id": str(uuid.uuid4()),
                "name": "Webhook Trigger",
                "type": "WEBHOOK",
                "start": start_action_id,
                "status": "running",
                "environment": "Shuffle",
                "auth": str(uuid.uuid4()),
            }]

        # Default: manual trigger
        return [{
            "id": str(uuid.uuid4()),
            "name": "Manual Trigger",
            "type": "MANUAL",
            "start": start_action_id,
            "status": "stopped",
            "environment": "Shuffle",
        }]

    # ── Tag extractor ─────────────────────────────────────────────────────────

    def _extract_tags(self, intermediate: dict) -> list[str]:
        """Extract meaningful tags from workflow metadata."""
        tags = []
        metadata = intermediate.get("workflow_metadata", {})

        if env := metadata.get("environment"):
            tags.append(env.lower())

        if gen := metadata.get("generated_by"):
            tags.append(gen.lower())

        # Add category tags from steps
        categories = set()
        for step in intermediate.get("steps", []):
            if cat := step.get("category"):
                categories.add(cat.lower())
        tags.extend(list(categories)[:5])  # Limit to 5

        return tags

    # ── Shuffle API deployment ────────────────────────────────────────────────

    async def deploy_to_shuffle(self, shuffle_workflow: dict) -> dict:
        """
        POST the translated workflow to a Shuffle instance.

        Args:
            shuffle_workflow: Translated Shuffle-native workflow dict

        Returns:
            dict with success, shuffle_workflow_id, and any errors
        """
        if not settings.shuffle_api_url or not settings.shuffle_api_key:
            return {
                "success": False,
                "error": "Shuffle API URL and key not configured. "
                         "Set SHUFFLE_API_URL and SHUFFLE_API_KEY in .env",
            }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{settings.shuffle_api_url}/api/v1/workflows",
                    json=shuffle_workflow,
                    headers={"Authorization": f"Bearer {settings.shuffle_api_key}"},
                )

            if resp.status_code in [200, 201]:
                data = resp.json()
                return {
                    "success": True,
                    "shuffle_workflow_id": data.get("id", shuffle_workflow["id"]),
                    "shuffle_url": (
                        f"{settings.shuffle_api_url}/workflows/{data.get('id', '')}"
                    ),
                }
            else:
                return {
                    "success": False,
                    "error": f"Shuffle returned {resp.status_code}: {resp.text[:200]}",
                }

        except Exception as e:
            logger.error("Shuffle deploy failed: %s", e)
            return {"success": False, "error": str(e)}

    async def validate_with_shuffle(self, shuffle_workflow: dict) -> dict:
        """
        Dry-run: validate the workflow with Shuffle without importing it.
        Falls back to local structural validation if Shuffle unavailable.
        """
        if settings.shuffle_api_url and settings.shuffle_api_key:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{settings.shuffle_api_url}/api/v1/workflows/validate",
                        json=shuffle_workflow,
                        headers={"Authorization": f"Bearer {settings.shuffle_api_key}"},
                    )
                if resp.status_code == 200:
                    return {"compatible": True, "source": "shuffle_api"}
                return {
                    "compatible": False,
                    "source": "shuffle_api",
                    "error": resp.text[:200],
                }
            except Exception:
                pass  # Fall through to local validation

        # Local structural validation fallback
        return self._validate_locally(shuffle_workflow)

    def _validate_locally(self, workflow: dict) -> dict:
        """Validate Shuffle workflow structure locally."""
        errors = []
        action_ids = {a["id"] for a in workflow.get("actions", [])}

        if not workflow.get("name"):
            errors.append("Missing workflow name")
        if not workflow.get("actions"):
            errors.append("Workflow must have at least one action")

        for branch in workflow.get("branches", []):
            if branch.get("source_id") not in action_ids:
                errors.append(f"Branch source {branch.get('source_id')} not in actions")
            if branch.get("destination_id") not in action_ids:
                errors.append(f"Branch destination {branch.get('destination_id')} not in actions")

        start = workflow.get("start", "")
        if start and start not in action_ids:
            errors.append(f"Start action {start} not found")

        return {
            "compatible": len(errors) == 0,
            "source": "local",
            "errors": errors,
        }


# ── Module-level helpers ──────────────────────────────────────────────────────

def translate_to_shuffle(intermediate: dict) -> dict:
    """Convenience function: translate intermediate → Shuffle format."""
    return ShuffleTranslator().translate(intermediate)


def validate_shuffle_workflow(workflow: dict) -> dict:
    """Convenience function: locally validate a Shuffle workflow."""
    return ShuffleTranslator()._validate_locally(workflow)
