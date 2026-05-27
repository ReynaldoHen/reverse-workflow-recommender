"""
AI Recommender v1.1 - thin Shuffle app.

Adds two indexing actions for the knowledge base and incident history.
"""

import json
import requests
from walkoff_app_sdk.app_base import AppBase


class AIRecommender(AppBase):
    __version__ = "1.1.0"
    app_name = "ai_recommender"

    def __init__(self, redis, logger, console_logger=None):
        super().__init__(redis, logger, console_logger)

    def _split(self, csv):
        return [x.strip() for x in (csv or "").split(",") if x.strip()]

    def _post(self, service_url, path, payload, timeout=180):
        r = requests.post(f"{service_url.rstrip('/')}{path}",
                          json=payload, timeout=timeout)
        r.raise_for_status()
        return json.dumps(r.json())

    def recommend_playbook(self, service_url, alert_id, title,
                            description="", severity="",
                            mitre_technique="", iocs=""):
        return self._post(service_url, "/recommend", {
            "alert_id": alert_id, "title": title,
            "description": description, "severity": severity,
            "mitre_technique": mitre_technique,
            "iocs": self._split(iocs),
        })

    def index_playbook(self, service_url, workflow_id, name,
                       description="", trigger_type="",
                       mitre_tags="", apps_used="", alert_category=""):
        return self._post(service_url, "/index", {
            "workflow_id": workflow_id, "name": name,
            "description": description, "trigger_type": trigger_type,
            "mitre_tags": self._split(mitre_tags),
            "apps_used": self._split(apps_used),
            "alert_category": alert_category,
        }, timeout=60)

    def index_knowledge(self, service_url, doc_type, title, content,
                        source_uri="", chunk_index="0",
                        tags="", mitre_tags=""):
        """Index a runbook, SOP, policy, or other reference document."""
        return self._post(service_url, "/index_knowledge", {
            "doc_type": doc_type, "title": title, "content": content,
            "source_uri": source_uri,
            "chunk_index": int(chunk_index or 0),
            "tags": self._split(tags),
            "mitre_tags": self._split(mitre_tags),
        }, timeout=60)

    def index_incident(self, service_url, incident_id, title, outcome,
                       summary="", iocs="", mitre_tags="", workflow_used=""):
        """Index a closed incident for historical context on future alerts."""
        return self._post(service_url, "/index_incident", {
            "incident_id": incident_id, "title": title, "outcome": outcome,
            "summary": summary,
            "iocs": self._split(iocs),
            "mitre_tags": self._split(mitre_tags),
            "workflow_used": workflow_used,
        }, timeout=60)

    def submit_feedback(self, service_url, alert_id, workflow_id,
                        rank, decision):
        return self._post(service_url, "/feedback", {
            "alert_id": alert_id, "workflow_id": workflow_id,
            "rank": int(rank), "decision": decision,
        }, timeout=30)


if __name__ == "__main__":
    AIRecommender.run()
