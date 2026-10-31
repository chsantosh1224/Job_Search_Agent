#!/usr/bin/env bash
# Deploy or update: pull the latest code, rebuild, migrate, restart.
#   bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f deploy/docker-compose.prod.yml --env-file .env.prod)

if [ ! -f .env.prod ]; then
  echo ".env.prod is missing. Run: bash deploy/server-setup.sh" >&2
  exit 1
fi

echo "== Pull"
git pull --ff-only

echo "== Build"
"${COMPOSE[@]}" build

echo "== Start (migrations run first)"
"${COMPOSE[@]}" up -d --remove-orphans

echo "== Health"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8010/api/health >/dev/null; then
    echo "API is up on 127.0.0.1:8010"
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy. Logs:" >&2
"${COMPOSE[@]}" logs --tail 50 api migrate >&2
exit 1
