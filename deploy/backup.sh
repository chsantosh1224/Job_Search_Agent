#!/usr/bin/env bash
# Nightly database backup, keeping the last 14. Add to crontab (crontab -e):
#   30 3 * * * /home/ubuntu/job-search-agent/deploy/backup.sh >> /home/ubuntu/jobagent-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$HOME/jobagent-backups}"
mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/jobagent-$(date +%Y%m%d-%H%M).sql.gz"

docker compose -f deploy/docker-compose.prod.yml --env-file .env.prod \
  exec -T db pg_dump -U jobagent jobagent | gzip > "$file"
echo "Backup written: $file ($(du -h "$file" | cut -f1))"

ls -1t "$BACKUP_DIR"/jobagent-*.sql.gz | tail -n +15 | xargs -r rm --
