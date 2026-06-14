#!/usr/bin/env bash
# One-click launcher for macOS. Double-click in Finder, or run:  ./run.command [args]
# First run creates a local virtual environment and installs dependencies.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "Setting up (first run only)..."
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  source .venv/bin/activate
fi

python main.py "$@"
