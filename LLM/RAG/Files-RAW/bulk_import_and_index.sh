#!/usr/bin/env bash
# =============================================================================
# Bulk import playbooks into Shuffle AND index them into the AI recommender.
# Run this once after Shuffle is up and the recommender is healthy.
#
# Usage:
#   bash bulk_import_and_index.sh \
#     --shuffle-url http://localhost:3001 \
#     --shuffle-token YOUR_API_TOKEN \
#     --recommender-url http://localhost:8088
# =============================================================================
set -euo pipefail

# ---- argument parsing -------------------------------------------------------
SHUFFLE_URL="http://localhost:3001"
SHUFFLE_TOKEN=""
REC_URL="http://localhost:8088"

while [[ $# -gt 0 ]]; do
  case $1 in
    --shuffle-url)    SHUFFLE_URL="$2";  shift 2 ;;
    --shuffle-token)  SHUFFLE_TOKEN="$2"; shift 2 ;;
    --recommender-url) REC_URL="$2";     shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

WORKFLOWS_DIR="$(dirname "$0")/workflows"

# ---- helper -----------------------------------------------------------------
say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
ok()  { printf "  \033[0;32m✓\033[0m %s\n" "$*"; }
err() { printf "  \033[0;31m✗\033[0m %s\n" "$*"; }

# ---- recommender healthcheck ------------------------------------------------
say "Checking recommender health"
HEALTH=$(curl -fsS "$REC_URL/health" 2>/dev/null || echo '{"status":"unreachable"}')
STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','error'))" 2>/dev/null || echo "error")
if [[ "$STATUS" != "ok" ]]; then
  err "Recommender not healthy ($STATUS). Is docker compose up? Is Ollama running?"
  exit 1
fi
ok "Recommender is healthy"

# ---- metadata per workflow --------------------------------------------------
# These match the fields each workflow JSON was designed around.
declare -A WF_META
WF_META["phishing_response"]='{"trigger_type":"email_alert","mitre_tags":["T1566"],"apps_used":["urlscan","virustotal","exchange","thehive","slack"],"alert_category":"phishing"}'
WF_META["ransomware_containment"]='{"trigger_type":"edr_alert","mitre_tags":["T1486","T1490"],"apps_used":["crowdstrike","active_directory","palo_alto","pagerduty","thehive"],"alert_category":"ransomware"}'
WF_META["brute_force_response"]='{"trigger_type":"siem_alert","mitre_tags":["T1110","T1078"],"apps_used":["abuseipdb","active_directory","palo_alto","thehive","email"],"alert_category":"brute_force"}'
WF_META["malware_detection_response"]='{"trigger_type":"edr_alert","mitre_tags":["T1204","T1059","T1055"],"apps_used":["virustotal","malwarebazaar","crowdstrike","thehive"],"alert_category":"malware"}'
WF_META["data_exfiltration_response"]='{"trigger_type":"dlp_alert","mitre_tags":["T1048","T1567","T1530"],"apps_used":["virustotal","active_directory","palo_alto","azure_ad","thehive","email"],"alert_category":"data_exfiltration"}'
WF_META["insider_threat_response"]='{"trigger_type":"ueba_alert","mitre_tags":["T1078","T1098"],"apps_used":["splunk","active_directory","thehive","email"],"alert_category":"insider_threat"}'
WF_META["vulnerability_response"]='{"trigger_type":"scanner_alert","mitre_tags":["T1190","T1203"],"apps_used":["tenable","nvd","jira","email"],"alert_category":"vulnerability"}'
WF_META["c2_beacon_response"]='{"trigger_type":"ids_alert","mitre_tags":["T1071","T1095","T1571"],"apps_used":["virustotal","misp","crowdstrike","palo_alto","splunk","thehive"],"alert_category":"c2_beacon"}'
WF_META["account_takeover_response"]='{"trigger_type":"identity_alert","mitre_tags":["T1078","T1539"],"apps_used":["haveibeenpwned","abuseipdb","azure_ad","active_directory","twilio","thehive"],"alert_category":"account_takeover"}'

# ---- process each workflow --------------------------------------------------
IMPORTED=0
INDEXED=0
FAILED=0

for json_file in "$WORKFLOWS_DIR"/*.json; do
  base=$(basename "$json_file" .json)
  wf_id=$(python3 -c "import json; d=json.load(open('$json_file')); print(d['id'])")
  wf_name=$(python3 -c "import json; d=json.load(open('$json_file')); print(d['name'])")
  wf_desc=$(python3 -c "import json; d=json.load(open('$json_file')); print(d['description'])")

  say "Processing: $wf_name"

  # Step 1: Import into Shuffle (skip if no token provided)
  if [[ -n "$SHUFFLE_TOKEN" ]]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$SHUFFLE_URL/api/v1/workflows" \
      -H "Authorization: Bearer $SHUFFLE_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "@$json_file")
    if [[ "$HTTP_CODE" =~ ^2 ]]; then
      ok "Imported into Shuffle (HTTP $HTTP_CODE)"
      IMPORTED=$((IMPORTED+1))
    else
      err "Shuffle import failed (HTTP $HTTP_CODE) — check token and URL"
      FAILED=$((FAILED+1))
    fi
  else
    echo "  [skip] No --shuffle-token provided; skipping Shuffle import"
  fi

  # Step 2: Index into recommender
  meta="${WF_META[$base]:-{}}"
  trigger_type=$(echo "$meta" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('trigger_type',''))")
  mitre_tags=$(echo "$meta" | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(d.get('mitre_tags',[])))")
  apps_used=$(echo "$meta" | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(d.get('apps_used',[])))")
  alert_category=$(echo "$meta" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('alert_category',''))")

  INDEX_PAYLOAD=$(python3 -c "
import json, sys
print(json.dumps({
  'workflow_id': '$wf_id',
  'name': '''$wf_name''',
  'description': '''$wf_desc''',
  'trigger_type': '$trigger_type',
  'mitre_tags': '$mitre_tags'.split(',') if '$mitre_tags' else [],
  'apps_used': '$apps_used'.split(',') if '$apps_used' else [],
  'alert_category': '$alert_category'
}))
")
  INDEX_RESP=$(curl -fsS -X POST "$REC_URL/index" \
    -H 'Content-Type: application/json' \
    -d "$INDEX_PAYLOAD" 2>/dev/null || echo '{"error":"request failed"}')

  INDEXED_ID=$(echo "$INDEX_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('indexed',''))" 2>/dev/null || echo "")
  if [[ -n "$INDEXED_ID" ]]; then
    ok "Indexed into recommender (id: $INDEXED_ID)"
    INDEXED=$((INDEXED+1))
  else
    err "Recommender index failed: $INDEX_RESP"
    FAILED=$((FAILED+1))
  fi
done

# ---- summary ----------------------------------------------------------------
say "Done"
echo "  Imported into Shuffle : $IMPORTED"
echo "  Indexed into recommender: $INDEXED"
echo "  Failures              : $FAILED"

if [[ $INDEXED -gt 0 ]]; then
  echo ""
  echo "Test a recommendation:"
  echo "  curl -X POST $REC_URL/recommend -H 'Content-Type: application/json' \\"
  echo "    -d '{\"alert_id\":\"test-1\",\"title\":\"User reported suspicious phishing email\",\"mitre_technique\":\"T1566\"}'"
fi
