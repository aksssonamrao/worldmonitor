#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-http://localhost:8090}"
RUN_ID="latest"

POST_STATUS=$(curl -sS -o /tmp/hazard-generate.json -w '%{http_code}' -X POST "$BASE_URL/compound/hazards/generate" \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"'"$RUN_ID"'","bbox":[72.0,8.0,72.8,8.8],"timestep_hours":[0,6,12,24],"hazard_types":["WIND","RAIN","HEAT"]}')
if [ "$POST_STATUS" -lt 200 ] || [ "$POST_STATUS" -ge 300 ]; then
  echo "Error: POST /compound/hazards/generate returned HTTP $POST_STATUS" >&2
  echo "Response body:" >&2
  cat /tmp/hazard-generate.json >&2 || true
  exit 1
fi

HAZARDS_TMP=$(mktemp)
GET_STATUS=$(curl -sS -o "$HAZARDS_TMP" -w '%{http_code}' "$BASE_URL/compound/hazards?run_id=$RUN_ID&timestep=0")
if [ "$GET_STATUS" -lt 200 ] || [ "$GET_STATUS" -ge 300 ]; then
  echo "Error: GET /compound/hazards returned HTTP $GET_STATUS" >&2
  echo "Response body:" >&2
  cat "$HAZARDS_TMP" >&2 || true
  exit 1
fi

FEATURES=$(python -c 'import json,sys;print(len(json.load(sys.stdin).get("features",[])))' < "$HAZARDS_TMP")
if [ "$FEATURES" -le 0 ]; then
  echo "No hazard features returned"
  exit 1
fi

echo "Smoke test passed. features=$FEATURES"
