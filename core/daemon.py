"""caliclaw daemon — entry point for pip installs (caliclaw-daemon script)."""
from __future__ import annotations

import asyncio
import os
import sys

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    from core.app import CaliclawApp
    app = CaliclawApp()
    try:
        asyncio.run(app.start(debug=args.debug))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
