#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 22.04 / 24.04 server (arm64 or amd64), e.g. an
# OCI Ampere A1 VM. Run as root:  sudo scripts/setup_server.sh [options]
#
#   --deploy-user <name>   user that owns /opt/dip and runs deploys (default: deploy)
#   --ssh-key-from <user>  copy this user's authorized_keys to the deploy user
#                          (default: $SUDO_USER, usually "ubuntu")
#   --swap-size <size>     swap file size if the server has no swap (default: 4G)
#   --skip-docker | --skip-firewall | --skip-swap | --skip-upgrades
#
# Safe to re-run: every step checks the current state first. It does NOT change the SSH
# daemon configuration and never removes packages, users, rules or data.
# Firewall: opens 22, 80 and 443/tcp. Oracle's Ubuntu images ship iptables rules
# (/etc/iptables/rules.v4) that reject everything except SSH; this script inserts ACCEPT
# rules for 80/443 before that REJECT and saves them. Elsewhere it uses ufw. The OCI
# security list / NSG must allow the same ports (done in the OCI console).
set -euo pipefail

DEPLOY_USER="deploy"
KEY_FROM="${SUDO_USER:-}"
SWAP_SIZE="4G"
DO_DOCKER=1
DO_FIREWALL=1
DO_SWAP=1
DO_UPGRADES=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy-user) DEPLOY_USER="${2:-}"; shift ;;
    --ssh-key-from) KEY_FROM="${2:-}"; shift ;;
    --swap-size) SWAP_SIZE="${2:-}"; shift ;;
    --skip-docker) DO_DOCKER=0 ;;
    --skip-firewall) DO_FIREWALL=0 ;;
    --skip-swap) DO_SWAP=0 ;;
    --skip-upgrades) DO_UPGRADES=0 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

log() { printf '[setup] %s\n' "$*"; }
die() { printf '[setup] ERROR: %s\n' "$*" >&2; exit 1; }
has_systemd() { [[ -d /run/systemd/system ]]; }

[[ "$(id -u)" -eq 0 ]] || die "run as root (sudo)"
[[ "$DEPLOY_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "invalid --deploy-user"
[[ "$SWAP_SIZE" =~ ^[0-9]+[MG]$ ]] || die "--swap-size must look like 4G or 2048M"
# shellcheck source=/dev/null
. /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "this script supports Ubuntu only (found ${ID:-unknown})"
case "${VERSION_ID:-}" in
  22.04|24.04) ;;
  *) log "warning: tested for Ubuntu 22.04/24.04, found ${VERSION_ID:-unknown}" ;;
esac
log "Ubuntu ${VERSION_ID} on $(dpkg --print-architecture)"

export DEBIAN_FRONTEND=noninteractive
log "installing base packages"
apt-get update -q
apt-get install -y -q --no-install-recommends ca-certificates curl git gnupg python3 \
  unattended-upgrades util-linux >/dev/null

if [[ "$DO_DOCKER" -eq 1 ]]; then
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    log "Docker Engine and the compose plugin are already installed"
  else
    log "installing Docker Engine from download.docker.com"
    install -m 0755 -d /etc/apt/keyrings
    if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
      chmod a+r /etc/apt/keyrings/docker.asc
    fi
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
      >/etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  fi
  if [[ ! -f /etc/docker/daemon.json ]]; then
    log "configuring Docker log rotation"
    mkdir -p /etc/docker
    printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "10m", "max-file": "5"}\n}\n' >/etc/docker/daemon.json
  fi
  if has_systemd; then
    systemctl enable --now docker >/dev/null
    systemctl restart docker
  else
    log "no systemd here; start dockerd yourself"
  fi
fi

if [[ "$DO_FIREWALL" -eq 1 ]]; then
  if [[ -f /etc/iptables/rules.v4 ]] && grep -q 'REJECT' /etc/iptables/rules.v4; then
    log "Oracle-style iptables rules found; allowing 80 and 443 before the REJECT rule"
    for port in 80 443; do
      if ! iptables -C INPUT -p tcp -m state --state NEW -m tcp --dport "$port" -j ACCEPT >/dev/null 2>&1; then
        line="$(iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" {print $1; exit}')"
        iptables -I INPUT "${line:-1}" -p tcp -m state --state NEW -m tcp --dport "$port" -j ACCEPT
      fi
    done
    if command -v netfilter-persistent >/dev/null; then
      netfilter-persistent save >/dev/null
    else
      iptables-save >/etc/iptables/rules.v4
    fi
  else
    log "configuring ufw (22, 80, 443/tcp)"
    apt-get install -y -q ufw >/dev/null
    ufw allow 22/tcp >/dev/null
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
  fi
  log "note: Docker-published ports use Docker's own iptables chains (they bypass ufw); only Caddy publishes ports (80/443)"
fi

if [[ "$DO_SWAP" -eq 1 ]]; then
  if [[ -n "$(swapon --show --noheadings 2>/dev/null)" ]]; then
    log "swap already active"
  elif [[ -f /swapfile ]]; then
    log "/swapfile exists but is not active; enabling it"
    swapon /swapfile
  else
    log "creating a ${SWAP_SIZE} swap file"
    fallocate -l "$SWAP_SIZE" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
  fi
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
  printf 'vm.swappiness=10\n' >/etc/sysctl.d/90-dip-swap.conf
  sysctl -q -p /etc/sysctl.d/90-dip-swap.conf || true
fi

if [[ "$DO_UPGRADES" -eq 1 ]]; then
  log "enabling unattended security upgrades"
  printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
    >/etc/apt/apt.conf.d/20auto-upgrades
fi

if id "$DEPLOY_USER" >/dev/null 2>&1; then
  log "user $DEPLOY_USER exists"
else
  log "creating user $DEPLOY_USER"
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
fi
if getent group docker >/dev/null; then usermod -aG docker "$DEPLOY_USER"; fi
home="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$home/.ssh"
if [[ ! -s "$home/.ssh/authorized_keys" && -n "$KEY_FROM" && "$KEY_FROM" != "$DEPLOY_USER" ]]; then
  src="$(getent passwd "$KEY_FROM" | cut -d: -f6)/.ssh/authorized_keys"
  if [[ -s "$src" ]]; then
    log "copying authorized_keys from $KEY_FROM"
    install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$src" "$home/.ssh/authorized_keys"
  fi
fi
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/dip
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /var/backups/dip

log "done. Next (as $DEPLOY_USER): git clone <repo> /opt/dip && cd /opt/dip &&"
log "  cp .env.production.example .env.production && chmod 600 .env.production && scripts/deploy.sh"
