import json
import os
import urllib.request
import urllib.error
from walkoff_app_sdk.app_base import AppBase


class PlaybookRecommender(AppBase):
    """
    Shuffle SOAR App — AI Playbook Recommender

    Integrates the AI recommendation API directly into Shuffle workflows.
    Analysts can query for playbook recommendations mid-execution.
    """

    __version__ = "3.0.0"
    app_name = "ai_playbook_recommender"

    def __init__(self, redis, logger, console_logger=None):
        super().__init__(redis, logger, console_logger)
        self.api_url = os.environ.get("RECOMMENDER_API_URL", "http://playbook-api:8000")
        self.api_key = os.environ.get("RECOMMENDER_API_KEY", "")

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "X-API-Key": self.api_key}

    def _post(self, path: str, payload: dict, timeout: int = 30) -> dict:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.api_url}{path}",
            data=data,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    # ── Actions ───────────────────────────────────────────────────────────────

    async def recommend_playbook(
        self,
        query: str,
        session_id: str = "",
        use_refinement: bool = False,
        available_integrations: str = "",
        api_keys_configured: str = "",
        top_k: int = 3,
    ) -> dict:
        """
        Get AI playbook recommendations for a given security task.

        Args:
            query: Natural language description of the security task or incident
            session_id: Optional session ID for multi-turn conversations
            use_refinement: Enable semi-agentic verification (slower but more accurate)
            available_integrations: Comma-separated list of available integrations
            api_keys_configured: Comma-separated list of integrations with configured API keys
            top_k: Number of recommendations to return (1-10)
        """
        payload: dict = {
            "query": query,
            "top_k": int(top_k),
            "use_refinement": bool(use_refinement),
        }

        if session_id:
            payload["session_id"] = session_id

        if available_integrations or api_keys_configured:
            payload["analyst_context"] = {
                "available_integrations": [
                    i.strip() for i in available_integrations.split(",") if i.strip()
                ],
                "api_keys_configured": [
                    i.strip() for i in api_keys_configured.split(",") if i.strip()
                ],
            }

        try:
            result = self._post("/api/v1/recommend", payload, timeout=60)
            return {
                "success": True,
                "intent": result.get("intent"),
                "recommendations": result.get("recommended_playbooks", []),
                "fallback_message": result.get("fallback_message", ""),
                "used_refinement": result.get("used_refinement", False),
                "latency_ms": result.get("latency_ms", 0),
                "top_playbook": (
                    result["recommended_playbooks"][0] if result.get("recommended_playbooks") else None
                ),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "recommendations": []}

    async def search_playbooks(
        self, query: str, category: str = "", integrations: str = "", top_k: int = 10
    ) -> dict:
        """
        Fast keyword + semantic search without LLM generation.

        Args:
            query: Search query
            category: Optional category filter (e.g. Phishing, Malware)
            integrations: Comma-separated integration filter
            top_k: Max results
        """
        payload = {
            "query": query,
            "top_k": int(top_k),
        }
        if category:
            payload["category"] = category
        if integrations:
            payload["integrations"] = [i.strip() for i in integrations.split(",") if i.strip()]

        try:
            result = self._post("/api/v1/search", payload)
            return {"success": True, "results": result.get("results", []), "total": result.get("total", 0)}
        except Exception as e:
            return {"success": False, "error": str(e), "results": []}

    async def explain_playbook(self, playbook_id: str) -> dict:
        """
        Get a detailed explanation of a specific playbook.

        Args:
            playbook_id: UUID of the playbook to explain
        """
        req = urllib.request.Request(
            f"{self.api_url}/api/v1/playbooks/{playbook_id}",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"success": True, "playbook": json.loads(resp.read())}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def submit_feedback(
        self,
        query: str,
        playbook_id: str,
        accepted: bool,
        confidence_score: float = 0.0,
        session_id: str = "",
    ) -> dict:
        """
        Submit analyst feedback on a recommendation to improve future results.

        Args:
            query: Original query that produced the recommendation
            playbook_id: UUID of the recommended playbook
            accepted: Whether the analyst accepted / used the recommendation
            confidence_score: Original confidence score from the recommendation
            session_id: Optional session ID
        """
        try:
            result = self._post(
                "/api/v1/feedback",
                {
                    "query": query,
                    "recommended_playbook_id": playbook_id,
                    "accepted": bool(accepted),
                    "confidence_score": float(confidence_score),
                    "session_id": session_id or None,
                },
            )
            return {"success": True, "message": result.get("message", "Feedback recorded")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def health_check(self) -> dict:
        """Check if the recommendation API is running correctly."""
        req = urllib.request.Request(
            f"{self.api_url}/health",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return {"success": True, "status": data.get("status"), "services": data.get("services", [])}
        except Exception as e:
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    PlaybookRecommender.run()
