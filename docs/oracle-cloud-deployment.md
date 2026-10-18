# Oracle Cloud (OCI) Always Free deployment

Target: one **Ampere A1 Flex** VM (arm64) in the tenancy's home region running
`docker-compose.prod.yml` behind Caddy, optionally with **OCI Object Storage** for
uploaded files. The frontend runs on Vercel ([vercel-deployment.md](vercel-deployment.md)).
Generic steps (env file, deploy, update, CI/CD) are in
[production-deployment.md](production-deployment.md).

Status: **CONFIGURED BUT NOT DEPLOYED** (no access to an OCI tenancy while this was
built). The arm64 image build, app import, an embedding and the unit tests were run
**under QEMU emulation** locally; that is evidence the image works on arm64, not a
measurement of A1 performance.

## What Always Free gives you (from Oracle's documentation)

Checked against Oracle's "Always Free Resources" page
(docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
on 2026-10-18. Limits
change; re-read the current page before you rely on them.

- Oracle Always Free resources are available for the life of the account within the
  applicable Always Free limits. Oracle's wording: "All Oracle Cloud Infrastructure
  accounts (whether free or paid) have a set of resources that are free of charge in the
  home region of the tenancy, for the life of the account."
- Ampere A1 compute: "the first 1,500 OCPU hours and 9,000 GB hours per month" are free,
  for `VM.Standard.A1.Flex`; "For Always Free tenancies, this is equivalent to 2 OCPUs
  and 12 GB of memory" (one 2-OCPU instance or two 1-OCPU instances).
- "You must create the Always Free compute instances in your home region."
- Block Volume: 200 GB total across boot and block volumes, and five volume backups;
  the default boot volume is about 50 GB (minimum 47 GB).
- Object Storage: 20 GB, and 50,000 API requests per month. (On paid/trial accounts the
  free amount is counted per storage tier.)
- Outbound data transfer: 10 TB per month.
- Idle compute reclamation: Oracle may reclaim Always Free instances that are idle for
  7 days, where idle means all of: CPU utilisation (95th percentile) below 20%, network
  utilisation below 20%, and, for A1 shapes, memory utilisation below 20%. A demo with
  very little traffic can meet these conditions. The page states the policy but not how
  to opt out; read Oracle's current guidance before relying on an idle demo VM.
- "Out of host capacity" when creating an A1 instance "indicates a temporary lack of
  Always Free shapes in your home region. Try creating the instance in a different
  availability domain, or wait a while". Oracle's troubleshooting page also suggests a
  different fault domain or shape size. Oracle also notes you can upgrade to Pay As You
  Go for more shape availability, and that "Oracle doesn't charge for Always Free
  resources after you upgrade" (only usage above the limits is billed).

What this project uses: 1 VM (2 OCPU / 12 GB, the full A1 allowance), a ~50-100 GB boot
volume, optionally one Object Storage bucket (well under 20 GB for a demo) and the 10 TB
egress. Nothing else in the stack needs a paid service. The OpenAI API is **not** part
of OCI and is billed by OpenAI per token.

## 1. Create the VM (console)

1. Sign in, confirm the **home region** (top right; Always Free only exists there).
2. Networking > Virtual cloud networks > **Start VCN Wizard** > "Create VCN with Internet
   Connectivity". Defaults are fine.
3. In the public subnet's **security list** (or an NSG attached to the VM) add ingress
   rules: source `0.0.0.0/0`, TCP destination ports **80** and **443**. Port 22 is there
   by default; restrict it to your IP if you can.
4. Compute > Instances > **Create instance**:
   - Image: **Canonical Ubuntu 24.04** (or 22.04), the aarch64 build.
   - Shape: **Ampere** > `VM.Standard.A1.Flex`, **2 OCPUs, 12 GB** memory.
   - Networking: the VCN's public subnet, "Assign a public IPv4 address".
   - SSH keys: paste **your** public key (keep the private key on your PC).
   - Boot volume: 50 GB is enough for the images, model cache and a demo database;
     up to 200 GB total is free.
   - If you get "Out of host capacity", try another availability domain or try later.
5. Note the public IP. Optional but useful: reserve it (Networking > IP management >
   Reserved public IPs) so it survives instance re-creation.

## 2. A hostname

Caddy needs a name that resolves to the VM for Let's Encrypt:

- Quickest: `<ip-with-dashes>.sslip.io`, e.g. `203-0-113-7.sslip.io` (or
  `203.0.113.7.nip.io`). No account; the name is tied to the IP.
- DuckDNS: create `<name>.duckdns.org`, set it to the VM IP.
- Your own domain: `A` record `api.example.com -> <ip>`.

Check from your PC: `nslookup <name>` returns the VM IP.

## 3. Prepare the server

```bash
ssh ubuntu@<public-ip>
sudo apt-get update && sudo apt-get install -y git
git clone <your-repo-url> /tmp/dip
sudo /tmp/dip/scripts/setup_server.sh
```

`setup_server.sh` (idempotent; never touches the SSH daemon config): base packages,
Docker Engine + compose plugin from download.docker.com with log rotation,
**host firewall** (Oracle's Ubuntu images ship `/etc/iptables/rules.v4` that rejects
everything but SSH; the script inserts ACCEPT rules for 80/443 before the REJECT rule
and saves them, or uses ufw on other images), a 4 GB swap file (swappiness 10),
unattended security upgrades, a `deploy` user in the `docker` group with your
`authorized_keys`, `/opt/dip` and `/var/backups/dip`.

Both firewalls matter: the OCI security list (step 1.3) **and** the host iptables.
Missing either one shows up as Let's Encrypt timeouts in `docker compose logs caddy`.

## 4. Configure and deploy

```bash
sudo -iu deploy
git clone <your-repo-url> /opt/dip && cd /opt/dip && git checkout final
cp .env.production.example .env.production && chmod 600 .env.production
nano .env.production
#   API_DOMAIN=203-0-113-7.sslip.io
#   CADDY_TLS=you@example.com
#   CORS_ALLOWED_ORIGINS=https://<your-project>.vercel.app
#   JWT_SECRET_KEY / POSTGRES_PASSWORD / REDIS_PASSWORD = random values
#   OPENAI_API_KEY=  (optional; empty disables /ask with a clear 503)
scripts/deploy.sh
scripts/health_check.sh --url https://203-0-113-7.sslip.io
```

## 5. Optional: OCI Object Storage for uploads

By default uploads live in the `storage_data` Docker volume on the boot volume (back it
up with `backup_postgres.sh --with-files`). To keep them in Object Storage instead:

1. Storage > Buckets > **Create bucket** (private, Standard tier), e.g. `dip-documents`.
2. Find the **namespace** (Tenancy details, or the bucket page).
3. Profile > **Customer secret keys** > Generate. Copy the secret immediately (shown
   once); the access key is listed afterwards. These are S3-compatible credentials for
   your user; for least privilege create a dedicated user/group with a policy limited
   to that bucket, e.g.
   `Allow group dip-storage to manage objects in compartment <c> where target.bucket.name='dip-documents'`.
4. In `.env.production`:

   ```ini
   STORAGE_BACKEND=oci
   STORAGE_S3_BUCKET=dip-documents
   STORAGE_S3_ENDPOINT_URL=https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
   STORAGE_S3_REGION=<region>            # e.g. eu-frankfurt-1
   STORAGE_S3_ACCESS_KEY_ID=<access key>
   STORAGE_S3_SECRET_ACCESS_KEY=<secret>
   ```

5. `scripts/deploy.sh`. The backend uses path-style addressing and SigV4 against the
   compatibility endpoint. Existing files in the volume are **not** migrated
   automatically; switch before real data arrives, or copy objects with the same keys.

The S3 backend is tested against a local S3-compatible server (SeaweedFS) and moto;
it was **not** run against real OCI Object Storage here (NOT VERIFIED).

Remember the free tier counts API requests (50,000/month): each upload is one PUT, each
processing run one GET, each delete one DELETE, so a demo stays far below it.

## 6. Keep it healthy

- `scripts/health_check.sh --url https://<API_DOMAIN>` from cron or an external uptime
  checker (e.g. every 5 minutes). Do not generate artificial load to dodge Oracle's
  idle-reclamation policy; if the instance must stay up, follow Oracle's current
  guidance (e.g. a paid account).
- Daily backup: `crontab -e` as `deploy`:
  `15 3 * * * cd /opt/dip && scripts/backup_postgres.sh --with-files >> /var/backups/dip/backup.log 2>&1`
- Boot volume backups: up to five volume backups are free; take one before big changes
  (Block Storage > Boot volumes > Create manual backup).
- `docker system df` / `df -h /` monthly; `docker image prune -f` after updates.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Caddy logs `timeout during connect` / ACME errors | security list ingress 80/443, host iptables (`sudo iptables -L INPUT -n --line-numbers`: ACCEPT 80/443 must be above REJECT), DNS name resolves to the VM |
| `Out of host capacity` | another availability domain, or retry later |
| Build is slow or OOM | `WEB_CONCURRENCY=1`, `WORKER_CONCURRENCY=1`; swap active (`swapon --show`) |
| `/ask` returns 503 "not configured" | `OPENAI_API_KEY` empty or placeholder (expected without a key) |
| Browser shows CORS errors on upload | `CORS_ALLOWED_ORIGINS` must equal the Vercel origin exactly (scheme + host, no path, no trailing slash) |
| Uploads fail with 413 | file above 10 MB (`MAX_UPLOAD_SIZE_BYTES`; Caddy allows 11 MB) |
