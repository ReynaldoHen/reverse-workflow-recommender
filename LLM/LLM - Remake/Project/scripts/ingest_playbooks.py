#!/usr/bin/env python3
"""
Ingest playbooks from a JSON file into the knowledge base.

Usage:
    python ingest_playbooks.py --file ../sample_data/sample_playbooks.json
    python ingest_playbooks.py --file my_playbooks.json --api-url http://localhost:8000 --api-key YOUR_KEY
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def ingest(file_path: str, api_url: str, api_key: str):
    with open(file_path) as f:
        playbooks = json.load(f)

    print(f"Ingesting {len(playbooks)} playbooks → {api_url}")
    success = failed = skipped = 0

    for pb in playbooks:
        payload = json.dumps({
            "name": pb.get("name", ""),
            "description": pb.get("description", ""),
            "use_cases": pb.get("use_cases", []),
            "integrations": pb.get("integrations", []),
            "triggers": pb.get("triggers", []),
            "tags": pb.get("tags", []),
            "category": pb.get("category", ""),
            "shuffle_workflow_id": pb.get("shuffle_workflow_id", ""),
            "shuffle_json": pb.get("shuffle_json", {}),
        }).encode()

        req = urllib.request.Request(
            f"{api_url}/api/v1/playbooks",
            data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                print(f"  ✓  {pb['name'][:60]}")
                success += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 409:
                print(f"  ⚠  {pb['name'][:60]} — already exists, skipping")
                skipped += 1
            else:
                print(f"  ✗  {pb['name'][:60]} — HTTP {e.code}: {body[:100]}")
                failed += 1
        except Exception as e:
            print(f"  ✗  {pb['name'][:60]} — {e}")
            failed += 1

        time.sleep(0.2)  # Brief pause to avoid overwhelming embedder

    print(f"\nDone: {success} ingested, {skipped} skipped, {failed} failed")
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Ingest playbooks into AI Playbook Recommender")
    parser.add_argument("--file", default="../sample_data/sample_playbooks.json")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    if not args.api_key:
        print("Note: No --api-key provided. Using empty key (will fail unless auth is disabled).")
        print("Get your API key from the startup logs or by POSTing to /api/v1/auth/login\n")

    ok = ingest(args.file, args.api_url.rstrip("/"), args.api_key)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
