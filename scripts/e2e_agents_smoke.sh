#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
AGENT_TEMPERATURE="${AGENT_TEMPERATURE:-0.2}"
AGENT_MAX_TOKENS="${AGENT_MAX_TOKENS:-1200}"
AGENT_TIMEOUT_SECONDS="${AGENT_TIMEOUT_SECONDS:-45}"
AGENT_MAX_TOOL_CALLS="${AGENT_MAX_TOOL_CALLS:-6}"
AGENT_MAX_EVIDENCE_PER_ROUTE="${AGENT_MAX_EVIDENCE_PER_ROUTE:-30}"

export AGENT_TEMPERATURE AGENT_MAX_TOKENS AGENT_TIMEOUT_SECONDS AGENT_MAX_TOOL_CALLS AGENT_MAX_EVIDENCE_PER_ROUTE

echo "[1/5] Starting services..."
docker compose up -d --build

echo "[2/5] Waiting for health..."
for i in {1..60}; do
  if curl -fsS "$BASE_URL/health" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "$BASE_URL/health" >/dev/null

echo "[3/5] Calling route endpoints..."
curl -fsS -X POST "$BASE_URL/api/routes/options" -H 'content-type: application/json' -d '{"origin":{"lat":37.74,"lon":-122.58},"destination":{"lat":37.78,"lon":-122.53},"depart_time":"2026-01-01T10:00:00Z","arrive_by":"2026-01-01T20:00:00Z","risk_appetite":0.5}' >/dev/null
curl -fsS -X POST "$BASE_URL/api/routes/score" -H 'content-type: application/json' -d '{"geometry":{"type":"LineString","coordinates":[[-122.58,37.74],[-122.53,37.78]]},"depart_time":"2026-01-01T10:00:00Z","arrive_by":"2026-01-01T20:00:00Z","run_id":"latest","timestep":0}' >/dev/null

echo "[4/5] Running agents workflow..."
RUN_ID="$(curl -fsS -X POST "$BASE_URL/api/agents/run" -H 'content-type: application/json' -d '{"route_id":"smoke-route","geometry":{"type":"LineString","coordinates":[[-122.58,37.74],[-122.53,37.78]]}}' | python -c 'import sys,json; print(json.load(sys.stdin)["run_id"])')"
echo "run_id=$RUN_ID"

STATUS=""
for i in {1..90}; do
  BODY="$(curl -fsS "$BASE_URL/api/agents/runs/$RUN_ID")"
  STATUS="$(python -c 'import sys,json; print(json.load(sys.stdin).get("status",""))' <<<"$BODY")"
  if [[ "$STATUS" == "succeeded" || "$STATUS" == "failed" ]]; then
    break
  fi
  sleep 1
done

[[ "$STATUS" == "succeeded" ]] || { echo "workflow did not succeed: $STATUS"; exit 1; }

VERIFIED="$(python -c 'import sys,json; data=json.load(sys.stdin); print(data.get("outputs",{}).get("verify",{}).get("verified",False))' <<<"$BODY")"
[[ "$VERIFIED" == "True" ]] || { echo "verifier failed"; exit 1; }

TRIGGERS_OK="$(python -c 'import sys,json; data=json.load(sys.stdin); decision=data.get("outputs",{}).get("decision",{}); print(bool(decision.get("reasoning")))' <<<"$BODY")"
[[ "$TRIGGERS_OK" == "True" ]] || { echo "decision output missing"; exit 1; }

CITATIONS_OK="$(python -c 'import sys,json; data=json.load(sys.stdin); brief=data.get("outputs",{}).get("brief",{}); c=brief.get("json_output",{}).get("citations",[]); print(isinstance(c,list))' <<<"$BODY")"
[[ "$CITATIONS_OK" == "True" ]] || { echo "brief citations missing"; exit 1; }

echo "[5/5] Smoke succeeded."
