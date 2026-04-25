# caliclaw

Your own personal AI assistant. Any server. Any task. The claw way. 🔱

**The first and only personal AI assistant built for Claude.** No API key — just your subscription.

<p>
  <a href="https://pypi.org/project/caliclaw/"><img src="https://img.shields.io/pypi/v/caliclaw.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/caliclaw/"><img src="https://img.shields.io/pypi/pyversions/caliclaw.svg" alt="Python"></a>
  <a href="https://github.com/califlaw/caliclaw/actions/workflows/ci.yml"><img src="https://github.com/califlaw/caliclaw/workflows/CI/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT"></a>
</p>

## Why caliclaw

Other AI assistants (openclaw, etc.) require API keys, manual configuration, and don't support Claude at all. caliclaw is different:

- **Zero config** — `caliclaw start` does everything. Setup, dependencies, pairing — automatic
- **No API key** — runs on your Claude subscription. No tokens, no billing surprises
- **No TOS violations** — built on official tools, not reverse engineering
- **Agents that actually work** — spawn agents on the fly, run them in parallel (swarm), chain them (pipeline), or let them work autonomously (loop) until the task is done
- **They remember** — persistent memory across sessions. Your assistant learns who you are and how you work
- **They have a soul** — personality, rules, and behavior defined in simple markdown files, not buried in code
- **They know when to stop** — anti-hallucination layer, permission levels, human approval for dangerous actions. Type `stop` and everything halts instantly
- **Secure by default** — prompt injection protection, input filtering, and encrypted vault built in. No setup needed
- **They work while you sleep** — cron jobs, scheduled heartbeats, automated checks
- **Sandbox by default** — agents work in isolated workspace. Unleash them on real directories only when you need to: `/unleash ~/myproject`
- **Context follows you** — switch directories with `/unleash`, conversation context is preserved automatically. One assistant, infinite places to work

## caliclaw vs openclaw

| | caliclaw | openclaw |
|---|---|---|
| Claude support | **Yes** | No |
| API key required | **No** — subscription only | Yes |
| Setup time | **One command** | Manual config |
| Agents spawn agents | **Yes** | No |
| Agents work autonomously | **Yes** — loops until done | No |
| Agents extract knowledge on death | **Yes** | No |
| Prompt injection protection | **Built in** | Manual |
| Memory across sessions | **Yes** | Varies |
| Soul system | **Yes** | Yes |
| Scheduled tasks | **Built in** | Plugin |
| Voice messages | **Built in** | No |
| Open source | **Yes** | Yes |

## What you get

