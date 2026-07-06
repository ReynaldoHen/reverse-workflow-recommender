"""Ollama client wrapper with JSON-safe generation and retries."""
import json
import re
import httpx
from ..config import get_settings

settings = get_settings()


class LLM:
    def __init__(self):
        self._url = f"{settings.ollama_host}/api/generate"
        print("OLLAMA URL =", self._url)

    async def complete(self, prompt: str, system: str = "", temperature: float | None = None) -> str:
        payload = {
            "model": settings.llm_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "think": settings.llm_think,
            "options": {
                "temperature": settings.llm_temperature if temperature is None else temperature,
                "top_p": settings.llm_top_p,
                "top_k": settings.llm_top_k,
                "presence_penalty": settings.llm_presence_penalty,
                "num_predict": settings.llm_num_predict,
                "num_ctx": settings.llm_num_ctx,
            },
        }
        if settings.llm_format:
            payload["format"] = settings.llm_format
        timeout = httpx.Timeout(
            connect=10.0,
            read=float(settings.ollama_read_timeout),
            write=30.0,
            pool=10.0,
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "") or ""
            thinking = data.get("thinking", "") or ""
            print(f"[llm] raw response len={len(raw)} thinking len={len(thinking)}")
            if not raw.strip():
                print(f"[llm] EMPTY response. thinking_preview={thinking[:300]!r}")
            return self._strip_thinking(raw)

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Buang blok reasoning Qwen3 agar tersisa konten/JSON.

        Menangani <think>...</think> lengkap maupun penutup </think> saja.
        JANGAN kembalikan string kosong bila pembersihan menghapus segalanya —
        kembalikan teks asli agar pemanggil (_extract_json) tetap bisa mencari JSON.
        """
        if not text:
            return text
        original = text
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        if "</think>" in cleaned:
            cleaned = cleaned.split("</think>", 1)[1]
        cleaned = cleaned.strip()
        return cleaned if cleaned else original.strip()

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