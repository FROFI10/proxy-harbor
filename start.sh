#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PYTHONUTF8=1
if [[ -x .venv/Scripts/python.exe ]]; then
  PYTHON=.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
else
  python3 -m venv .venv
  PYTHON=.venv/bin/python
  if [[ -f requirements-lock.txt ]]; then
    "$PYTHON" -m pip install -r requirements-lock.txt
  else
    "$PYTHON" -m pip install -r requirements.txt
  fi
fi
exec "$PYTHON" run.py "$@"
