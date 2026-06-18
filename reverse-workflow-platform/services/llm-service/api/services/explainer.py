"""Explains a playbook's steps and descriptions in analyst-friendly language."""
import json
from .llm import llm


class Explainer:
    async def explain(self, playbook: dict) -> dict:
        """playbook: {slug, name, description, steps:[{order,title,app,action,detail}]}."""
        steps = playbook.get("steps") or []
        system = ("You are a SOC analyst trainer. For each playbook step, explain in plain "
                  "language WHAT it does and WHY it matters. Respond ONLY as JSON: "
                  '{"summary": str, "steps": [{"order": int, "title": str, "what": str, "why": str}]}.')
        prompt = json.dumps({
            "name": playbook.get("name"),
            "description": playbook.get("description"),
            "steps": steps,
        })
        try:
            data = await llm.complete_json(prompt, system=system)
            return {
                "slug": playbook.get("slug"),
                "name": playbook.get("name"),
                "summary": data.get("summary", playbook.get("description", "")),
                "step_explanations": data.get("steps", self._deterministic(steps)),
            }
        except Exception:
            # Deterministic fallback so the endpoint never hard-fails
            return {
                "slug": playbook.get("slug"),
                "name": playbook.get("name"),
                "summary": playbook.get("description", ""),
                "step_explanations": self._deterministic(steps),
            }

    @staticmethod
    def _deterministic(steps: list[dict]) -> list[dict]:
        out = []
        for s in steps:
            out.append({
                "order": s.get("order"),
                "title": s.get("title", s.get("action", "Step")),
                "what": s.get("detail", f"Runs {s.get('action','an action')} on {s.get('app','an app')}."),
                "why": "Part of the automated response sequence for this scenario.",
            })
        return out


explainer = Explainer()
