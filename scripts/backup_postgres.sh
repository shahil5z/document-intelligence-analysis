#!/usr/bin/env bash
# Back up the production PostgreSQL database (pg_dump custom format, -Fc).
#
#   scripts/backup_postgres.sh [--with-files] [--no-upload]
#
# Writes BACKUP_DIR/dip-<UTC timestamp>.dump (or .dump.gpg when BACKUP_GPG_RECIPIENT is
# set) plus a .sha256 file, checks the dump with pg_restore --list, deletes this script's
# own backups older than BACKUP_RETENTION_DAYS, and, when BACKUP_S3_BUCKET is set, copies
# the new files to object storage with the STORAGE_S3_* endpoint and keys.
# --with-files also archives the uploaded files (local storage volume) as a .tar.gz.
# Read-only for the database; never deletes anything but expired backup files.
set -euo pipefail
# shellcheck source=lib_prod.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_prod.sh"

WITH_FILES=0
UPLOAD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-files) WITH_FILES=1 ;;
    --no-upload) UPLOAD=0 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

require_env_file
BACKUP_DIR="$(env_get BACKUP_DIR /var/backups/dip)"
RETENTION_DAYS="$(env_get BACKUP_RETENTION_DAYS 14)"
GPG_RECIPIENT="$(env_get BACKUP_GPG_RECIPIENT)"
S3_BUCKET="$(env_get BACKUP_S3_BUCKET)"
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || die "BACKUP_RETENTION_DAYS must be a number"

service_running postgres || die "the postgres service is not running"
umask 077
mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$BACKUP_DIR/dip-$stamp.dump"
tmp="$base.partial"
trap 'rm -f "$tmp"' EXIT

log "dumping the database to $base"
# The password never appears on a command line: pg_dump runs inside the container with
# the container's own POSTGRES_* environment.
# shellcheck disable=SC2016  # expanded inside the container
compose exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' >"$tmp"
[[ -s "$tmp" ]] || die "pg_dump produced an empty file"

log "verifying the dump (pg_restore --list)"
compose exec -T postgres pg_restore --list <"$tmp" >/dev/null || die "the dump is not readable by pg_restore"

final="$base"
if [[ -n "$GPG_RECIPIENT" ]]; then
  command -v gpg >/dev/null || die "BACKUP_GPG_RECIPIENT is set but gpg is not installed"
  final="$base.gpg"
  gpg --batch --yes --trust-model always --recipient "$GPG_RECIPIENT" --output "$final" --encrypt "$tmp"
  rm -f "$tmp"
  log "encrypted for $GPG_RECIPIENT"
else
  mv "$tmp" "$final"
fi
(cd "$BACKUP_DIR" && sha256sum "$(basename "$final")" >"$(basename "$final").sha256")
files=("$final" "$final.sha256")

if [[ "$WITH_FILES" -eq 1 ]]; then
  if [[ "$(env_get STORAGE_BACKEND local)" == "local" ]]; then
    archive="$BACKUP_DIR/dip-files-$stamp.tar.gz"
    log "archiving uploaded files to $archive"
    compose exec -T api tar -C /data/storage -cf - . | gzip >"$archive"
    (cd "$BACKUP_DIR" && sha256sum "$(basename "$archive")" >"$(basename "$archive").sha256")
    files+=("$archive" "$archive.sha256")
  else
    log "STORAGE_BACKEND is not local; uploaded files live in object storage (not archived)"
  fi
fi

log "applying retention: removing dip-* backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'dip-*.dump*' -o -name 'dip-files-*.tar.gz*' \) \
  -mtime +"$RETENTION_DAYS" -print -delete

if [[ -n "$S3_BUCKET" && "$UPLOAD" -eq 1 ]]; then
  log "uploading ${#files[@]} file(s) to bucket $S3_BUCKET"
  for file in "${files[@]}"; do
    # shellcheck disable=SC2094  # the file is only read (stdin); the key is just its name
    # boto3 from the application image; credentials come from the container env.
    compose run --rm --no-deps -T -e BACKUP_S3_BUCKET="$S3_BUCKET" -e BACKUP_KEY="backups/$(basename "$file")" \
      --entrypoint python api -c '
import os, sys, boto3
from botocore.config import Config
client = boto3.client(
    "s3",
    endpoint_url=os.environ.get("STORAGE_S3_ENDPOINT_URL") or None,
    region_name=os.environ.get("STORAGE_S3_REGION") or None,
    aws_access_key_id=os.environ["STORAGE_S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["STORAGE_S3_SECRET_ACCESS_KEY"],
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                  request_checksum_calculation="when_required",
                  response_checksum_validation="when_required"),
)
client.upload_fileobj(sys.stdin.buffer, os.environ["BACKUP_S3_BUCKET"], os.environ["BACKUP_KEY"])
' <"$file"
  done
fi

log "backup complete: $final ($(du -h "$final" | cut -f1))"
