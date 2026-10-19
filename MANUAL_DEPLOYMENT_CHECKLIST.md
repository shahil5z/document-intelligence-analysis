# Manual deployment checklist

Everything here needs your accounts (Oracle Cloud, a DNS name, Vercel, GitHub, OpenAI)
and was **not** done while building the project. Tick the boxes in order. Details:
[docs/oracle-cloud-deployment.md](docs/oracle-cloud-deployment.md),
[docs/vercel-deployment.md](docs/vercel-deployment.md),
[docs/production-deployment.md](docs/production-deployment.md).

## A. Repository

- [ ] Push the `final` branch to your GitHub repository (from your PC:
      `git remote add origin <url>` then `git push -u origin final`, or merge into `main`).
- [ ] Check that `.env`, `env`, `.env.production` are **not** in the push (`git ls-files | findstr env`
      in PowerShell shows only `.env.example`, `.env.production.example`, `frontend/.env.example`).

## B. Oracle Cloud VM

- [ ] Sign in; note your **home region** (Always Free exists only there).
- [ ] VCN wizard "with Internet Connectivity".
- [ ] Security list / NSG ingress: TCP 80 and 443 from `0.0.0.0/0` (22 ideally only from your IP).
- [ ] Create instance: Ubuntu 24.04 aarch64, `VM.Standard.A1.Flex` 2 OCPU / 12 GB, public IPv4, your SSH public key.
      On "Out of host capacity": another availability domain, or retry later.
- [ ] (Optional) reserve the public IP.
- [ ] `ssh ubuntu@<ip>`; `git clone <repo> /tmp/dip && sudo /tmp/dip/scripts/setup_server.sh`.
- [ ] `sudo iptables -L INPUT -n --line-numbers`: ACCEPT 80 and 443 appear above REJECT.

## C. Hostname

- [ ] Choose one: your domain (`A` record), `<ip-with-dashes>.sslip.io`, or a DuckDNS name.
- [ ] `nslookup <name>` from your PC returns the VM IP.

## D. Server configuration and first deploy

- [ ] `sudo -iu deploy`; `git clone <repo> /opt/dip && cd /opt/dip && git checkout final`.
- [ ] `cp .env.production.example .env.production && chmod 600 .env.production`.
- [ ] Fill `API_DOMAIN`, `CADDY_TLS` (your e-mail), `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`,
      `REDIS_PASSWORD` (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).
- [ ] `CORS_ALLOWED_ORIGINS`: leave the placeholder until step E gives you the Vercel
      URL, or put the expected URL now.
- [ ] Generate `CLIENT_IP_HEADER_SECRET` (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
      and put it in `.env.production`; you set the same value on Vercel in step E. Without it,
      per-IP limits (including the demo's 3 sessions per IP per day) count Vercel's egress IPs.
- [ ] Review the public-demo limits (`DEMO_*`, `RATE_LIMIT_*_DAILY`, `RATE_LIMIT_DEMO*`) or set
      `DEMO_ENABLED=false` to turn the demo off.
- [ ] Store a copy of `.env.production` in your password manager.
- [ ] `scripts/deploy.sh` (first build takes several minutes).
- [ ] `scripts/health_check.sh --url https://<API_DOMAIN>` prints "all checks passed".
- [ ] Browser: `https://<API_DOMAIN>/health/ready` shows `"status":"ready"` with a valid certificate;
      `https://<API_DOMAIN>/metrics` is 404.

## E. Vercel

- [ ] New project from the GitHub repository; **Root Directory `frontend`**.
- [ ] Environment variable `NEXT_PUBLIC_API_URL=https://<API_DOMAIN>` (Production; no trailing slash; not a secret).
- [ ] `DIP_CLIENT_IP_SECRET` = the `CLIENT_IP_HEADER_SECRET` value (mark it Sensitive; server-only, no `NEXT_PUBLIC_` prefix).
- [ ] Optional `NEXT_PUBLIC_SITE_URL=https://<your-frontend-domain>` (Open Graph image URLs; Vercel's production URL is used otherwise).
- [ ] Fill in the placeholders on `/impressum` and `/privacy` (`frontend/src/app/(public)/{impressum,privacy}/page.tsx`)
      and the GitHub link in `frontend/src/lib/brand.ts` before sharing the URL publicly.
- [ ] Deploy; note the URL (e.g. `https://<project>.vercel.app`).
- [ ] On the VM: `CORS_ALLOWED_ORIGINS=https://<project>.vercel.app` in `.env.production`, then `scripts/deploy.sh`.

## F. Smoke test the live system

- [ ] From your PC: `py -3.12 scripts\production_smoke_test.py --base-url https://<API_DOMAIN> --register`
      with `$env:SMOKE_EMAIL` / `$env:SMOKE_PASSWORD` set to a throw-away account. Expect `RESULT: PASS`.
- [ ] In the browser on the Vercel URL: register, upload a PDF, wait for "Completed",
      search, ask (503 "not configured" is expected without an OpenAI key), delete.
- [ ] Update the "Live demo" table in `README.md` with both URLs.

## G. OpenAI (optional, costs money)

- [ ] Create a project key with a monthly budget limit at platform.openai.com.
- [ ] Put it **only** in `/opt/dip/.env.production` (`OPENAI_API_KEY=`), never in Vercel or Git.
- [ ] `scripts/deploy.sh`; then the smoke test with `--with-llm --require-llm`.
- [ ] `py -3.12 scripts\check_ask_real.py --base-url https://<API_DOMAIN>`: the document-level and
      specific questions must be answered with citations, the off-topic one refused (exit code 0).
- [ ] Ask a question in the UI; the answer shows `[1]` chips that open the cited passage.
- [ ] Landing page "Try the demo": upload a PDF, ask 3 questions, the 4th opens "Create a free account to continue".

## H. GitHub Actions deploy (optional)

- [ ] On your PC: `ssh-keygen -t ed25519 -f dip_deploy -N ""`; append `dip_deploy.pub` to
      `/home/deploy/.ssh/authorized_keys` on the VM.
- [ ] `ssh-keyscan -t ed25519 <ip>` and compare the fingerprint with the one you saw on first SSH.
- [ ] Repository > Settings > Environments > `production`; secrets `ORACLE_HOST`,
      `ORACLE_USER` (`deploy`), `ORACLE_SSH_PRIVATE_KEY` (contents of `dip_deploy`),
      `ORACLE_SSH_KNOWN_HOSTS` (the keyscan line); variable `API_PUBLIC_URL=https://<API_DOMAIN>`.
      Consider "required reviewers" on the environment.
- [ ] The VM checkout needs a fetchable `origin` (public repo, or a read-only deploy key for the `deploy` user).
- [ ] Push to `final`/`main` or run "Deploy" manually; CI runs first, then the SSH deploy and the public health check.
- [ ] Delete the local `dip_deploy` private key copy once stored as a secret.

## I. Operations

- [ ] Cron (as `deploy`): `15 3 * * * cd /opt/dip && scripts/backup_postgres.sh --with-files >> /var/backups/dip/backup.log 2>&1`.
- [ ] Copy backups off the VM (`BACKUP_S3_BUCKET` or `scp`), and do one
      `restore_postgres.sh --into dip_restore_check` drill.
- [ ] External uptime check on `https://<API_DOMAIN>/health/ready`.
- [ ] Create an admin: `docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -m app.cli create-admin --email you@example.com`.
- [ ] Re-read Oracle's idle-reclamation policy; a demo VM with no traffic for 7 days can be reclaimed.
