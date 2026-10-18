#!/usr/bin/env bash
# Deploy or update the production stack on the server (idempotent, never drops data).
#
#   scripts/deploy.sh [--ref <branch|tag|commit>] [--no-pull] [--skip-backup] [--no-smoke]
#
# 1. refuses to run with local changes in the checkout, then fetches and checks out --ref
#    (default: fast-forward the current branch);
# 2. backs up PostgreSQL (scripts/backup_postgres.sh) if it is already running;
# 3. builds the application image and pulls the pinned base images;
# 4. starts PostgreSQL/Redis and runs `alembic upgrade head` in a one-off container;
# 5. (re)starts api, worker, beat and Caddy and waits for their health checks;
# 6. runs scripts/health_check.sh and, when SMOKE_EMAIL and SMOKE_PASSWORD are set,
#    scripts/production_smoke_test.py.
# Volumes are never removed; there is no `down -v`, no `alembic downgrade`, no reset.
set -euo pipefail
# shellcheck source=lib_prod.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_prod.sh"

REF=""
PULL=1
BACKUP=1
SMOKE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) REF="${2:-}"; shift ;;
    --no-pull) PULL=0 ;;
    --skip-backup) BACKUP=0 ;;
    --no-smoke) SMOKE=0 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

cd "$ROOT"
require_env_file

exec 9>"${TMPDIR:-/tmp}/dip-deploy.lock"
flock -n 9 || die "another deploy is running"

previous="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ "$PULL" -eq 1 ]]; then
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "the checkout has local changes; commit or stash them first"
  log "fetching from origin"
  git fetch --tags --prune origin
  if [[ -n "$REF" ]]; then
    if git show-ref --verify --quiet "refs/remotes/origin/$REF"; then
      git checkout -B "$REF" "origin/$REF"
    else
      git checkout --detach "$REF"
    fi
  elif git symbolic-ref -q HEAD >/dev/null; then
    git merge --ff-only "@{upstream}"
  fi
fi
current="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
log "deploying $current (previous: $previous)"

if [[ "$BACKUP" -eq 1 ]] && service_running postgres; then
  log "backing up the database before the update"
  "$ROOT/scripts/backup_postgres.sh"
fi

log "building the application image"
compose build --pull api
compose pull --quiet postgres redis caddy

log "starting PostgreSQL and Redis"
compose up -d --wait postgres redis

log "running database migrations (alembic upgrade head)"
compose run --rm --no-deps migrate

log "starting the application"
compose up -d --wait --wait-timeout 300 api worker beat caddy

# HEALTH_ARGS: extra options for health_check.sh, e.g. "--cacert /path/ca.crt".
read -r -a health_args <<<"${HEALTH_ARGS:-}"
"$ROOT/scripts/health_check.sh" "${health_args[@]}"

if [[ "$SMOKE" -eq 1 && -n "${SMOKE_EMAIL:-}" && -n "${SMOKE_PASSWORD:-}" ]]; then
  log "running the production smoke test"
  read -r -a smoke_args <<<"${SMOKE_ARGS:-}"
  python3 "$ROOT/scripts/production_smoke_test.py" --base-url "${SMOKE_BASE_URL:-https://$(env_get API_DOMAIN)}" "${smoke_args[@]}"
elif [[ "$SMOKE" -eq 1 ]]; then
  log "smoke test skipped (set SMOKE_EMAIL and SMOKE_PASSWORD to run it)"
fi

log "deploy of $current finished. Roll back with: scripts/deploy.sh --ref $previous"
