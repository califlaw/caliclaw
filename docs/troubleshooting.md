# Troubleshooting

Common issues and how to fix them.

## Bot not responding

**Symptoms:** Send a message in Telegram, no reply or "No response."

**Diagnosis:**
```bash
caliclaw status         # is bot running?
caliclaw doctor         # all components OK?
caliclaw logs 50        # any errors?
```

**Common causes:**

1. **Stale Claude session** — bot has invalid `claude_session_id` from before a config change. Fix:
   ```bash
   caliclaw restart
   ```
   If still broken, manually clear:
   ```python
   sqlite3 data/caliclaw.db "UPDATE sessions SET claude_session_id = NULL"
   ```

2. **Telegram conflict** — two bot processes running.
   ```bash
   pgrep -af caliclaw
   ```
   Kill duplicates, then `caliclaw start`.

3. **Rate limit hit** — Claude returns empty. Check `caliclaw status` for usage %.

4. **Working directory inaccessible** — after `/unleash` to a deleted directory.
   ```
   /unleash revoke
   ```
   Returns to sandbox workspace.

## Bot starts but immediately dies

**Diagnosis:**
```bash
caliclaw start --debug    # run in foreground, see errors
```

**Common causes:**

1. **Invalid Telegram token** — `TokenValidationError` in logs.
   - Get a fresh token from [@BotFather](https://t.me/BotFather)
   - Update `.env`: `TELEGRAM_BOT_TOKEN=...`

2. **Port 8080 in use** — Dashboard can't bind.
   ```bash
   fuser 8080/tcp     # find what's using it
   # Either kill the other process or disable dashboard:
   echo "DASHBOARD_ENABLED=false" >> .env
   ```

3. **Database locked** — another process holds SQLite lock.
   ```bash
   pkill -9 caliclaw    # nuke everything
   rm data/caliclaw.db-shm data/caliclaw.db-wal
   caliclaw start
   ```

## "TelegramConflictError"

Two processes polling the same bot. Fix:
```bash
pkill -9 -f "python3.*__main__"
rm data/caliclaw.pid
caliclaw start
```

## Pairing not working

**Symptoms:** `/pair ABC123` does nothing.

**Causes:**

1. **Code expired** — pairing codes have 15-minute TTL. Generate new one:
   ```bash
   caliclaw init    # or just delete data/pairing_code.txt and restart
   ```

2. **Already paired** — bot only pairs once. To re-pair:
   ```bash
   # Remove the user from .env
   sed -i '/TELEGRAM_ALLOWED_USERS/d' .env
   caliclaw restart
   ```

## Voice messages not transcribed

**Symptoms:** Send voice message, get "Could not transcribe audio."

**Diagnosis:**
```bash
caliclaw doctor    # check whisper-cpp + model
```

**Fix:** Re-run init to rebuild whisper:
```bash
rm -rf vendor/whisper.cpp models/ggml-base.bin
caliclaw init
```

## Backup file too large for Telegram

caliclaw auto-chunks backups >50MB. If you see "Backup too large":

1. Bot will send multiple `.part*` files
2. Download all of them
3. Concatenate: `cat *.part* > backup.tar.gz`
4. Restore: `caliclaw comeback backup.tar.gz`

To shrink backups, run `/squeeze` to compress old conversations or `caliclaw memory flush` for a fresh start.

## Lost master password (vault)

**Symptoms:** Can't unlock vault, secrets are gone.

**Bad news:** There is no recovery. Vault uses PBKDF2 with the master password — without it, secrets are permanently encrypted.

**What to do:**
```bash
rm vault/secrets.enc ~/.caliclaw/vault.key
caliclaw vault init    # start fresh
```

Re-add secrets manually via `caliclaw vault <key> <value>`.

## Agent stuck in loop

If `/loop` runs forever:

```
stop
```

Send "stop" or "стоп" in Telegram. All running agents and loops are killed instantly. Or:
```bash
caliclaw restart
```

## Disk filling up

**Logs grow:** caliclaw rotates logs at 10MB, keeps 5 backups. Max 50MB.

**Backups grow:** keeps last 10 backups, older deleted automatically.

**workspace/media:** voice messages, photos. Clean manually:
```bash
rm -rf workspace/media/*
```

## Migration from openclaw fails

```bash
caliclaw migrate ~/old-project --dry-run    # preview
```

Check the output for errors. Common fixes:

- **"Not a directory"** — wrong path
- **"Cannot parse memories.json"** — old format. Edit the JSON manually
- **"Table not found"** — different DB schema. Migration will skip those tables and continue

## Where to look for help

- Logs: `caliclaw logs`
- Status: `caliclaw status`
- Health: `caliclaw doctor`
- DB: `sqlite3 data/caliclaw.db` (read-only inspection)
