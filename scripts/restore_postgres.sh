#!/usr/bin/env bash
# Restore a pg_dump (-Fc) backup made by scripts/backup_postgres.sh.
#
#   Check a backup without touching production (restores into a NEW scratch database):
#     scripts/restore_postgres.sh --file /var/backups/dip/dip-<stamp>.dump --into dip_restore_check
#   Replace the live database (stops api/worker/beat, takes a safety backup first):
#     scripts/restore_postgres.sh --file <dump> --replace-live-database --i-understand-this-overwrites-data
#
# .gpg files are decrypted with the local gpg keyring; a matching .sha256 is verified.
set -euo pipefail
# shellcheck source=lib_prod.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_prod.sh"

FILE=""
INTO=""
REPLACE=0
CONFIRMED=0
SAFETY_BACKUP=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) FILE="${2:-}"; shift ;;
    --into) INTO="${2:-}"; shift ;;
    --replace-live-database) REPLACE=1 ;;
    --i-understand-this-overwrites-data) CONFIRMED=1 ;;
    --no-safety-backup) SAFETY_BACKUP=0 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

require_env_file
[[ -n "$FILE" && -f "$FILE" ]] || die "--file <backup> is required and must exist"
if [[ -n "$INTO" && "$REPLACE" -eq 1 ]]; then die "use either --into or --replace-live-database"; fi
if [[ -z "$INTO" && "$REPLACE" -eq 0 ]]; then die "choose --into <new database> or --replace-live-database"; fi
if [[ "$REPLACE" -eq 1 && "$CONFIRMED" -eq 0 ]]; then
  die "--replace-live-database also needs --i-understand-this-overwrites-data"
fi
if [[ -n "$INTO" && ! "$INTO" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then die "invalid database name: $INTO"; fi
service_running postgres || die "the postgres service is not running"

if [[ -f "$FILE.sha256" ]]; then
  log "verifying checksum"
  (cd "$(dirname "$FILE")" && sha256sum --check --quiet "$(basename "$FILE").sha256") || die "checksum mismatch"
fi

work="$(mktemp)"
trap 'rm -f "$work"' EXIT
if [[ "$FILE" == *.gpg ]]; then
  log "decrypting"
  gpg --batch --quiet --output - --decrypt "$FILE" >"$work"
else
  cp "$FILE" "$work"
fi
compose exec -T postgres pg_restore --list <"$work" >/dev/null || die "not a readable pg_dump archive"

if [[ -n "$INTO" ]]; then
  exists="$(compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -Atc \"SELECT 1 FROM pg_database WHERE datname = '$INTO'\"")"
  [[ -z "$exists" ]] || die "database $INTO already exists; pick a new name (nothing was changed)"
  log "creating scratch database $INTO and restoring into it"
  compose exec -T postgres sh -c "createdb -U \"\$POSTGRES_USER\" '$INTO'"
  compose exec -T postgres sh -c "pg_restore -U \"\$POSTGRES_USER\" -d '$INTO' --no-owner --exit-on-error" <"$work"
  compose exec -T postgres sh -c "psql -U \"\$POSTGRES_USER\" -d '$INTO' -Atc \"SELECT 'users=' || (SELECT count(*) FROM users) || ' documents=' || (SELECT count(*) FROM documents) || ' chunks=' || (SELECT count(*) FROM document_chunks) || ' alembic=' || (SELECT version_num FROM alembic_version)\""
  log "restored into $INTO. Drop it when done: docker compose ... exec postgres dropdb -U <user> $INTO"
  exit 0
fi

if [[ "$SAFETY_BACKUP" -eq 1 ]]; then
  log "taking a safety backup of the current database first"
  "$(dirname "${BASH_SOURCE[0]}")/backup_postgres.sh" --no-upload
fi
log "stopping api, worker and beat"
compose stop api worker beat
log "restoring into the live database (pg_restore --clean --if-exists)"
# shellcheck disable=SC2016  # expanded by the container's shell, not this one
compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' <"$work"
log "starting api, worker and beat"
compose up -d --wait api worker beat
log "restore complete; run scripts/health_check.sh"
