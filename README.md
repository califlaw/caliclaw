<h1 align="center">🔱 caliclaw</h1>

<p align="center">
  Personal AI assistant in Telegram. Runs on your Claude subscription.
</p>

<p align="center">
  <a href="https://pypi.org/project/caliclaw/"><img src="https://img.shields.io/pypi/v/caliclaw.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/caliclaw/"><img src="https://img.shields.io/pypi/pyversions/caliclaw.svg" alt="Python"></a>
  <a href="https://github.com/califlaw/caliclaw/actions/workflows/ci.yml"><img src="https://github.com/califlaw/caliclaw/workflows/CI/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT"></a>
</p>

<!-- Drop a 20s Telegram session recording at docs/demo.gif and uncomment:
<p align="center">
  <img src="docs/demo.gif" alt="caliclaw demo" width="640">
</p>
-->

```
┌─ caliclaw ─────────────────────────────────────────────┐
│ you   > /spawn researcher "audit auth for bugs"        │
│ bot   🟢 Agent researcher spawned (ephemeral)          │
│                                                        │
│ you   > delegate: find bugs and report                 │
│ bot   [researcher] 3 issues in auth/session.py:        │
│         1. JWT not rotated on privilege change         │
│         2. Race condition in refresh token handler     │
│         3. Session ID in error logs                    │
│       Knowledge extracted → memory/. Agent killed 🔴   │
│                                                        │
│ you   > /cron "0 9 * * *" "morning health report"      │
│ bot   ⏰ Scheduled (runs daily 09:00)                  │
│                                                        │
│ you   > stop                                           │
│ bot   🛑 Stopped: 1 agent, 1 typing indicator          │
└────────────────────────────────────────────────────────┘
```

## Install

```bash
pip install caliclaw
caliclaw start
```

First run sets up everything. Pair your bot with `/pair <code>` in Telegram.

## What it does

- Chat with Claude through your Telegram bot — text, voice, files
- Spawn sub-agents (ephemeral / project / global) that work in parallel or pipelines
- Run scheduled tasks (`/cron`) and autonomous loops (`/loop`) until done
- Remember across sessions — persistent memory with knowledge extraction on kill
- Live on any server — systemd-installed `caliclaw immortal` survives reboots & crashes
- Sandbox by default — agents touch real dirs only with `/unleash ~/proj`
- Built-in skills: `code`, `shell`, `git`, `ops`, `debug`, `research`, `security`, `testing`, `web-access`, `code-review`, `incident-response`, `automation`, `self-evolve`

## Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) logged in
- Telegram bot token — [@BotFather](https://t.me/BotFather)

## Agents

```
/spawn researcher "audit auth module for bugs"
/spawn fixer "patch what researcher finds"
/cron "0 9 * * *" "morning server health report"
/loop "refactor the test suite"
stop
```

Parallel swarms, sequential pipelines, and autonomous loops are first-class.
Main agent spawns sub-agents itself — no manual intervention needed.

## Skills marketplace

13 default skills ship in the box. Browse & install more from
**[caliclaw-gym](https://califlaw.github.io/caliclaw-gym/)**:

```bash
caliclaw skills gym
caliclaw skills install stripe-webhooks
caliclaw skills publish my-skill
```

Zero backend — GitHub Issues for voting, Pages for browsing. Fork, PR, ship.

## Immortal mode

```bash
caliclaw immortal on     # systemd unit — survives reboots, crashes, OOM
caliclaw immortal        # status
caliclaw immortal off
```

## Config & updates

```bash
caliclaw reforge         # re-configure any single component
caliclaw update          # upgrade from PyPI in place
caliclaw model set opus  # switch default model
```

No YAML. No Docker. No env-var hunt. One `.env` file.

## Migrating from openclaw / nanoclaw / zeroclaw

```bash
caliclaw migrate ~/path/to/old-project
```

Auto-detects, imports soul + memory + skills + database.

## Docs

[Commands](docs/commands.md) · [Config](docs/configuration.md) ·
[Backup](docs/backup.md) · [Troubleshooting](docs/troubleshooting.md) ·
[Contributing](docs/contributing.md)

## License

MIT
