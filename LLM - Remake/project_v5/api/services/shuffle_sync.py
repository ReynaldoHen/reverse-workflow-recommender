import json
"""Periodic sync job: pulls workflows from Shuffle API → indexes into KB."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services.retrieval import RetrievalService

logger = logging.getLogger(__name__)
settings = get_settings()


class ShuffleSyncService:
    """Fetches Shuffle workflows and upserts them into the KB."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.retrieval = RetrievalService(db)

    async def sync_all(self) -> dict:
        """Full sync from Shuffle. Returns stats dict."""
        if not settings.shuffle_api_url or not settings.shuffle_api_key:
            logger.warning("Shuffle API not configured — skipping sync")
            return {"synced": 0, "skipped": 0, "errors": 0}

        workflows = await self._fetch_workflows()
        stats = {"synced": 0, "skipped": 0, "errors": 0}

        for wf in workflows:
            try:
                await self._upsert_workflow(wf)
                stats["synced"] += 1
            except Exception as e:
                logger.error("Failed to sync workflow %s: %s", wf.get("id"), e)
                stats["errors"] += 1

        logger.info("Shuffle sync complete: %s", stats)
        return stats

    async def _fetch_workflows(self) -> list[dict]:
        headers = {"Authorization": f"Bearer {settings.shuffle_api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.shuffle_api_url}/api/v1/workflows",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _upsert_workflow(self, wf: dict):
        playbook_id = wf.get("id", str(uuid.uuid4()))
        name = wf.get("name", "Unnamed Workflow")
        description = wf.get("description", "")
        tags = wf.get("tags", [])

        # Extract integrations from actions
        integrations = list({
            action.get("app_name", "")
            for action in wf.get("actions", [])
            if action.get("app_name")
        })

        # Derive category from tags or name
        category = _infer_category(name, tags)

        # Upsert into PostgreSQL
        await self.db.execute(
            text("""
                INSERT INTO playbooks (
                    id, name, description, integrations, tags, category,
                    shuffle_workflow_id, shuffle_json, last_synced_from_shuffle, is_active
                )
                VALUES (
                    :id, :name, :desc, :integrations, :tags, :category,
                    :wf_id, :json::jsonb, NOW(), true
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    integrations = EXCLUDED.integrations,
                    tags = EXCLUDED.tags,
                    category = EXCLUDED.category,
                    shuffle_json = EXCLUDED.shuffle_json,
                    last_synced_from_shuffle = NOW(),
                    updated_at = NOW()
            """),
            {
                "id": playbook_id,
                "name": name,
                "desc": description,
                "integrations": integrations,
                "tags": tags,
                "category": category,
                "wf_id": wf.get("id"),
                "json": json.dumps(wf),
            },
        )

        # Index into Qdrant
        await self.retrieval.index_playbook(
            playbook_id=playbook_id,
            name=name,
            description=description,
            category=category,
            integrations=integrations,
            use_cases=tags,
            tags=tags,
        )

    async def start_background_sync(self, db_factory):
        """Run periodic sync on a background asyncio task."""
        while True:
            try:
                async with db_factory() as db:
                    svc = ShuffleSyncService(db)
                    await svc.sync_all()
            except Exception as e:
                logger.error("Background sync error: %s", e)
            await asyncio.sleep(settings.shuffle_sync_interval_minutes * 60)


def _infer_category(name: str, tags: list[str]) -> str:
    combined = (name + " " + " ".join(tags)).lower()
    mapping = {
        "phishing": "Phishing",
        "ransomware": "Ransomware",
        "malware": "Malware",
        "cloud": "Cloud Security",
        "siem": "SIEM Automation",
        "ioc": "IOC Enrichment",
        "enrich": "IOC Enrichment",
        "triage": "Alert Triage",
        "endpoint": "Endpoint Response",
        "threat": "Threat Intel",
    }
    for key, val in mapping.items():
        if key in combined:
            return val
    return "General"
