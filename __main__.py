"""caliclaw daemon — entry point for source installs."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

from core.app import CaliclawApp


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = CaliclawApp()
    try:
        asyncio.run(app.start(debug=args.debug))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
