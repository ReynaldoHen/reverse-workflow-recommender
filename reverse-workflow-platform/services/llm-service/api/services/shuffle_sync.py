import asyncio
import json
from ..config import get_settings
from ..database import SessionLocal, Playbook
from .shuffle_client import shuffle_client
from .app_registry import app_registry

settings = get_settings()


class ShuffleSyncService:
    async def sync_once(self) -> dict:
        if not settings.shuffle_connected:
            return {"synced": False, "reason": "offline"}
        apps = await shuffle_client.list_apps()
        app_registry.merge_from_shuffle(apps)
        workflows = await shuffle_client.list_workflows()
        stored = 0
        db = SessionLocal()
        try:
            for wf in workflows:
                slug = f"shuffle-{wf.get('id')}"
                existing = db.query(Playbook).filter_by(slug=slug).first()
                payload = json.loads(json.dumps(wf))
                if existing:
                    existing.shuffle_json = payload
                else:
                    db.add(Playbook(slug=slug, name=wf.get("name", slug),
                                    category="Synced", description=wf.get("description", ""),
                                    steps=[], apps=[], shuffle_json=payload))
                    stored += 1
            db.commit()
        finally:
            db.close()
        return {"synced": True, "apps": len(apps), "new_workflows": stored}


shuffle_sync_service = ShuffleSyncService()


async def run_sync_loop():
    interval = settings.shuffle_sync_interval_minutes * 60
    while True:
        try:
            if settings.shuffle_connected:
                await shuffle_sync_service.sync_once()
        except Exception:
            pass
        await asyncio.sleep(interval)
