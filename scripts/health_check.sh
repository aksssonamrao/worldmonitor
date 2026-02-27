#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BACKEND_API_URL:-http://localhost:8080}"
ADMIN_KEY="${ADMIN_API_KEY:-}"

ok() { echo "[OK]   $1"; }
fail() { echo "[FAIL] $1"; return 1; }

check_json_endpoint() {
  local name="$1"
  local url="$2"
  local body status
  body=$(curl -sS -m 8 -w $'\n%{http_code}' "$url" || true)
  status=$(echo "$body" | tail -n1)
  if [[ "$status" =~ ^2 ]]; then
    ok "$name status=$status"
  else
    fail "$name status=${status:-000}"
  fi
}

check_post_json() {
  local name="$1"
  local url="$2"
  local payload="$3"
  local body status
  body=$(curl -sS -m 10 -H 'Content-Type: application/json' -d "$payload" -w $'\n%{http_code}' "$url" || true)
  status=$(echo "$body" | tail -n1)
  if [[ "$status" =~ ^2 ]]; then
    ok "$name status=$status"
  else
    fail "$name status=${status:-000}"
  fi
}

failures=0

check_json_endpoint "backend_health" "$BASE_URL/health" || failures=$((failures+1))
check_json_endpoint "compound_health" "$BASE_URL/compound/health" || failures=$((failures+1))
check_json_endpoint "system_status" "$BASE_URL/system/status" || failures=$((failures+1))

# Fast functional smoke that does not depend on external APIs / historical data.
check_post_json "agent_brief" "$BASE_URL/api/agent/brief" '{"prompt":"health check brief"}' || failures=$((failures+1))

if [[ -n "$ADMIN_KEY" ]]; then
  body=$(curl -sS -m 8 -H "X-Admin-Key: $ADMIN_KEY" -w $'\n%{http_code}' "$BASE_URL/internal/jobs/stats" || true)
  status=$(echo "$body" | tail -n1)
  if [[ "$status" =~ ^2 ]]; then
    ok "job_queue_stats status=$status"
  else
    fail "job_queue_stats status=${status:-000}"
    failures=$((failures+1))
  fi
else
  echo "[SKIP] job_queue_stats (ADMIN_API_KEY not set)"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "Health check completed with $failures failure(s)."
  exit 1
fi

echo "Health check passed for backend architecture."
