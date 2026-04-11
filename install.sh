#!/bin/bash
set -e

echo "🔱 Installing caliclaw..."
echo ""

python3 -m venv .venv > /dev/null 2>&1
source .venv/bin/activate
pip install . > /dev/null 2>&1

# Build engine module (Cython compiled)
pip install -q cython > /dev/null 2>&1
python3 bin/build_engine.py > /dev/null 2>&1 || true

echo "✓ Installed. Ready to go."
echo ""
echo "  caliclaw start"
