# Configuration

caliclaw is configured via `.env` file in the project root. Created automatically by `caliclaw init`.

## Required

```bash
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

Get from [@BotFather](https://t.me/BotFather) in Telegram.

## Security

```bash
# Whitelist of Telegram user IDs allowed to use the bot
# Auto-set after /pair command. If empty, bot ignores everyone.
TELEGRAM_ALLOWED_USERS=123456789
```

## Engine

```bash
# Default model for agents
CLAUDE_DEFAULT_MODEL=sonnet      # haiku | sonnet | opus

# Override engine binary (optional, for backend swapping)
CALICLAW_BACKEND=claude
```

## Limits

```bash
# Max concurrent agents (parallel agent processes)
MAX_CONCURRENT_AGENTS=3

# Max iterations per autonomous loop
MAX_LOOP_ITERATIONS=20

# Max loop duration (minutes)
MAX_LOOP_DURATION_MINUTES=120
```

## Usage Tracking

caliclaw tracks API usage as percentage of daily limit (not dollars).

```bash
# Pause: switch to cheaper models when usage exceeds %
USAGE_PAUSE_PERCENT=80

# Emergency: only haiku above this %
USAGE_EMERGENCY_PERCENT=90

# Stop: refuse all requests above this %
USAGE_STOP_PERCENT=95
```

## Heartbeats (scheduled background tasks)

```bash
HEARTBEAT_QUICK_CRON="*/5 * * * *"     # Every 5 minutes
HEARTBEAT_REVIEW_CRON="*/30 * * * *"   # Every 30 minutes
HEARTBEAT_MORNING_CRON="0 9 * * *"     # 9 AM daily
HEARTBEAT_DREAM_CRON="0 3 * * *"       # 3 AM daily
```

Cron expressions respect the `TZ` setting below.

## Auto-backup

```bash
BACKUP_ENABLED=true
BACKUP_INTERVAL_DAYS=7    # weekly (1=daily, 3=every 3 days, 7=weekly)
```

When enabled, caliclaw creates a backup tar.gz and sends it to your Telegram every N days. Files >50MB are automatically chunked.

## Voice transcription

```bash
WHISPER_CPP_PATH=/path/to/whisper-cli
```

Auto-built during `caliclaw init`.

## Dashboard

```bash
DASHBOARD_ENABLED=true
DASHBOARD_PORT=8080
```

Web UI for monitoring at `http://localhost:8080`. Health endpoint at `/health`.

## Timezone

```bash
TZ=Europe/Moscow
```

Used for cron expressions and timestamp display. Standard IANA timezone names.

## Logging

```bash
LOG_LEVEL=INFO    # DEBUG | INFO | WARNING | ERROR
```

Logs are written to `logs/caliclaw.log` with rotation: max 10MB per file, 5 backups (50MB total).

## Project paths (rarely changed)

```bash
PROJECT_ROOT=/path/to/caliclaw     # auto-detected
DATA_DIR=./data
WORKSPACE_DIR=./workspace
AGENTS_DIR=./agents
SKILLS_DIR=./skills
MEMORY_DIR=./memory
```

## Vault

```bash
VAULT_KEY_PATH=~/.caliclaw/vault.key
```

Master password is set via `caliclaw vault init`. Stored encrypted with Fernet (AES-128).
