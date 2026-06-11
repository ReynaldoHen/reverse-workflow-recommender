"""
Semi-agentic refinement layer.

Runs AFTER Simple RAG. Uses Ollama tool calling to verify recommendations
against the analyst's actual environment and adjust confidence scores.

Tools:
  - verify_integration_compatibility
  - check_required_customizations
  - flag_config_gaps
"""
import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from schemas import AgentVerification, AnalystContext, RecommendedPlaybook
from services.llm import get_llm_client

logger = logging.getLogger(__name__)

# ── Tool definitions (Ollama / OpenAI format) ─────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "verify_integration_compatibility",
            "description": (
                "Check whether a playbook's required integrations are all present "
                "in the analyst's Shuffle environment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playbook_id": {"type": "string", "description": "Playbook UUID"},
                    "analyst_integrations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of integrations available to the analyst",
                    },
                },
                "required": ["playbook_id", "analyst_integrations"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_required_customizations",
            "description": (
                "Identify configuration or customisation steps the analyst "
                "must perform before the playbook is ready to use."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playbook_id": {"type": "string"},
                    "environment": {
                        "type": "string",
                        "description": "Analyst's environment (e.g. azure, aws, on-prem)",
                    },
                },
                "required": ["playbook_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_config_gaps",
            "description": (
                "Identify missing API keys, secrets, or service connections "
                "the analyst has not yet configured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "playbook_id": {"type": "string"},
                    "api_keys_configured": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Integrations for which API keys are already set",
                    },
                },
                "required": ["playbook_id"],
            },
        },
    },
]


