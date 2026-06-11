"""Ollama LLM client — chat, tool calling, structured JSON output."""
import json
import logging
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMClient:
    """Async client for Ollama /api/chat."""

    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> dict:
        """Send chat request. Returns the assistant message dict."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 1024,
            },
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {})

    async def classify_intent(self, query: str) -> str:
        """Classify query intent into one of 4 categories."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You classify SOC analyst queries into exactly one of these intents: "
                    "recommend_existing, modify_existing, explain_playbook, generate_new.\n"
                    "respond with ONLY the intent label, nothing else."
                ),
            },
            {"role": "user", "content": query},
        ]
        msg = await self.chat(messages, temperature=0.0)
        raw = msg.get("content", "recommend_existing").strip().lower()
        valid = {"recommend_existing", "modify_existing", "explain_playbook", "generate_new"}
        return raw if raw in valid else "recommend_existing"

    async def recommend(
        self,
        query: str,
        intent: str,
        candidates: list[dict],
        conversation_history: list[dict],
        top_k: int = 3,
    ) -> dict:
        """Generate structured recommendation from retrieved candidates."""
        context_str = "\n\n".join(
            f"[{i+1}] ID={c['id']} | {c['name']}\n"
            f"    Category: {c['category']}\n"
            f"    Description: {c['description']}\n"
            f"    Integrations: {', '.join(c['integrations'])}\n"
            f"    Use cases: {', '.join(c.get('use_cases', []))}"
            for i, c in enumerate(candidates)
        )

        system_prompt = f"""You are an expert SOC automation advisor for Shuffle SOAR.
Given the analyst's query and retrieved playbooks, recommend the best {top_k} playbooks.

Intent detected: {intent}

Retrieved playbooks (ranked by relevance):
{context_str}

Respond ONLY with valid JSON matching this exact schema (no preamble, no markdown fences):
{{
  "recommended_playbooks": ["<id1>", "<id2>", "<id3>"],
  "confidence_scores": [0.92, 0.87, 0.73],
  "reasoning": ["<why pb1 fits>", "<why pb2 fits>", "<why pb3 fits>"],
  "required_integrations": ["<tool1>", "<tool2>"],
  "modifications": ["<step1>", "<step2>"],
  "fallback_message": ""
}}

Rules:
- Only include IDs from the retrieved list above.
- confidence_scores must sum to at most 3.0 and each be between 0.0 and 1.0.
- If no playbook fits well (all scores < 0.4), set fallback_message explaining this.
- modifications = specific configuration steps the analyst needs to do.
- Keep reasoning concise (1-2 sentences per playbook).
"""

        messages = [
            {"role": "system", "content": system_prompt},
            *conversation_history[-4:],  # last 2 turns
            {"role": "user", "content": query},
        ]

        msg = await self.chat(messages, json_mode=True)
        raw = msg.get("content", "{}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON: %s", raw[:200])
            return {"recommended_playbooks": [], "confidence_scores": [], "reasoning": [],
                    "required_integrations": [], "modifications": [],
                    "fallback_message": "Could not parse recommendation. Please try rephrasing."}

    async def is_healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False


_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
