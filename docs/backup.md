# Backup & Recovery

caliclaw has built-in backup with auto-delivery to Telegram.

## What's backed up

- `data/` — SQLite DB, sessions, history
- `memory/` — Long-term memory (markdown files)
- `agents/` — Soul files (personality, identity)
- `skills/` — Skill definitions
- `.env` — Configuration
- `vault/` — Encrypted secrets (if exists)

**Not backed up:** `logs/`, `workspace/media/`, `vendor/`, compiled artifacts.

## Manual backup

```bash
caliclaw backup           # create backup now
caliclaw backup list      # list all backups
```

Backups are stored in `backups/caliclaw-<timestamp>.tar.gz`. The 10 most recent are kept; older ones are deleted automatically.

## Restore (comeback)

```bash
caliclaw comeback                    # restore from latest
caliclaw comeback file.tar.gz        # restore from specific
caliclaw comeback ~/backups/x.tar.gz # absolute path
```

Before restoring, caliclaw creates a **safety backup** of your current state labeled `pre-restore`. If something goes wrong, you can comeback from that.

After restore, run `caliclaw restart` to apply the restored state.

## Auto-backup to Telegram

Enabled during `caliclaw init` (Step 5 — Options) or via `.env`:

```bash
BACKUP_ENABLED=true
BACKUP_INTERVAL_DAYS=7    # weekly
```

Every N days, caliclaw:
1. Creates a backup
2. Sends the file to your Telegram
3. Cleans up old backups (keeps last 10)

### Large backups (>50MB)

Telegram has a 50MB file limit. caliclaw automatically:
1. Splits the backup into 45MB chunks
2. Sends each chunk as a separate file
3. Includes restore instructions in the first message

To restore from chunks:

```bash
# Download all .part* files from Telegram
cat caliclaw-2026-04-10.tar.gz.part* > caliclaw-2026-04-10.tar.gz
caliclaw comeback caliclaw-2026-04-10.tar.gz
```

## Disaster recovery

If your machine dies:

1. Install caliclaw on new machine
2. Run `caliclaw init` (or `caliclaw start` which auto-runs init)
3. Download the latest backup from your Telegram chat
4. Run `caliclaw comeback path/to/backup.tar.gz`
5. Run `caliclaw restart`

Your bot is back with all memory, agents, and history.

## Backup size estimates

| Time using caliclaw | Approx backup size |
|---|---|
| 1 month | 2-5 MB |
| 1 year | 15-30 MB |
| 3 years | 80-150 MB |

Most users will never hit the 50MB Telegram limit. Heavy users (long sessions, many agents) might need chunking after a year.
