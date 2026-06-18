from typing import List, Dict, Any
from neo4j import AsyncGraphDatabase
from ..config import get_settings


settings = get_settings()


def infer_role(name: str) -> str:
    name = (name or "").lower()

    if "alert" in name or "trigger" in name:
        return "TRIGGER"
    if "block" in name or "quarantine" in name:
        return "RESPONSE"
    if "scan" in name or "check" in name or "lookup" in name:
        return "ANALYSIS"
    return "ENRICHMENT"


class GraphRetrieval:
    def __init__(self):
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=settings.neo4j_auth
        )

    async def get_action_context(self, workflow_id: str) -> List[Dict[str, Any]]:
        """
        Mengambil contextual graph view:
        - ACTION
        - role inference
        - next actions
        - APP relationship
        """

        query = """
        MATCH (a:ACTION {workflow_id: $workflow_id})
        OPTIONAL MATCH (a)-[r:NEXT]->(b:ACTION)
        OPTIONAL MATCH (a)-[:USES_APP]->(app:APP)
        RETURN
            a.action_id AS id,
            a.label AS name,
            a.app_id AS app_id,
            app.app_name AS app_name,
            collect({
                target_id: b.action_id,
                target_name: b.label,
                condition: r.condition
            }) AS next_actions
        """

        async with self.driver.session() as session:
            result = await session.run(query, workflow_id=workflow_id)
            records = [r.data() async for r in result]

        context = []

        for r in records:
            context.append({
                "id": r["id"],
                "label": r["name"],
                "app": r["app_name"],
                "role": infer_role(r["name"]),
                "next_actions": [
                    n for n in r["next_actions"]
                    if n.get("target_id") is not None
                ]
            })

        return context

    async def close(self):
        await self.driver.close()


graph_retrieval = GraphRetrieval()