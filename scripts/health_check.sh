#!/usr/bin/env bash
# Health check for the production stack. Exit code 0 = healthy.
#
#   scripts/health_check.sh [--url https://api.example.com] [--cacert <file>] [--internal-only]
#
# Checks: every long-running service is running (and healthy where it has a
# healthcheck), /health/ready inside the api container (PostgreSQL + Redis), the public
# URL over HTTPS (/health/ready 200, /metrics blocked with 404), and free disk space.
set -euo pipefail
# shellcheck source=lib_prod.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_prod.sh"

URL=""
CACERT=""
INTERNAL_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="${2:-}"; shift ;;
    --cacert) CACERT="${2:-}"; shift ;;
    --internal-only) INTERNAL_ONLY=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

require_env_file
failures=0
fail() { log "FAIL: $*"; failures=$((failures + 1)); }
ok() { log "ok:   $*"; }

for service in postgres redis api worker beat caddy; do
  id="$(compose ps --quiet "$service" 2>/dev/null || true)"
  if [[ -z "$id" ]]; then
    fail "$service is not created"
    continue
  fi
  state="$("${DOCKER[@]}" inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id")"
  case "$state" in
    "running healthy"|"running none") ok "$service ($state)" ;;
    *) fail "$service ($state)" ;;
  esac
done

if compose exec -T api python -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5); sys.exit(0 if json.load(r).get('status') == 'ready' else 1)" >/dev/null 2>&1; then
  ok "api /health/ready (PostgreSQL and Redis reachable)"
else
  fail "api /health/ready"
fi

if [[ "$INTERNAL_ONLY" -eq 0 ]]; then
  [[ -n "$URL" ]] || URL="https://$(env_get API_DOMAIN)"
  curl_args=(-sS -o /dev/null -w '%{http_code}' --max-time 10)
  [[ -n "$CACERT" ]] && curl_args+=(--cacert "$CACERT")
  code="$(curl "${curl_args[@]}" "$URL/health/ready" || echo 000)"
  if [[ "$code" == "200" ]]; then ok "$URL/health/ready -> 200"; else fail "$URL/health/ready -> $code"; fi
  code="$(curl "${curl_args[@]}" "$URL/metrics" || echo 000)"
  if [[ "$code" == "404" ]]; then ok "$URL/metrics is blocked (404)"; else fail "$URL/metrics -> $code (must be 404)"; fi
fi

used="$(df --output=pcent / | tail -n 1 | tr -dc '0-9')"
if [[ "$used" -ge 90 ]]; then fail "root filesystem ${used}% full"; else ok "root filesystem ${used}% used"; fi

if [[ "$failures" -gt 0 ]]; then
  log "$failures check(s) failed"
  exit 1
fi
log "all checks passed"
