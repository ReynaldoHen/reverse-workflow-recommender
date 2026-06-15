"""Ollama client wrapper with JSON-safe generation and retries."""
import json
import re
import httpx
from ..config import get_settings

settings = get_settings()


class LLM:
    def __init__(self):
        self._url = f"{settings.ollama_host}/api/generate"

    async def complete(self, prompt: str, system: str = "", temperature: float | None = None) -> str:
        payload = {
            "model": settings.llm_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": settings.llm_temperature if temperature is None else temperature},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(self._url, json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")

    async def complete_json(self, prompt: str, system: str = "") -> dict:
        """Ask the model for JSON, retry, then fall back to regex extraction."""
        last_err = ""
        for _ in range(settings.llm_max_retries):
            raw = await self.complete(prompt, system=system)
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                last_err = str(exc)
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except json.JSONDecodeError:
                        continue
        raise ValueError(f"LLM did not return valid JSON after retries: {last_err}")


llm = LLM()
