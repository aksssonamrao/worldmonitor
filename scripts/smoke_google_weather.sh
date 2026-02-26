#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${1:-http://localhost:8090}"
RUN_ID="latest"

curl -sS -X POST "$BASE_URL/compound/hazards/generate" \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"'"$RUN_ID"'","bbox":[72.0,8.0,72.8,8.8],"timestep_hours":[0,6,12,24],"hazard_types":["WIND","RAIN","HEAT"]}' >/tmp/hazard-generate.json

FEATURES=$(curl -sS "$BASE_URL/compound/hazards?run_id=$RUN_ID&timestep=0" | python -c 'import json,sys;print(len(json.load(sys.stdin).get("features",[])))')
if [ "$FEATURES" -le 0 ]; then
  echo "No hazard features returned"
  exit 1
fi

echo "Smoke test passed. features=$FEATURES"
