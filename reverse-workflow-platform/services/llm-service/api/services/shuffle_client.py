"""First-class Shuffle SOAR API client.

The whole system flow connects to Shuffle through this client. When no live
instance is configured (SHUFFLE_API_URL / SHUFFLE_API_KEY empty) it runs in
OFFLINE/MOCK mode so the thesis demo still works end to end.
"""
import uuid
import httpx
from ..config import get_settings

settings = get_settings()


class ShuffleClient:
    def __init__(self):
        self.base = settings.shuffle_api_url.rstrip("/")
        self.key = settings.shuffle_api_key
        self.connected = settings.shuffle_connected

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    async def health(self) -> dict:
        if not self.connected:
            return {"connected": False, "mode": "offline", "detail": "No Shuffle credentials set."}
        try:
            async with httpx.AsyncClient(verify=settings.shuffle_verify_ssl, timeout=15) as c:
                r = await c.get(f"{self.base}/api/v1/health", headers=self._headers)
                return {"connected": r.status_code == 200, "mode": "live", "status": r.status_code}
        except Exception as exc:
            return {"connected": False, "mode": "error", "detail": str(exc)}

    async def list_apps(self) -> list[dict]:
        if not self.connected:
            return []
        async with httpx.AsyncClient(verify=settings.shuffle_verify_ssl, timeout=30) as c:
            r = await c.get(f"{self.base}/api/v1/apps", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def list_workflows(self) -> list[dict]:
        if not self.connected:
            return []
        async with httpx.AsyncClient(verify=settings.shuffle_verify_ssl, timeout=30) as c:
            r = await c.get(f"{self.base}/api/v1/workflows", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def deploy_workflow(self, workflow: dict) -> dict:
        """Create a workflow in Shuffle (POST /api/v1/workflows -> SetNewWorkflow).

        Offline mode returns a mock deployment id. Note Shuffle assigns its own
        workflow id on creation, so we return whatever id it gives back.
        """
        if not self.connected:
            return {"deployed": False, "mode": "offline",
                    "deployment_id": f"mock-{uuid.uuid4()}",
                    "detail": "Offline mode: workflow validated but not sent to Shuffle."}
        async with httpx.AsyncClient(verify=settings.shuffle_verify_ssl, timeout=60) as c:
            r = await c.post(f"{self.base}/api/v1/workflows", headers=self._headers, json=workflow)
            r.raise_for_status()
            body = r.json()
            return {"deployed": True, "mode": "live",
                    "deployment_id": body.get("id") or workflow.get("id"), "raw": body}

    async def execute_workflow(self, workflow_id: str, execution_argument: str = "") -> dict:
        """Run a deployed workflow (POST /api/v1/workflows/{id}/execute)."""
        if not self.connected:
            return {"executed": False, "mode": "offline",
                    "execution_id": f"mock-exec-{uuid.uuid4()}",
                    "detail": "Offline mode: execution simulated, not sent to Shuffle."}
        payload = {"execution_argument": execution_argument} if execution_argument else {}
        async with httpx.AsyncClient(verify=settings.shuffle_verify_ssl, timeout=60) as c:
            r = await c.post(f"{self.base}/api/v1/workflows/{workflow_id}/execute",
                             headers=self._headers, json=payload)
            r.raise_for_status()
            body = r.json()
            return {"executed": True, "mode": "live",
                    "execution_id": body.get("execution_id"), "raw": body}


shuffle_client = ShuffleClient()
