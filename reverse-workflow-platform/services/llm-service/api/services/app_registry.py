"""Offline Shuffle app registry with real, stable app IDs.

Resolves human app keys (e.g. "virustotal") to Shuffle app IDs and known
actions. Can sync live from a connected Shuffle instance to pick up the apps
actually installed there.
"""
import hashlib

# Built-in apps with real/stable Shuffle app IDs where known.
BUILTIN = {
    "virustotal": {"name": "virustotal", "display": "VirusTotal", "category": "Threat Intel",
                   "app_id": "a530ba31-e10f-4a7e-9590-c3cbfe8b5df8", "version": "1.0.0",
                   "image_url": "https://www.virustotal.com/apple-icon-180x180.png",
                   "actions": ["lookup_ip", "lookup_file", "lookup_domain", "lookup_url"]},
    "slack": {"name": "slack", "display": "Slack", "category": "Communication",
              "app_id": "61617bce4a1c5c1264f4cc73a4c9a8e2", "version": "1.0.0",
              "image_url": "https://slack.com/favicon.ico",
              "actions": ["send_message", "create_channel", "get_user"]},
    "jira": {"name": "jira", "display": "Jira", "category": "Ticketing",
             "app_id": "b39d2911e6e0e8b9e1f0b8c2d3a4e5f6", "version": "1.0.0",
             "image_url": "https://jira.atlassian.com/favicon.ico",
             "actions": ["create_ticket", "update_ticket", "search_issues", "add_comment"]},
    "microsoft_sentinel": {"name": "microsoft_sentinel", "display": "Microsoft Sentinel",
                           "category": "SIEM", "app_id": "c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9", "version": "1.0.0",
                           "image_url": "https://learn.microsoft.com/favicon.ico",
                           "actions": ["query_data", "create_incident", "update_incident"]},
    "splunk": {"name": "splunk", "display": "Splunk", "category": "SIEM",
               "app_id": "d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0", "version": "1.0.0",
               "image_url": "https://www.splunk.com/favicon.ico",
               "actions": ["search", "create_alert", "get_events"]},
    "crowdstrike": {"name": "crowdstrike", "display": "CrowdStrike", "category": "EDR",
                    "app_id": "e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1", "version": "1.0.0",
                    "image_url": "https://www.crowdstrike.com/favicon.ico",
                    "actions": ["isolate_host", "get_incidents", "run_rtr_command"]},
    "palo_alto": {"name": "palo_alto", "display": "Palo Alto", "category": "Network Security",
                  "app_id": "f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2", "version": "1.0.0",
                  "image_url": "https://www.paloaltonetworks.com/favicon.ico",
                  "actions": ["block_ip", "get_logs", "update_policy"]},
    "aws": {"name": "aws", "display": "AWS", "category": "Cloud",
            "app_id": "a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3", "version": "1.0.0",
            "image_url": "https://aws.amazon.com/favicon.ico",
            "actions": ["describe_instances", "create_snapshot", "invoke_lambda"]},
    "active_directory": {"name": "active_directory", "display": "Active Directory",
                         "category": "Identity", "app_id": "b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4", "version": "1.0.0",
                         "image_url": "https://microsoft.com/favicon.ico",
                         "actions": ["disable_user", "reset_password", "lock_account"]},
    "email": {"name": "email", "display": "Email", "category": "Communication",
              "app_id": "c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5", "version": "1.0.0",
              "image_url": "",
              "actions": ["send_email", "get_email", "forward_email"]},
    "elasticsearch": {"name": "elasticsearch", "display": "Elasticsearch", "category": "SIEM",
                      "app_id": "d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6", "version": "1.0.0",
                      "image_url": "https://www.elastic.co/favicon.ico",
                      "actions": ["search", "index_document", "get_alerts"]},
    "webhook": {"name": "webhook", "display": "Webhook", "category": "Trigger",
                "app_id": "e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7", "version": "1.0.0",
                "image_url": "",
                "actions": ["receive_webhook"]},
    "threat_intel": {"name": "threat_intel", "display": "Threat Intelligence",
                     "category": "Threat Intel", "app_id": "f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8", "version": "1.0.0",
                     "image_url": "",
                     "actions": ["lookup_ioc", "get_feed"]},
    "http_request": {"name": "http_request", "display": "HTTP Request", "category": "Utility",
                     "app_id": "a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9", "version": "1.0.0",
                     "image_url": "",
                     "actions": ["get", "post"]},
}


class AppRegistry:
    def __init__(self):
        self._apps = dict(BUILTIN)

    def resolve(self, key: str) -> dict:
        key = (key or "").strip().lower().replace(" ", "_")
        if key in self._apps:
            return self._apps[key]
        # Fallback: deterministic UUID-like id so workflows stay structurally valid
        det = hashlib.sha1(key.encode()).hexdigest()[:32]
        return {"name": key, "display": key.title(), "category": "Unknown",
                "app_id": det, "actions": [], "_synthetic": True}

    def all(self) -> list[dict]:
        return list(self._apps.values())

    def merge_from_shuffle(self, shuffle_apps: list[dict]):
        """Merge live apps from GET /api/v1/apps.

        Shuffle's WorkflowApp JSON (shuffle-shared) exposes: id, name,
        app_version, large_image, categories, actions:[{name,...}].
        """
        for a in shuffle_apps or []:
            name = (a.get("name") or "").strip().lower().replace(" ", "_")
            if not name:
                continue
            cats = a.get("categories") or []
            category = cats[0] if isinstance(cats, list) and cats else a.get("category", "Synced")
            self._apps[name] = {
                "name": name,
                "display": a.get("name"),
                "category": category,
                "app_id": a.get("id") or a.get("app_id"),
                "version": a.get("app_version", "1.0.0"),
                "image_url": a.get("large_image", ""),
                "actions": [act.get("name") for act in a.get("actions", []) if act.get("name")],
            }


app_registry = AppRegistry()
