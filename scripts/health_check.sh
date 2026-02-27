#!/usr/bin/env bash
set -euo pipefail

check_endpoint() {
  local name="$1"
  local url="$2"

  local body status
  body=$(curl -sS -m 8 -w $'\n%{http_code}' "$url" || true)
  status=$(echo "$body" | tail -n1)
  payload=$(echo "$body" | sed '$d')

  if [[ "$status" =~ ^2 ]]; then
    freshness=$(python - <<'PY' "$payload"
import json,sys
try:
    d=json.loads(sys.argv[1])
except Exception:
    print('n/a')
    raise SystemExit(0)
for key in ('events_freshness','hazards_freshness','alerts_freshness','last_hazard_run'):
    if d.get(key):
        print(f"{key}={d[key]}")
        raise SystemExit(0)
if isinstance(d.get('ingestion_state'), dict):
    vals=[]
    for k,v in d['ingestion_state'].items():
        if isinstance(v, dict) and v.get('last_run'):
            vals.append(f"{k}:{v['last_run']}")
    print(','.join(vals) if vals else 'n/a')
else:
    print('n/a')
PY
)
    echo "[OK]   $name status=$status freshness=$freshness"
  else
    echo "[FAIL] $name status=${status:-000}"
    return 1
  fi
}

failures=0
check_endpoint "routing_api" "${ROUTING_API_URL:-http://localhost:8093/health}" || failures=$((failures+1))
check_endpoint "compound_api" "${COMPOUND_API_HEALTH_URL:-http://localhost:8090/compound/health}" || failures=$((failures+1))
check_endpoint "system_status" "${COMPOUND_STATUS_URL:-http://localhost:8090/system/status}" || failures=$((failures+1))
check_endpoint "planner" "${PLANNER_API_URL:-http://localhost:8091/health}" || failures=$((failures+1))
check_endpoint "ingestor" "${INGESTOR_API_URL:-http://localhost:8092/ingestor/health}" || failures=$((failures+1))

if [[ "$failures" -gt 0 ]]; then
  echo "Health check completed with $failures failure(s)."
  exit 1
fi

echo "Health check passed for all services."
