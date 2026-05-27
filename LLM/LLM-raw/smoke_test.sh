#!/usr/bin/env bash
# v1.1 smoke test: health, index playbooks + KB + incident, recommend, feedback.
set -euo pipefail
SVC="${1:-http://localhost:8088}"
say() { printf "\n==> %s\n" "$*"; }

say "health"
curl -fsS "$SVC/health" | python3 -m json.tool

say "index playbook: phishing response"
curl -fsS -X POST "$SVC/index" -H 'Content-Type: application/json' -d '{
  "workflow_id": "wf-phish-001",
  "name": "Phishing response v2",
  "description": "Triage reported phishing, detonate URLs, block sender, notify user",
  "trigger_type": "email_alert",
  "mitre_tags": ["T1566"],
  "apps_used": ["email", "urlscan", "active_directory"],
  "alert_category": "phishing"
}' | python3 -m json.tool

say "index playbook: ransomware containment"
curl -fsS -X POST "$SVC/index" -H 'Content-Type: application/json' -d '{
  "workflow_id": "wf-ransom-001",
  "name": "Ransomware containment",
  "description": "Isolate host on EDR, disable user, snapshot for forensics, alert IR",
  "trigger_type": "edr_alert",
  "mitre_tags": ["T1486", "T1490"],
  "apps_used": ["crowdstrike", "active_directory", "slack"],
  "alert_category": "ransomware"
}' | python3 -m json.tool

say "index runbook: phishing triage SOP"
curl -fsS -X POST "$SVC/index_knowledge" -H 'Content-Type: application/json' -d '{
  "doc_type": "runbook",
  "title": "Phishing triage runbook",
  "content": "When a user reports a suspicious email, first detonate any URLs in a sandbox. If the URL is confirmed malicious, block the sender domain and notify the affected user. For executive-targeted attempts, escalate to IR before any automated response. T1566 phishing is the most common entry vector.",
  "tags": ["phishing", "triage"],
  "mitre_tags": ["T1566"]
}' | python3 -m json.tool

say "index policy: executive escalation"
curl -fsS -X POST "$SVC/index_knowledge" -H 'Content-Type: application/json' -d '{
  "doc_type": "policy",
  "title": "Executive asset policy",
  "content": "Alerts affecting executive laptops or finance team assets require human approval before any containment action. Auto-isolation is disabled for these assets.",
  "tags": ["policy", "executive"]
}' | python3 -m json.tool

say "index incident: prior false positive"
curl -fsS -X POST "$SVC/index_incident" -H 'Content-Type: application/json' -d '{
  "incident_id": "inc-2024-0042",
  "title": "Reported phishing - marketing newsletter",
  "summary": "User reported the company newsletter as phishing; not malicious",
  "outcome": "false_positive",
  "mitre_tags": ["T1566"],
  "workflow_used": "wf-phish-001"
}' | python3 -m json.tool

say "recommend for an inbound phishing alert"
curl -fsS -X POST "$SVC/recommend" -H 'Content-Type: application/json' -d '{
  "alert_id": "alert-9001",
  "title": "User reported suspicious email with link",
  "description": "Employee forwarded an email containing a credential-harvesting URL",
  "severity": "high",
  "mitre_technique": "T1566",
  "iocs": ["hxxp://evil.example/login"]
}' | python3 -m json.tool

say "smoke test complete"
