"""Reverse pipeline: NL description -> LLM intermediate JSON -> Shuffle JSON.

If generation is not possible (no valid workflow after retries / no usable apps)
or any error occurs, the caller is expected to invoke the Action Recommender.
This module signals that by returning success=False with an error reason.
"""
import json
from .llm import llm
from .shuffle_translator import shuffle_translator
from .app_registry import app_registry

SYSTEM = (
    "You design SOAR workflows. Convert the analyst's description into an "
    "intermediate workflow JSON. Respond ONLY with JSON of the form: "
    '{"name": str, "start": "n1", "nodes": [{"id": "n1", "app": "virustotal", '
    '"action": "lookup_url", "parameters": {"url": "${url}"}}], '
    '"edges": [{"from": "n1", "to": "n2", "conditions": []}]}. '
    "Use only app keys from the provided registry list."
)


class PlaybookGenerator:
    async def generate(self, description: str, target_integrations: list[str] | None = None) -> dict:
        registry_keys = [a["name"] for a in app_registry.all()]
        prompt = json.dumps({
            "description": description,
            "preferred_apps": target_integrations or [],
            "available_app_keys": registry_keys,
        })
        try:
            intermediate = await llm.complete_json(prompt, system=SYSTEM)
        except Exception as exc:
            return {"success": False, "error": f"LLM could not produce valid workflow JSON: {exc}"}

        errors = shuffle_translator.validate_intermediate(intermediate)
        if errors:
            return {"success": False, "error": "Intermediate validation failed: " + "; ".join(errors),
                    "intermediate": intermediate}

        # If no node maps to a known app, treat generation as not possible.
        known = [n for n in intermediate.get("nodes", [])
                 if not app_registry.resolve(n.get("app")).get("_synthetic")]
        if not known:
            return {"success": False,
                    "error": "No requested integrations are available in the app registry.",
                    "intermediate": intermediate}

        shuffle_wf = shuffle_translator.translate(intermediate)
        wf_errors = shuffle_translator.validate_shuffle(shuffle_wf)
        if wf_errors:
            return {"success": False, "error": "Shuffle validation failed: " + "; ".join(wf_errors),
                    "intermediate": intermediate}

        return {"success": True, "intermediate": intermediate, "shuffle_workflow": shuffle_wf}


playbook_generator = PlaybookGenerator()
