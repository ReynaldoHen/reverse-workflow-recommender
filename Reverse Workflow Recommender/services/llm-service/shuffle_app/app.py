import requests

API = "http://playbook-api:8000/api/v1"


def recommend(token: str, query: str):
    r = requests.post(f"{API}/recommend",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"query": query})
    return r.json()


def generate(token: str, description: str, integrations: list):
    r = requests.post(f"{API}/generate/playbook",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"description": description, "target_integrations": integrations,
                            "dry_run": True})
    return r.json()
