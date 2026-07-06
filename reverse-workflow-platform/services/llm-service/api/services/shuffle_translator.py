"""Translate intermediate workflow JSON -> Shuffle-native deployment JSON.

Schema verified against the official shuffle-shared v0.9.91 Go structs
(Action, Branch, Position, Workflow) used by the user's local Shuffle build.

Key schema facts (authoritative, from structs.go):
  * Action node id field is "id" (json:"id"), NOT "id_".
  * Start-node flag is "isStartNode" (json:"isStartNode,omitempty"), camelCase.
  * Actions carry: app_id, app_name, app_version, label, name, description,
    environment, errors, is_valid, large_image, parameters, position,
    priority, execution_delay, category.
  * Branch carries: id, source_id, destination_id, label, has_errors,
    conditions, decorator.
  * Workflow carries: id, name, description, start, actions, branches,
    triggers, is_valid, errors, tags, workflow_variables, comments.
  * The workflow-level "start" field is the real determinant of the start
    node, so it is always set to the first action's id.
"""
import uuid
from .app_registry import app_registry
from ..config import get_settings

DEFAULT_ENVIRONMENT = "Shuffle"


class ShuffleTranslator:
    def __init__(self, environment: str = DEFAULT_ENVIRONMENT):
        self.environment = environment

    def translate(self, intermediate: dict, environment: str | None = None) -> dict:
        """Convert intermediate representation to Shuffle-native workflow JSON."""
        env = environment or self.environment
        name = intermediate.get("name", "Generated Workflow")
        description = intermediate.get("description", "")
        nodes = intermediate.get("nodes", [])
        wf_id = uuid.uuid4().hex

        actions, id_map = [], {}
        for idx, node in enumerate(nodes):
            node_id = uuid.uuid4().hex
            id_map[node.get("id")] = node_id
            app = app_registry.resolve(node.get("app"))

            x = 250.0 + (idx % 3) * 250.0
            y = 150.0 + (idx // 3) * 200.0
            is_start = (idx == 0)

            actions.append({
                "app_name": app["name"],
                "app_version": app.get("version", "1.0.0"),
                "app_id": app["app_id"],
                "description": node.get("description", ""),
                "errors": [],
                "id": node_id,
                "is_valid": True,
                "isStartNode": is_start,
                "label": node.get("label") or app.get("display", app["name"]),
                "large_image": app.get("image_url", ""),
                "environment": env,
                "name": node.get("action", "action"),
                "parameters": [
                    {
                        "name": k,
                        "value": v if isinstance(v, str) else str(v),
                        "required": True,
                        "configuration": False,
                        "id": uuid.uuid4().hex,
                    }
                    for k, v in (node.get("parameters") or {}).items()
                ],
                "position": {"x": x, "y": y},
                "priority": 0,
                "execution_delay": node.get("execution_delay", 0),
                "category": app.get("category", ""),
            })

        branches = []
        for edge in intermediate.get("edges", []):
            src, dst = id_map.get(edge.get("from")), id_map.get(edge.get("to"))
            if src and dst:
                branches.append({
                    "destination_id": dst,
                    "id": uuid.uuid4().hex,
                    "source_id": src,
                    "label": "",
                    "has_errors": False,
                    "conditions": [],
                    "decorator": False,
                })

        start = id_map.get(intermediate.get("start")) or (actions[0]["id"] if actions else "")

        return {
            "id": wf_id,
            "name": name,
            "description": description,
            "start": start,
            "actions": actions,
            "branches": branches,
            "triggers": [],
            "is_valid": True,
            "errors": [],
            "tags": ["ai-generated"],
            "workflow_variables": [],
            "comments": [],
        }

    @staticmethod
    def validate_intermediate(data: dict) -> list[str]:
        errors = []
        if not data.get("nodes"):
            errors.append("No nodes defined.")
        ids = {n.get("id") for n in data.get("nodes", [])}
        for n in data.get("nodes", []):
            if not n.get("app") or not n.get("action"):
                errors.append(f"Node {n.get('id')} missing app/action.")
        for e in data.get("edges", []):
            if e.get("from") not in ids or e.get("to") not in ids:
                errors.append(f"Edge {e} references unknown node.")
        return errors

    @staticmethod
    def validate_shuffle(wf: dict) -> list[str]:
        """Validate against the required shuffle-shared workflow fields."""
        errors = []
        for field in ("id", "name", "actions", "start", "branches"):
            if field not in wf:
                errors.append(f"Missing field: {field}")
        if not wf.get("actions"):
            errors.append("Workflow has no actions.")
        action_ids = {a.get("id") for a in wf.get("actions", [])}
        if wf.get("start") and wf["start"] not in action_ids:
            errors.append("start does not reference a valid action id.")
        for b in wf.get("branches", []):
            if b.get("source_id") not in action_ids or b.get("destination_id") not in action_ids:
                errors.append(f"Branch {b.get('id')} references unknown action.")
        starts = [a for a in wf.get("actions", []) if a.get("isStartNode")]
        if len(starts) != 1:
            errors.append(f"Expected exactly 1 start node, found {len(starts)}.")
        return errors


shuffle_translator = ShuffleTranslator(environment=get_settings().shuffle_environment)
