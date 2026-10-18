# Backup and recovery

What holds state in production (`docker-compose.prod.yml`):

| Data | Where | Backed up by |
| --- | --- | --- |
| Users, documents metadata, jobs, chunks + embeddings, audit log | `postgres_data` volume | `scripts/backup_postgres.sh` (pg_dump `-Fc`) |
| Uploaded files (`STORAGE_BACKEND=local`) | `storage_data` volume | `backup_postgres.sh --with-files` (tar.gz) |
| Uploaded files (`STORAGE_BACKEND=oci`) | OCI Object Storage bucket | Object Storage durability; optionally bucket versioning / replication (OCI console) |
| Redis (AOF on) | `redis_data` | not backed up: it holds the Celery queue and rate-limit counters. Losing the volume resets the counters and drops jobs that were queued but not started; those documents stay `queued` (the stale-job reconciler only handles `processing`/`retrying`), so delete and re-upload them |
| TLS certificates | `caddy_data` | not needed: Caddy re-issues them |
| Embedding model | `model_cache` | not needed: re-downloaded |
| Secrets | `/opt/dip/.env.production` | **you**: keep a copy in a password manager. Without `JWT_SECRET_KEY` sessions just restart; without `POSTGRES_PASSWORD` you need the dump to rebuild. |

Chunks and embeddings can always be rebuilt from the files with `reprocess`, but the
database also holds users and ownership, so back up the database **and** the files
together.

## Taking backups

```bash
cd /opt/dip
scripts/backup_postgres.sh                 # database only
scripts/backup_postgres.sh --with-files    # + uploaded files (local storage)
scripts/backup_postgres.sh --no-upload     # skip the optional bucket copy
```

- Output: `BACKUP_DIR/dip-<UTC stamp>.dump` (default `/var/backups/dip`, mode 0600) and
  a `.sha256`. Every dump is verified with `pg_restore --list` before it is kept.
- `BACKUP_GPG_RECIPIENT=<key id or e-mail>`: the dump is encrypted to that **public**
  key (`.dump.gpg`); keep the private key off the server.
- `BACKUP_S3_BUCKET=<bucket>`: the new files are also copied to that bucket using the
  `STORAGE_S3_*` endpoint and keys (boto3 inside the api image). Use a different bucket
  from the documents bucket, ideally with a retention rule.
- `BACKUP_RETENTION_DAYS` (default 14): older `dip-*` files in `BACKUP_DIR` are deleted;
  nothing else is.
- `deploy.sh` takes a backup automatically before every update (unless `--skip-backup`).

Daily cron for the `deploy` user:

```cron
15 3 * * * cd /opt/dip && scripts/backup_postgres.sh --with-files >> /var/backups/dip/backup.log 2>&1
```

Backups on the VM disk do not survive losing the VM. Copy them off the machine
(`BACKUP_S3_BUCKET`, or `scp deploy@host:/var/backups/dip/dip-*.dump* .` from your PC) and
take occasional OCI boot-volume backups (five are free).

## Verifying a backup (non-destructive)

```bash
cd /var/backups/dip && sha256sum -c dip-<stamp>.dump.sha256
cd /opt/dip && scripts/restore_postgres.sh --file /var/backups/dip/dip-<stamp>.dump --into dip_restore_check
#   prints users=.. documents=.. chunks=.. alembic=..   compare with the live counts
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
  sh -c 'dropdb -U "$POSTGRES_USER" dip_restore_check'
```

`--into` only ever creates a **new** database and refuses an existing name. Do this
monthly; an untested backup is a hope, not a backup.

## Restoring the live database

```bash
scripts/restore_postgres.sh --file /var/backups/dip/dip-<stamp>.dump \
  --replace-live-database --i-understand-this-overwrites-data
```

Both flags are required. The script verifies the checksum, takes a **safety backup** of
the current database, stops `api`, `worker` and `beat`, runs
`pg_restore --clean --if-exists` into the live database, and starts the services again
(waiting for their healthchecks). Then run `scripts/health_check.sh --url https://<API_DOMAIN>`.

## Restoring uploaded files (local storage)

```bash
cd /opt/dip
C="docker compose -f docker-compose.prod.yml --env-file .env.production"
(cd /var/backups/dip && sha256sum -c dip-files-<stamp>.tar.gz.sha256)
$C exec -T api tar -xzf - -C /data/storage < /var/backups/dip/dip-files-<stamp>.tar.gz
```

Restore the files from the same time as the database dump, so every document row has
its file.

## Disaster recovery (new VM)

1. Create the VM and run `setup_server.sh` ([oracle-cloud-deployment.md](oracle-cloud-deployment.md)).
2. Clone the repository to `/opt/dip`, check out the same ref, restore `.env.production`
   from your password manager (same `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
   `JWT_SECRET_KEY`).
3. Point DNS at the new IP (or change the sslip.io name and Vercel's
   `NEXT_PUBLIC_API_URL`, then redeploy the frontend).
4. `scripts/deploy.sh` (creates empty volumes and runs migrations).
5. Copy the dump (and files archive) to `/var/backups/dip`, then restore with
   `--replace-live-database --i-understand-this-overwrites-data` and the files command.
6. `scripts/health_check.sh --url https://<API_DOMAIN>` and
   `python3 scripts/production_smoke_test.py --base-url https://<API_DOMAIN>`.

Targets for this single-VM demo: RPO = time since the last backup (24 h with the daily
cron), RTO = roughly one hour by hand. There is no replication or failover.

## What was tested (locally, production-like stack)

All on the local `docker-compose.prod.yml` + `docker-compose.prod.e2e.yml` stack, not on
a real server:

- `backup_postgres.sh --with-files`: dump verified with `pg_restore --list`, checksum
  written, files archive created.
- `restore_postgres.sh --into dip_restore_check`: counts matched the live database
  (users 10, documents 6, chunks 5, alembic `0002`); a second run into the same name was
  refused; `--replace-live-database` without the second flag was refused.
- Live restore drill: deleted all documents and chunks, ran
  `--replace-live-database --i-understand-this-overwrites-data`, counts returned to
  10 / 6 / 5, health check passed.
- GPG: encrypted dump (`.dump.gpg`) restored with `--into` using a throw-away key.
- Files archive: checksum verified; extracted into a scratch directory in the api
  container, same file count as `/data/storage` (6).
- Upload to `BACKUP_S3_BUCKET`: NOT VERIFIED against a real bucket.
