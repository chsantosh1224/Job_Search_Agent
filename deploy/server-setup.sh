#!/usr/bin/env bash
# First-time setup on the Lightsail server. Safe to re-run: every step checks before acting.
#   bash deploy/server-setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Docker"
if ! command -v docker >/dev/null; then
  echo "Docker is not installed. Install it first: https://docs.docker.com/engine/install/" >&2
  exit 1
fi
docker compose version

echo "== Swap (a safety net for the 2 GB instance)"
if swapon --show | grep -q .; then
  swapon --show
else
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo "2 GB swap file created"
fi

echo "== .env.prod"
if [ -f .env.prod ]; then
  echo ".env.prod already exists; leaving it unchanged"
else
  cp deploy/env.prod.example .env.prod
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env.prod
  sed -i "s|^JWT_SECRET=.*|JWT_SECRET='$(openssl rand -base64 48 | tr -d '\n')'|" .env.prod
  chmod 600 .env.prod
  echo "Created .env.prod with generated database password and session secret."
  echo "Edit it now to add OPENROUTER_API_KEY (and later RESEND_API_KEY, DIGEST_TO)."
fi

mkdir -p data
echo
echo "Next: edit .env.prod, then run: bash deploy/deploy.sh"
