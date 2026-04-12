#!/bin/bash
# caliclaw daily backup script
# Add to cron: 0 4 * * * /path/to/caliclaw/scripts/backup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$SRC/backups"
DATE=$(date +%Y-%m-%d)
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

tar czf "$BACKUP_DIR/caliclaw-$DATE.tar.gz" \
    -C "$SRC" \
    data/ \
    memory/ \
    agents/ \
    workspace/conversations/ \
    skills/ \
    .env \
    2>/dev/null

find "$BACKUP_DIR" -name "caliclaw-*.tar.gz" -mtime +$KEEP_DAYS -delete

echo "Backup completed: caliclaw-$DATE.tar.gz"