- **Telegram bot** — text, voice, photos, files. Streaming responses. Inline controls
- **Terminal chat** — same assistant, same soul, right in your shell. `caliclaw chat`
- **20+ commands** — agents, tasks, memory, skills, model switching, all from Telegram or CLI
- **Voice** — send voice messages, whisper-cpp transcribes them
- **Skills system** — enable/disable capabilities. Create your own in markdown. Browse community skills at [caliclaw-gym](https://github.com/califlaw/caliclaw-gym)
- **Encrypted vault** — store secrets your agents can use
- **Health dashboard** — web UI for monitoring activity and status
- **Migration** — coming from openclaw/nanoclaw/zeroclaw? One command imports everything

## Quick start

**From PyPI:**

```bash
pip install caliclaw
caliclaw start
```

**From source:**

```bash
git clone https://github.com/califlaw/caliclaw.git
cd caliclaw
source install.sh
caliclaw start
```

First run triggers setup automatically. Pair with your bot by sending `/pair <code>` in Telegram.

No YAML configs. No Docker. No environment variables to hunt down.

Need to change something later? Use `caliclaw reforge` to pick one component
(credentials, profile, soul, model, or skills) and re-configure it without
touching the rest.

To stay current: `caliclaw update` checks PyPI and upgrades in place.

## Terminal chat

Prefer the shell over Telegram? Same assistant, same soul, same memory:

```bash
caliclaw chat
```

Streaming responses, session history, slash commands. Works alongside the
Telegram bot — conversations stay in sync.

## Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot token from [@BotFather](https://t.me/BotFather) (optional if you only use `caliclaw chat`)

## How agents work

> When you kill an agent, it doesn't just die — it extracts everything it learned into memory. The next agent picks up where it left off. Knowledge never dies.

```
You send a message in Telegram (or type in caliclaw chat)
  -> caliclaw loads the agent's soul, memory, and skills
  -> Agent processes your request with full system access
  -> Response streams back to you in real-time
  -> Conversation saved, memory updated

Need parallel work?
  -> /spawn researcher "find all bugs in auth module"
  -> /spawn fixer "fix the bugs researcher found"
  -> They work independently, report back to you

Need autonomous work?
  -> /loop "refactor the entire test suite"
  -> Agent works in iterations until done or you say stop

Need scheduled work?
  -> /cron "0 9 * * *" "check server health and report"
  -> Runs every morning, sends you the result
```

## Skills marketplace — caliclaw-gym 🏋️

caliclaw ships with **14 default skills** — a professional dev kit, not a newbie bundle:

| Core | Unique | Meta |
|---|---|---|
| `code` read first, minimal diffs | `incident-response` production fires | `self-evolve` agent creates new skills |
| `shell` bash mastery | `code-review` review like a senior | |
| `git` atomic commits, recovery | `automation` glue scripts, webhooks, cron | |
| `ops` ssh, systemd, deploy | `browser` headless navigation & scraping | |
| `debug` read errors, isolate | | |
| `research` authoritative sources | | |
| `security` secrets, OWASP | | |
| `testing` pyramid, regression | | |
| `web-access` search + fetch | | |

Need more? Browse community-built skills at **<https://califlaw.github.io/caliclaw-gym/>**:

```bash
caliclaw skills gym                     # browse all community skills
caliclaw skills install stripe-webhooks # install one
caliclaw skills publish my-skill        # share yours with the community
```

Built your own skill and want to share it? Fork [caliclaw-gym](https://github.com/califlaw/caliclaw-gym), add `skills/<name>/SKILL.md`, open a PR. After merge it gets a voting issue — community upvotes with 👍 and it ranks by stars. See the [contributing guide](https://github.com/califlaw/caliclaw-gym/blob/main/CONTRIBUTING.md).

No API, no backend, no auth — just GitHub Issues for voting and GitHub Pages for the browser. Zero infrastructure, fully community-owned.

## Choosing the model

By default caliclaw uses `sonnet` — balanced between speed and reasoning. Change it anytime:

```bash
caliclaw model                    # show current default + options
caliclaw model set opus           # switch to opus (more reasoning, heavier)
caliclaw model set haiku          # switch to haiku (fast, cheap)
```

The CLI persists your choice in `.env` and auto-restarts the bot if it's running. You can also switch runtime-only via `/model` in Telegram.

## Different LLM providers

Don't want to pay Anthropic directly? Route every `claude -p` call through OpenRouter or your own proxy:

```bash
caliclaw llm                                    # show current provider
caliclaw llm openrouter sk-or-v1-abc...         # route through OpenRouter (Claude models)
caliclaw llm custom http://localhost:3456       # claude-code-router / LiteLLM / your own
caliclaw llm anthropic                          # reset to Claude direct
```

caliclaw exports `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` into every Claude Code subprocess (main agent, image-describer, swarm). OpenRouter's `/v1/messages` endpoint is Anthropic-compatible but only serves Claude models — for GPT/Gemini/Llama, point at a translating proxy like [claude-code-router](https://github.com/musistudio/claude-code-router) or [LiteLLM](https://github.com/BerriAI/litellm) and use `caliclaw llm custom`.

## Migration

Coming from another *claw project?

```bash
caliclaw migrate ~/path/to/old-project
```

Auto-detects project type. Migrates soul, memory, skills, database. Supports openclaw, nanoclaw, zeroclaw.

## Deploy

```bash
ssh user@vps
pip install caliclaw
caliclaw start
```

Auto-reconnects on network drops. Auto-restarts on failure. Graceful shutdown with watchdog.

### Make it immortal ☠

Survive reboots, crashes, OOM kills — caliclaw comes back every time:

```bash
caliclaw immortal on       # installs systemd unit, enables, starts
caliclaw immortal          # status — alive/dead, immortal/mortal
caliclaw immortal off      # break the seal
```

During first-run `caliclaw init`, the "Keep caliclaw always running" option does the same thing. You can toggle it later anytime with `caliclaw immortal on/off` — no need to re-run init.

Status output looks like:

```
  ☠  IMMORTAL  survives reboots and crashes
  ♥  Alive right now
```

## Documentation

Full docs in [docs/](docs/):

- [Commands reference](docs/commands.md) — every CLI and Telegram command
- [Configuration](docs/configuration.md) — all `.env` settings
- [Backup & recovery](docs/backup.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](docs/contributing.md) — development guide

## License

MIT
