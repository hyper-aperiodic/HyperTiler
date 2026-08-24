#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PYTHON=$(command -v python3.14 || command -v python3)
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo "Done. Run ./run.sh to launch HyperTiler."
