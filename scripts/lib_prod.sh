#!/usr/bin/env bash
# Shared helpers for the production scripts (sourced, not executed).
# shellcheck shell=bash

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-$ROOT/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE_PROD:-$ROOT/docker-compose.prod.yml}"
# Extra compose files (space-separated), e.g. the local e2e override when testing.
COMPOSE_EXTRA_FILES="${COMPOSE_EXTRA_FILES:-}"
# DOCKER_CMD="sudo docker" when the user is not in the docker group.
read -r -a DOCKER <<<"${DOCKER_CMD:-docker}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
die() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; exit 1; }

# Read one KEY from the env file without sourcing it (values may contain shell
# metacharacters). Prints nothing when the key is absent. Never echo secret values.
env_get() {
  local key="$1" default="${2:-}" line value
  line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    printf '%s' "$default"
    return
  fi
  value="${line#*=}"
  value="${value%\"}"
  value="${value#\"}"
  printf '%s' "${value:-$default}"
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found (copy .env.production.example and fill it in)"
  local mode
  mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo 600)"
  if [[ "$mode" != "600" && "$mode" != "400" ]]; then
    log "warning: $ENV_FILE has mode $mode; run: chmod 600 $ENV_FILE"
  fi
  if grep -Eq '^[A-Z0-9_]+=<' "$ENV_FILE"; then
    die "$ENV_FILE still has <placeholder> values: $(grep -Eo '^[A-Z0-9_]+=<' "$ENV_FILE" | cut -d= -f1 | tr '\n' ' ')"
  fi
}

compose() {
  local args=(-f "$COMPOSE_FILE")
  local extra
  for extra in $COMPOSE_EXTRA_FILES; do args+=(-f "$extra"); done
  if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then args+=(-p "$COMPOSE_PROJECT_NAME"); fi
  "${DOCKER[@]}" compose "${args[@]}" --env-file "$ENV_FILE" "$@"
}

service_running() {
  [[ -n "$(compose ps --status running --quiet "$1" 2>/dev/null)" ]]
}
