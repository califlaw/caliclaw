# Contributing

Want to hack on caliclaw? Here's how.

## Development setup

```bash
git clone https://github.com/califlaw/caliclaw.git
cd caliclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest pytest-asyncio pytest-cov
```

`-e` installs in editable mode so changes are picked up immediately.

## Project structure

```
caliclaw/
├── core/              # Agent, orchestrator, queue, db, config, protocols
├── telegram/          # Aiogram bot + handlers package
│   ├── bot.py        # CaliclawBot class
│   └── handlers/     # 8 modules (system, session, agents, tasks, ...)
├── intelligence/      # Memory, compaction
├── automation/        # Scheduler, heartbeats, triggers
├── security/          # Permissions, approval, vault
├── safety/            # Anti-hallucination, input filter
├── monitoring/        # Tracking, dashboard, health check
├── media/             # Whisper transcription
├── cli/               # CLI entry, commands, TUI, UI helpers, migrate
│   ├── caliclaw_cli.py    # Main dispatcher
│   ├── ui.py              # Rich CLI helpers
│   ├── tui.py             # Terminal chat
│   ├── migrate.py         # Migration CLI
│   └── commands/          # Command implementations
├── core/migrators/    # openclaw, nanoclaw, zeroclaw migrators
├── bin/               # Engine wrapper (caliclaw-engine)
├── agents/            # Default soul files
├── skills/            # Built-in skills
├── tests/             # 190 tests
├── docs/              # You're here
└── __main__.py        # Composition root + entry point
```

## Architecture

caliclaw uses **dependency injection** via constructor params. The composition root is `CaliclawApp.__init__` in `__main__.py` — it creates `Database`, `AgentPool`, `CaliclawBot` and wires them together.

Core dependencies use **Protocols** (`core/protocols.py`):
- `StorageProtocol` — DB contract
- `AgentRunnerProtocol` — agent execution contract
- `MemoryProtocol` — memory backend contract

This means tests can substitute implementations without monkey-patching.

## Running tests

```bash
python3 -m pytest tests/                       # all tests
python3 -m pytest tests/test_queue.py -v       # specific file
python3 -m pytest -k "race" --tb=short         # filter by name
python3 -m pytest --cov=core --cov-report=term # with coverage
```

Tests are organized:
- **Unit** — most tests, no external dependencies
- **Integration** — `tests/test_integration.py` uses mock claude binary
- **Real Claude** — marked with `@requires_claude`, skipped if `claude` not installed

## Adding a new Telegram command

1. Decide which handler module fits (`telegram/handlers/`)
2. Add the command:
```python
@router.message(Command("mycommand"))
async def cmd_mycommand(message: Message) -> None:
    if not bot._check_allowed(message):
        return
    await message.answer("Hello!")
```
3. Register in `BotCommand` list in `telegram/bot.py:start()`
4. Add to `/help` text in `telegram/handlers/system.py`

## Adding a new CLI command

1. Add function in `cli/caliclaw_cli.py`:
```python
def cmd_mything(args: argparse.Namespace) -> None:
    from cli.ui import ui
    ui.ok("Done!")
```
2. Register subparser in `main()`:
```python
sub.add_parser("mything", help="Do my thing")
```
3. Add to dispatch dict (`sync_map` or `async_map`)
4. Add to help epilog

## Adding a new migrator

1. Create file in `core/migrators/`:
```python
from core.migrate import BaseMigrator, register_migrator

@register_migrator
class MyMigrator(BaseMigrator):
    source_name = "myclaw"
    source_description = "Migrate from myclaw"

    def validate_source(self) -> List[str]: ...
    def discover_components(self) -> Dict[MigrationComponent, bool]: ...
    def plan(self, components, strategy) -> MigrationPlan: ...
    def _migrate_db_item(self, item, strategy) -> None: ...
```
2. The `@register_migrator` decorator auto-registers it.
3. Auto-discovery picks it up via `core/migrators/__init__.py`.

## Code style

- **Type hints** required for new code
- **No `except Exception`** — use specific exceptions
- **No `print()`** in core code — use `logger`
- **Async-first** for I/O (aiosqlite, aiogram, asyncio)
- **DI** — accept dependencies via constructor, don't create them inside

## Tests required

All new features need tests. We're at 190 tests passing — keep it that way.

## CI

GitHub Actions runs on every push:
- Tests on Python 3.10, 3.11, 3.12
- Coverage report
- Check for `except Exception` blocks (fails if found)

See `.github/workflows/ci.yml`.

## Releasing

1. Bump version in `pyproject.toml`
2. Tag: `git tag v0.2.0 && git push --tags`
3. Create GitHub Release
4. PyPI publish workflow runs automatically (Trusted Publisher OIDC)
