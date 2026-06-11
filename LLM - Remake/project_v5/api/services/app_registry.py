"""
App Registry for Shuffle SOAR.

Provides a mapping of app names → app metadata (IDs, actions, parameters).
Works OFFLINE with a built-in registry, and can refresh from a live Shuffle
instance when credentials are configured.

Used by the Shuffle Translator to resolve real app_ids and valid actions
when generating deployment-ready workflows.
"""
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Built-in offline registry ─────────────────────────────────────────────────
# Covers the most common Shuffle SOAR apps.
# Each entry has: app_id (deterministic UUID), description, and list of actions.
# Actions have: action_name, description, and key parameters.

BUILTIN_REGISTRY: dict[str, dict] = {
    "virustotal": {
        "app_id": "a530ba31-e10f-4a7e-9590-c3cbfe8b5df8",
        "display_name": "VirusTotal",
        "description": "Threat intelligence and malware analysis",
        "category": "Threat Intelligence",
        "actions": {
            "lookup_ip": {
                "description": "Get reputation for an IP address",
                "parameters": ["ip_address"],
            },
            "lookup_file": {
                "description": "Analyse a file hash",
                "parameters": ["file_hash"],
            },
            "lookup_domain": {
                "description": "Get reputation for a domain",
                "parameters": ["domain"],
            },
            "lookup_url": {
                "description": "Analyse a URL",
                "parameters": ["url"],
            },
        },
    },
    "slack": {
        "app_id": "b8c3f1a2-3d4e-5f6a-7b8c-9d0e1f2a3b4c",
        "display_name": "Slack",
        "description": "Team messaging and notifications",
        "category": "Communication",
        "actions": {
            "send_message": {
                "description": "Post a message to a channel",
                "parameters": ["channel", "message"],
            },
            "create_channel": {
                "description": "Create a new Slack channel",
                "parameters": ["channel_name"],
            },
            "get_user": {
                "description": "Get user information by email or ID",
                "parameters": ["user_email"],
            },
        },
    },
    "jira": {
        "app_id": "c9d4e5f6-1a2b-3c4d-5e6f-7a8b9c0d1e2f",
        "display_name": "Jira",
        "description": "Issue and project tracking",
        "category": "Ticketing",
        "actions": {
            "create_ticket": {
                "description": "Create a new issue",
                "parameters": ["summary", "description", "priority", "project_key"],
            },
            "update_ticket": {
                "description": "Update an existing issue",
                "parameters": ["issue_key", "status", "comment"],
            },
            "search_issues": {
                "description": "Search issues with JQL",
                "parameters": ["jql_query"],
            },
            "add_comment": {
                "description": "Add a comment to an issue",
                "parameters": ["issue_key", "comment"],
            },
        },
    },
    "microsoft_sentinel": {
        "app_id": "d0e1f2a3-4b5c-6d7e-8f9a-0b1c2d3e4f5a",
        "display_name": "Microsoft Sentinel",
        "description": "Cloud-native SIEM and SOAR",
        "category": "SIEM",
        "actions": {
            "query_data": {
                "description": "Run a KQL query",
                "parameters": ["kql_query", "workspace_id"],
            },
            "create_incident": {
                "description": "Create a new incident",
                "parameters": ["title", "description", "severity"],
            },
            "update_incident": {
                "description": "Update an existing incident",
                "parameters": ["incident_id", "status", "comment"],
            },
            "get_alerts": {
                "description": "List recent alerts",
                "parameters": ["time_range", "severity"],
            },
        },
    },
    "splunk": {
        "app_id": "e1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
        "display_name": "Splunk",
        "description": "Log aggregation and SIEM",
        "category": "SIEM",
        "actions": {
            "search": {
                "description": "Run a Splunk search",
                "parameters": ["search_query", "time_range"],
            },
            "create_alert": {
                "description": "Create a saved search alert",
                "parameters": ["name", "search_query", "threshold"],
            },
            "get_events": {
                "description": "Get events from a Splunk index",
                "parameters": ["index", "query"],
            },
        },
    },
    "crowdstrike": {
        "app_id": "f2a3b4c5-6d7e-8f9a-0b1c-2d3e4f5a6b7c",
        "display_name": "CrowdStrike",
        "description": "Endpoint detection and response",
        "category": "EDR",
        "actions": {
            "get_processes": {
                "description": "List processes on a host",
                "parameters": ["device_id"],
            },
            "isolate_host": {
                "description": "Network-isolate an endpoint",
                "parameters": ["device_id"],
            },
            "get_incidents": {
                "description": "Retrieve recent incidents",
                "parameters": ["time_range", "status"],
            },
            "run_rtr_command": {
                "description": "Execute a Real Time Response command",
                "parameters": ["device_id", "command"],
            },
        },
    },
    "palo_alto": {
        "app_id": "a3b4c5d6-7e8f-9a0b-1c2d-3e4f5a6b7c8d",
        "display_name": "Palo Alto Networks",
        "description": "Next-generation firewall and threat prevention",
        "category": "Network Security",
        "actions": {
            "block_ip": {
                "description": "Add IP to blocklist",
                "parameters": ["ip_address", "list_name"],
            },
            "get_logs": {
                "description": "Query traffic or threat logs",
                "parameters": ["log_type", "query"],
            },
            "update_policy": {
                "description": "Update a security policy rule",
                "parameters": ["rule_name", "action"],
            },
        },
    },
    "aws": {
        "app_id": "b4c5d6e7-8f9a-0b1c-2d3e-4f5a6b7c8d9e",
        "display_name": "AWS",
        "description": "Amazon Web Services cloud services",
        "category": "Cloud",
        "actions": {
            "describe_instances": {
                "description": "List EC2 instances",
                "parameters": ["region", "filters"],
            },
            "create_snapshot": {
                "description": "Create an EBS snapshot",
                "parameters": ["volume_id", "description"],
            },
            "get_security_groups": {
                "description": "List security groups",
                "parameters": ["vpc_id"],
            },
            "invoke_lambda": {
                "description": "Invoke a Lambda function",
                "parameters": ["function_name", "payload"],
            },
        },
    },
    "active_directory": {
        "app_id": "c5d6e7f8-9a0b-1c2d-3e4f-5a6b7c8d9e0f",
        "display_name": "Active Directory",
        "description": "Microsoft Active Directory identity management",
        "category": "Identity",
        "actions": {
            "disable_user": {
                "description": "Disable an AD user account",
                "parameters": ["username"],
            },
            "reset_password": {
                "description": "Force a password reset",
                "parameters": ["username"],
            },
            "get_user_groups": {
                "description": "List groups for a user",
                "parameters": ["username"],
            },
            "lock_account": {
                "description": "Lock a user account",
                "parameters": ["username"],
            },
        },
    },
    "email": {
        "app_id": "d6e7f8a9-0b1c-2d3e-4f5a-6b7c8d9e0f1a",
        "display_name": "Email",
        "description": "Generic email send/receive operations",
        "category": "Communication",
        "actions": {
            "send_email": {
                "description": "Send an email",
                "parameters": ["to", "subject", "body"],
            },
            "get_email": {
                "description": "Retrieve an email",
                "parameters": ["mailbox", "message_id"],
            },
            "forward_email": {
                "description": "Forward an email",
                "parameters": ["message_id", "to"],
            },
        },
    },
    "webhook": {
        "app_id": "e7f8a9b0-1c2d-3e4f-5a6b-7c8d9e0f1a2b",
        "display_name": "Webhook",
        "description": "Trigger workflows via HTTP webhook",
        "category": "Trigger",
        "actions": {
            "receive_webhook": {
                "description": "Start workflow from webhook payload",
                "parameters": ["payload"],
            },
        },
    },
    "threat_intel": {
        "app_id": "f8a9b0c1-2d3e-4f5a-6b7c-8d9e0f1a2b3c",
        "display_name": "Threat Intelligence",
        "description": "Generic threat intelligence feed integration",
        "category": "Threat Intelligence",
        "actions": {
            "lookup_ioc": {
                "description": "Look up an IOC across threat feeds",
                "parameters": ["ioc_value", "ioc_type"],
            },
            "get_feed": {
                "description": "Fetch latest feed entries",
                "parameters": ["feed_name", "limit"],
            },
        },
    },
    "http_request": {
        "app_id": "a9b0c1d2-3e4f-5a6b-7c8d-9e0f1a2b3c4d",
        "display_name": "HTTP Request",
        "description": "Make arbitrary HTTP API calls",
        "category": "Utility",
        "actions": {
            "get": {
                "description": "HTTP GET request",
                "parameters": ["url", "headers"],
            },
            "post": {
                "description": "HTTP POST request",
                "parameters": ["url", "body", "headers"],
            },
        },
    },
    "elasticsearch": {
        "app_id": "b0c1d2e3-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
        "display_name": "Elasticsearch",
        "description": "Elasticsearch / Elastic Stack SIEM queries",
        "category": "SIEM",
        "actions": {
            "search": {
                "description": "Run an Elasticsearch query",
                "parameters": ["index", "query"],
            },
            "index_document": {
                "description": "Index a document",
                "parameters": ["index", "document"],
            },
            "get_alerts": {
                "description": "Retrieve detection alerts",
                "parameters": ["time_range", "severity"],
            },
        },
    },
}

