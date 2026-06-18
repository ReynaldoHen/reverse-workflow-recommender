#!/usr/bin/env python3
"""Ingest a playbook dataset into the running API (auth via JWT or API key)."""
import argparse, json, sys, requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--api-url", default="http://localhost:8000")
    ap.add_argument("--api-key", help="JWT token or admin key")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="admin")
    args = ap.parse_args()

    token = args.api_key
    if not token:
        r = requests.post(f"{args.api_url}/api/v1/auth/login",
                          json={"username": args.username, "password": args.password})
        r.raise_for_status()
        token = r.json()["access_token"]

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    playbooks = json.load(open(args.file))
    ok = 0
    for pb in playbooks:
        resp = requests.post(f"{args.api_url}/api/v1/playbooks", headers=headers, json=pb)
        if resp.status_code < 300:
            ok += 1
            print(f"  + {pb['slug']}")
        else:
            print(f"  ! {pb['slug']}: {resp.status_code} {resp.text[:120]}", file=sys.stderr)
    print(f"Ingested {ok}/{len(playbooks)} playbooks.")


if __name__ == "__main__":
    main()
