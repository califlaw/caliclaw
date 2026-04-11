# Security

## Permission levels

Every action has one of three levels:

### auto
Executed without asking. Read-only operations:
- `ls`, `cat`, `grep`, `ps`, `df`, `free`
- `git status`, `git diff`, `git log`
- `systemctl status`

### confirm_tg
Requires Telegram confirmation (tap a button):
- `Write`, `Edit` files
- `git commit`, `git push`
- `pip install`, `apt install`
- `docker start/stop`
- Creating cron tasks

### confirm_terminal
Requires entering a 4-character code in Telegram:
- `rm -rf`
- `git push --force`, `git reset --hard`
- `systemctl restart`
- `iptables`, firewall changes
- `reboot`, `shutdown`
- Production deploys

## Approval flow

1. Agent wants to run a dangerous command
2. caliclaw sends a Telegram message with action details
3. For `confirm_tg`: tap [Approve] or [Deny]
4. For `confirm_terminal`: type `/approve ab12` (4-char code)
5. Timeout after 5 minutes → action cancelled

All approvals are logged in the database.

## Sender allowlist

Only listed Telegram user IDs can interact with the bot. Set in `.env`:

```
TELEGRAM_ALLOWED_USERS=123456789
```

Empty = allow all (development only).

## Vault

Encrypted credential storage using AES-256:

```bash
caliclaw vault init    # Set master password
caliclaw vault set     # Store a secret
caliclaw vault list    # List stored secrets
```

Secrets are encrypted at rest. Agents access them through a controlled interface, never through environment variables.

## Anti-hallucination

### Verify before act
Agents must check before assuming:
- File exists? Read it first
- Command exists? `which` it first
- Service running? `systemctl status` first

### Ground truth assertions
Dangerous patterns are blocked automatically:
- `rm -rf /` → blocked
- `curl | bash` → blocked
- `DROP TABLE` → blocked
- `chmod 777` → warning

### Contradiction detection
If an agent says "nginx is running" then later "nginx is not installed", caliclaw flags the contradiction.

### Confidence scoring
Agents rate their confidence before actions:
- HIGH (90%+): execute
- MEDIUM (60-90%): execute but notify user
- LOW (<60%): stop and ask