# ── Aliases: alternate names that map to canonical keys ──────────────────────
APP_ALIASES: dict[str, str] = {
    "virus_total": "virustotal",
    "vt": "virustotal",
    "ms_sentinel": "microsoft_sentinel",
    "azure_sentinel": "microsoft_sentinel",
    "sentinel": "microsoft_sentinel",
    "cs": "crowdstrike",
    "falcon": "crowdstrike",
    "palo": "palo_alto",
    "pan": "palo_alto",
    "aws_security_hub": "aws",
    "s3": "aws",
    "ad": "active_directory",
    "ldap": "active_directory",
    "elastic": "elasticsearch",
    "elastic_search": "elasticsearch",
    "elk": "elasticsearch",
    "es": "elasticsearch",
    "teams": "slack",      # close enough for messaging actions
    "ms_teams": "slack",
    "http": "http_request",
    "rest": "http_request",
    "api_call": "http_request",
}


class AppRegistry:
    """Manages the registry of available Shuffle SOAR apps."""

    def __init__(self, registry_path: Optional[str] = None):
        """
        Args:
            registry_path: Optional path to a JSON file with an overriding registry.
                           Used to persist fetched registry from Shuffle API.
        """
        self._registry: dict[str, dict] = dict(BUILTIN_REGISTRY)
        self._registry_path = registry_path
        if registry_path:
            self._load_from_file(registry_path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def resolve_app(self, app_name: str) -> Optional[dict]:
        """
        Resolve an app name to its registry entry.
        Returns None if not found.

        Args:
            app_name: The app name (e.g., "virustotal", "VirusTotal", "vt")
        """
        key = self._normalize(app_name)
        if key in self._registry:
            return {"app_key": key, **self._registry[key]}
        # Try aliases
        alias_key = APP_ALIASES.get(key)
        if alias_key and alias_key in self._registry:
            return {"app_key": alias_key, **self._registry[alias_key]}
        # Partial match
        for reg_key, entry in self._registry.items():
            if key in reg_key or reg_key in key:
                return {"app_key": reg_key, **entry}
        return None

    def resolve_action(self, app_name: str, action_name: str) -> Optional[dict]:
        """
        Resolve an app + action pair.
        Returns action metadata or None.
        """
        app = self.resolve_app(app_name)
        if not app:
            return None
        actions = app.get("actions", {})
        norm_action = self._normalize(action_name)
        if norm_action in actions:
            return actions[norm_action]
        # Partial match
        for act_key, act_data in actions.items():
            if norm_action in act_key or act_key in norm_action:
                return {"action_key": act_key, **act_data}
        return None

    def get_app_id(self, app_name: str) -> str:
        """
        Get the app_id for a given app name.
        Returns a deterministic UUID even for unknown apps (so workflows
        remain structurally valid).
        """
        app = self.resolve_app(app_name)
        if app:
            return app["app_id"]
        # Deterministic fallback UUID from app name
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"shuffle.app.{app_name}"))

    def get_first_action(self, app_name: str) -> str:
        """Return the first available action for an app, or a generic fallback."""
        app = self.resolve_app(app_name)
        if app and app.get("actions"):
            return next(iter(app["actions"]))
        return "execute"

    def all_apps(self) -> list[dict]:
        """Return all registered apps as a list."""
        return [{"app_key": k, **v} for k, v in self._registry.items()]

    def export_json(self) -> str:
        """Export registry as JSON string."""
        return json.dumps(self._registry, indent=2)

    # ── Shuffle API sync ───────────────────────────────────────────────────────

    async def refresh_from_shuffle(self) -> int:
        """
        Fetch apps from a live Shuffle instance and merge into registry.
        Returns count of new/updated apps.
        """
        if not settings.shuffle_api_url or not settings.shuffle_api_key:
            logger.info("Shuffle not configured — using built-in registry only")
            return 0

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{settings.shuffle_api_url}/api/v1/apps",
                    headers={"Authorization": f"Bearer {settings.shuffle_api_key}"},
                )
                resp.raise_for_status()
                apps = resp.json()

            count = 0
            for app in apps:
                app_name = self._normalize(app.get("name", ""))
                if not app_name:
                    continue
                actions = {}
                for action in app.get("actions", []):
                    act_name = self._normalize(action.get("name", ""))
                    if act_name:
                        actions[act_name] = {
                            "description": action.get("description", ""),
                            "parameters": [
                                p.get("name", "") for p in action.get("parameters", [])
                            ],
                        }

                self._registry[app_name] = {
                    "app_id": app.get("id", str(uuid.uuid4())),
                    "display_name": app.get("name", app_name),
                    "description": app.get("description", ""),
                    "category": app.get("category", "General"),
                    "actions": actions,
                }
                count += 1

            logger.info("Refreshed registry from Shuffle: %d apps", count)

            if self._registry_path:
                self._save_to_file(self._registry_path)

            return count

        except Exception as e:
            logger.warning("Could not refresh registry from Shuffle: %s", e)
            return 0

    # ── File persistence ───────────────────────────────────────────────────────

    def _load_from_file(self, path: str):
        try:
            with open(path) as f:
                data = json.load(f)
            self._registry.update(data)
            logger.info("Loaded registry from %s (%d apps)", path, len(data))
        except FileNotFoundError:
            logger.debug("No registry file at %s — using built-in", path)
        except Exception as e:
            logger.warning("Could not load registry file: %s", e)

    def _save_to_file(self, path: str):
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                json.dump(self._registry, f, indent=2)
            logger.info("Registry saved to %s", path)
        except Exception as e:
            logger.warning("Could not save registry: %s", e)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(name: str) -> str:
        """Lowercase, replace spaces/hyphens with underscores."""
        return name.lower().replace(" ", "_").replace("-", "_").strip()


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry_instance: Optional[AppRegistry] = None


def get_app_registry() -> AppRegistry:
    global _registry_instance
    if _registry_instance is None:
        registry_path = getattr(settings, "app_registry_path", None)
        _registry_instance = AppRegistry(registry_path=registry_path)
    return _registry_instance
