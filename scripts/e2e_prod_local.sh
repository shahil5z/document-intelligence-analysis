#!/usr/bin/env bash
# Production-like end-to-end run on one machine (Linux/macOS/WSL with Docker):
#   docker-compose.prod.yml + docker-compose.prod.e2e.yml (APP_ENV=production, gunicorn,
#   Caddy HTTPS with its local CA, stub LLM), the Next.js production build behind Caddy at
#   https://app.localhost:8443, then the Playwright suite in frontend/e2e.
#
# Usage: scripts/e2e_prod_local.sh [--down]     (--down removes the stack and its volumes)
# Needs: docker compose, node/npm (frontend deps installed), curl, python3, and
#        "127.0.0.1 api.localhost app.localhost" in /etc/hosts (for Node and curl).
# Never touches a real OpenAI key: /ask goes to scripts/stub_llm_server.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_DIR="$ROOT/.e2e"
ENV_FILE="$E2E_DIR/env.production"
HTTPS_PORT="${E2E_HTTPS_PORT:-8443}"
API_URL="https://api.localhost:${HTTPS_PORT}"
APP_URL="https://app.localhost:${HTTPS_PORT}"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-dip-e2e}"
# DOCKER_CMD="sudo docker" if your user is not in the docker group.
read -r -a DOCKER <<<"${DOCKER_CMD:-docker}"
COMPOSE=("${DOCKER[@]}" compose -p "$COMPOSE_PROJECT_NAME" -f "$ROOT/docker-compose.prod.yml" -f "$ROOT/docker-compose.prod.e2e.yml" --env-file "$ENV_FILE")

log() { printf '[e2e] %s\n' "$*"; }

if [[ "${1:-}" == "--down" ]]; then
  [[ -f "$ENV_FILE" ]] || { log "nothing to remove"; exit 0; }
  "${COMPOSE[@]}" down --volumes --remove-orphans
  exit 0
fi

for host in api.localhost app.localhost; do
  if ! getent hosts "$host" >/dev/null 2>&1; then
    log "$host does not resolve; add '127.0.0.1 api.localhost app.localhost' to /etc/hosts"
    exit 1
  fi
done

mkdir -p "$E2E_DIR"
chmod 700 "$E2E_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  log "writing $ENV_FILE with fresh random secrets"
  umask 077
  python3 - "$ENV_FILE" "$HTTPS_PORT" <<'PY'
import secrets, sys
path, port = sys.argv[1], sys.argv[2]
lines = {
    "APP_ENV": "production",
    "API_DOMAIN": "api.localhost",
    "CADDY_TLS": "internal",
    "CADDY_HTTP_PORT": "8080",
    "CADDY_HTTPS_PORT": port,
    "CORS_ALLOWED_ORIGINS": f"https://app.localhost:{port}",
    "JWT_SECRET_KEY": secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "REDIS_PASSWORD": secrets.token_urlsafe(24),
    # Only the local stub sees this value; it is not an OpenAI key.
    "OPENAI_API_KEY": "stub-" + secrets.token_hex(8),
    "E2E_FRONTEND_UPSTREAM": "host.docker.internal:3000",
    "HF_HUB_OFFLINE": "0",
    # Generous limits so repeated local runs are not throttled.
    "RATE_LIMIT_REGISTER": "100/hour",
    "RATE_LIMIT_LOGIN": "100/minute",
    "RATE_LIMIT_UPLOAD": "200/day",
    "RATE_LIMIT_ASK": "200/hour",
}
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(f"{k}={v}\n" for k, v in lines.items())
PY
fi
# The Caddy root certificate is only readable once Caddy has created it; until then the
# api bind mount needs the file to exist.
touch "$E2E_DIR/caddy-root.crt"

log "building and starting the production stack (project $COMPOSE_PROJECT_NAME)"
"${COMPOSE[@]}" build api
if [[ -n "${SEED_HF_CACHE:-}" && -d "${SEED_HF_CACHE}/hub" ]]; then
  log "seeding the model cache volume from $SEED_HF_CACHE"
  "${COMPOSE[@]}" run --rm --no-deps -v "${SEED_HF_CACHE}:/seed:ro" --entrypoint sh api \
    -c 'cp -rn /seed/hub /data/models/ 2>/dev/null || true'
fi
"${COMPOSE[@]}" up -d --wait --wait-timeout 300

log "exporting Caddy's local root certificate"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T caddy cat /data/caddy/pki/authorities/local/root.crt >"$E2E_DIR/caddy-root.crt.tmp" 2>/dev/null \
    && [[ -s "$E2E_DIR/caddy-root.crt.tmp" ]]; then
    break
  fi
  sleep 2
done
cat "$E2E_DIR/caddy-root.crt.tmp" >"$E2E_DIR/caddy-root.crt"
rm -f "$E2E_DIR/caddy-root.crt.tmp"
[[ -s "$E2E_DIR/caddy-root.crt" ]] || { log "Caddy root certificate not found"; exit 1; }

log "checking $API_URL/health/ready over HTTPS"
curl -fsS --retry 20 --retry-delay 3 --retry-all-errors --cacert "$E2E_DIR/caddy-root.crt" "$API_URL/health/ready" >/dev/null
code="$(curl -s -o /dev/null -w '%{http_code}' --cacert "$E2E_DIR/caddy-root.crt" "$API_URL/metrics")"
[[ "$code" == "404" ]] || { log "/metrics is reachable from outside (HTTP $code)"; exit 1; }

log "building the frontend for $API_URL"
cd "$ROOT/frontend"
NEXT_PUBLIC_API_URL="$API_URL" NEXT_TELEMETRY_DISABLED=1 npm run build >"$E2E_DIR/next-build.log" 2>&1
NODE_EXTRA_CA_CERTS="$E2E_DIR/caddy-root.crt" NEXT_PUBLIC_API_URL="$API_URL" \
  npx next start -H 0.0.0.0 -p 3000 >"$E2E_DIR/next-start.log" 2>&1 &
NEXT_PID=$!
trap 'kill "$NEXT_PID" 2>/dev/null || true' EXIT
curl -fsS --retry 30 --retry-delay 1 --retry-all-errors --cacert "$E2E_DIR/caddy-root.crt" "$APP_URL/" >/dev/null

log "running Playwright against $APP_URL"
E2E_BASE_URL="$APP_URL" E2E_API_URL="$API_URL" npx playwright test "$@"
