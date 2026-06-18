"""Recommends a concrete next-best ACTION when reverse generation is not
possible or when an error occurs anywhere in the pipeline.

This is the fallback brain of the system: instead of returning an empty or
failed response, it returns prioritised, actionable guidance for the analyst.
"""
import json
from .llm import llm
from .recommendation import recommender


class ActionRecommender:
    async def recommend(self, *, trigger: str, reason: str,
                        context: str, error_detail: str | None = None) -> dict:
        """trigger: generation_not_possible | error | deployment_failed."""
        closest = await self._closest_playbook(context)

        # Try an LLM-authored action plan; fall back to a deterministic one.
        actions = await self._llm_actions(trigger, reason, context, error_detail, closest)
        if not actions:
            actions = self._deterministic_actions(trigger, closest)

        return {
            "trigger": trigger,
            "reason": reason,
            "recommended_actions": actions,
            "closest_playbook": closest,
        }

    async def _closest_playbook(self, context: str) -> str | None:
        try:
            hits = await recommender.recommend(context, top_k=1)
            return hits[0]["slug"] if hits else None
        except Exception:
            return None

    async def _llm_actions(self, trigger, reason, context, error_detail, closest):
        system = ("You are a senior SOC engineer. Generation of an automated playbook "
                  "failed. Recommend 2-4 concrete fallback actions a human analyst should "
                  "take now. Respond ONLY as JSON: "
                  '{"actions": [{"priority": int, "action": str, "detail": str}]}.')
        prompt = json.dumps({
            "trigger": trigger, "reason": reason, "context": context,
            "error_detail": error_detail, "closest_existing_playbook": closest,
        })
        try:
            data = await llm.complete_json(prompt, system=system)
            return data.get("actions") or []
        except Exception:
            return []

    @staticmethod
    def _deterministic_actions(trigger: str, closest: str | None) -> list[dict]:
        base = []
        if closest:
            base.append({"priority": 1, "action": "Use the closest existing playbook",
                         "detail": f"Run or adapt '{closest}', which best matches this scenario."})
        if trigger == "deployment_failed":
            base.append({"priority": 2, "action": "Verify Shuffle connectivity",
                         "detail": "Check SHUFFLE_API_URL/KEY and that the required apps are installed in Shuffle."})
        base.append({"priority": len(base) + 1, "action": "Escalate for manual handling",
                     "detail": "Open a ticket and assign a tier-2 analyst to handle this case manually."})
        base.append({"priority": len(base) + 1, "action": "Capture details for tuning",
                     "detail": "Record the request so the dataset/registry can be extended to cover it."})
        return base


action_recommender = ActionRecommender()
