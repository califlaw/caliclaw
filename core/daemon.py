"""caliclaw daemon entry point — used by pip-installed caliclaw-daemon script."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Fix macOS SSL
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Verbose console output")
    args = parser.parse_args()

    from core.config import get_settings
    from core.db import Database
    from core.agent import AgentPool
    from telegram.bot import CaliclawBot
    from automation.scheduler import TaskScheduler, HeartbeatManager

    # Import CaliclawApp from __main__.py
    main_py = Path(__file__).resolve().parent.parent / "__main__.py"
    if main_py.exists():
        # Source install — import directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("caliclaw_main", str(main_py))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app = mod.CaliclawApp()
    else:
        # Fallback: import from installed package
        from __main__ import CaliclawApp
        app = CaliclawApp()

    try:
        asyncio.run(app.start(debug=args.debug))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
