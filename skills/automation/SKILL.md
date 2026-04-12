---
name: automation
description: Scripts, webhooks, cron, glue code
audience: builder
---

## Automation

Glue code that makes things work together. Indie hacker superpower.

### When to automate

- **3 times rule**: did it manually 3 times? Automate it.
- Tasks done weekly+ — even small ones add up
- Tasks that interrupt deep work — automate to remove the interruption
- Tasks where humans make mistakes — automation is more reliable

### When NOT to automate

- One-off tasks (write a one-liner instead)
- Things that change every time (no pattern to capture)
- Where the automation is harder to maintain than the task

### Tools

**Cron / systemd timers**: scheduled tasks
```bash
# Run every 6 hours
0 */6 * * * /path/to/script.sh
```

**GitHub Actions**: CI, releases, scheduled workflows
**Webhooks**: react to external events (Stripe, GitHub, Telegram)
**File watchers**: `inotifywait`, `fswatch` for "do X when Y changes"
**HTTP polling**: when no webhook available — but back off exponentially

### Write good automation

- **Idempotent**: running twice gives same result as running once
- **Logged**: every run produces a log entry
- **Error notifications**: if it breaks, you find out (Telegram/email/Slack)
- **Dry-run mode**: `--dry-run` flag to see what would happen
- **Self-healing**: retries, timeouts, fallbacks

### Common patterns

**Event → action**:
```
Stripe webhook → save to DB → notify Telegram
```

**Schedule → check → notify**:
```
Every 5 min → check disk space → alert if >85%
```

**Source → transform → destination**:
```
RSS feed → filter keywords → save to Notion
```

### Quick wins

- **Backup automation**: cron + tar + remote upload
- **Deploy on push**: GitHub Action that SSH + pulls + restarts
- **Status notifications**: cron + curl + Telegram bot
- **Log aggregation**: ship logs to one place
- **Cert renewal**: certbot + hook to restart nginx

### Don't

- Automate without monitoring (silent failure is worst failure)
- Hardcode secrets in scripts
- Schedule everything at `0 * * * *` (thundering herd)
- Skip error handling because "it'll work"
- Forget to document what each automation does