class SemiAgenticService:
    MAX_ITERATIONS = 3

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def refine(
        self,
        recommendations: list[RecommendedPlaybook],
        analyst_context: AnalystContext,
    ) -> list[RecommendedPlaybook]:
        """
        Run the agentic refinement loop for the top recommendation (or all of them).
        Returns the same list with adjusted confidence scores and agent_verification data.
        """
        refined = []
        for rec in recommendations:
            try:
                verified = await self._verify_one(rec, analyst_context)
                refined.append(verified)
            except Exception as e:
                logger.warning("Refinement failed for %s: %s", rec.id, e)
                refined.append(rec)  # fallback: keep original
        return refined

    async def _verify_one(
        self, rec: RecommendedPlaybook, ctx: AnalystContext
    ) -> RecommendedPlaybook:
        """Run tool-calling loop for a single playbook recommendation."""

        system_msg = {
            "role": "system",
            "content": (
                "You are verifying a Shuffle SOAR playbook recommendation against an analyst's environment.\n"
                "Use the available tools to check compatibility, customisations, and config gaps.\n"
                "Call each tool once for the given playbook, then stop."
            ),
        }
        user_msg = {
            "role": "user",
            "content": (
                f"Verify playbook '{rec.name}' (ID: {rec.id}) for this environment:\n"
                f"Available integrations: {ctx.available_integrations}\n"
                f"API keys configured: {ctx.api_keys_configured}\n"
                f"Environment: {ctx.environment or 'not specified'}\n\n"
                "Use the tools to check compatibility, customisations, and config gaps."
            ),
        }

        messages = [system_msg, user_msg]
        tool_results: dict[str, dict] = {}

        # ── Agentic loop ──────────────────────────────────────────────────────
        for iteration in range(self.MAX_ITERATIONS):
            response_msg = await self.llm.chat(messages, tools=TOOLS, temperature=0.0)

            # No more tool calls → done
            if not response_msg.get("tool_calls"):
                break

            # Append assistant turn
            messages.append(response_msg)

            # Execute all tool calls
            for call in response_msg["tool_calls"]:
                fn_name = call["function"]["name"]
                args_raw = call["function"].get("arguments", "{}")
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                result = await self._execute_tool(fn_name, args, rec, ctx)
                tool_results[fn_name] = result

                # Feed result back
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result),
                })

            # All three tools done
            if len(tool_results) >= 3:
                break

        # ── Build AgentVerification from collected results ────────────────────
        compat = tool_results.get("verify_integration_compatibility", {})
        custom = tool_results.get("check_required_customizations", {})
        gaps = tool_results.get("flag_config_gaps", {})

        verification = AgentVerification(
            compatible=compat.get("compatible", True),
            missing_integrations=compat.get("missing_integrations", []),
            coverage_pct=compat.get("coverage_pct", 1.0),
            customization_required=custom.get("customization_required", False),
            customization_steps=custom.get("steps", []),
            config_gaps=gaps.get("gaps", []),
        )

        # ── Adjust confidence score ───────────────────────────────────────────
        adjusted_score = rec.confidence_score

        # Penalise for missing integrations
        if verification.missing_integrations:
            penalty = 0.1 * len(verification.missing_integrations)
            adjusted_score = max(0.0, adjusted_score - penalty)

        # Penalise for high-severity config gaps
        high_gaps = sum(1 for g in verification.config_gaps if g.get("severity") == "high")
        if high_gaps:
            adjusted_score = max(0.0, adjusted_score - 0.05 * high_gaps)

        # Penalise for incomplete coverage
        adjusted_score *= (0.7 + 0.3 * verification.coverage_pct)
        adjusted_score = round(adjusted_score, 3)

        return rec.model_copy(update={
            "confidence_score": adjusted_score,
            "agent_verification": verification,
            "modifications": rec.modifications + verification.customization_steps,
        })

    # ── Tool implementations ──────────────────────────────────────────────────

    async def _execute_tool(
        self, fn_name: str, args: dict,
        rec: RecommendedPlaybook, ctx: AnalystContext
    ) -> dict:
        if fn_name == "verify_integration_compatibility":
            return await self._tool_verify_compat(rec, ctx)
        elif fn_name == "check_required_customizations":
            return await self._tool_check_customizations(rec, ctx)
        elif fn_name == "flag_config_gaps":
            return await self._tool_flag_gaps(rec, ctx)
        return {"error": f"Unknown tool: {fn_name}"}

    async def _tool_verify_compat(
        self, rec: RecommendedPlaybook, ctx: AnalystContext
    ) -> dict:
        """Check if playbook integrations overlap with analyst's available ones."""
        available = [i.lower() for i in ctx.available_integrations]
        required = [i.lower() for i in rec.integrations]

        missing = [r for r in required if r not in available]
        coverage = (len(required) - len(missing)) / max(len(required), 1)

        return {
            "compatible": len(missing) == 0,
            "missing_integrations": missing,
            "coverage_pct": round(coverage, 2),
            "note": (
                f"Playbook requires {len(required)} integrations; "
                f"{len(required) - len(missing)} available."
            ),
        }

    async def _tool_check_customizations(
        self, rec: RecommendedPlaybook, ctx: AnalystContext
    ) -> dict:
        """Fetch playbook JSON from DB and derive required customisation steps."""
        result = await self.db.execute(
            text("SELECT shuffle_json, category, triggers FROM playbooks WHERE id = :id"),
            {"id": rec.id},
        )
        row = result.fetchone()
        steps = []

        if row:
            # Generic steps based on category
            category = (row.category or "").lower()
            if "phishing" in category:
                steps.append("Configure email parser action with your mail gateway settings")
            if "ransomware" in category or "malware" in category:
                steps.append("Set sandbox environment URL in the malware analysis action")
            if "cloud" in category:
                env = ctx.environment or "cloud"
                steps.append(f"Update cloud provider credentials for {env} environment")

            # Integration-specific steps
            for intg in rec.integrations:
                if intg.lower() not in [a.lower() for a in ctx.api_keys_configured]:
                    steps.append(f"Add {intg} API key to Shuffle App authentication")

        return {
            "customization_required": len(steps) > 0,
            "steps": steps,
            "difficulty": "medium" if len(steps) > 3 else "easy",
        }

    async def _tool_flag_gaps(
        self, rec: RecommendedPlaybook, ctx: AnalystContext
    ) -> dict:
        """Flag API key / config gaps between required and configured integrations."""
        configured = [a.lower() for a in ctx.api_keys_configured]
        gaps = []

        for intg in rec.integrations:
            if intg.lower() not in configured:
                severity = "high" if intg.lower() in ["virustotal", "crowdstrike", "sentinel"] else "medium"
                gaps.append({
                    "integration": intg,
                    "gap": f"API key not configured for {intg}",
                    "severity": severity,
                    "action": f"Add {intg} credentials in Shuffle App Authentication settings",
                })

        return {
            "has_gaps": len(gaps) > 0,
            "gaps": gaps,
            "total_gaps": len(gaps),
        }
