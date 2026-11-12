#!/usr/bin/env bash
# Outcome-First Controller Runner
set -euo pipefail

SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
DB_ARG=""
if [ -n "${CONTROLLER_DB:-}" ]; then
    DB_ARG="--db $CONTROLLER_DB"
fi

# Find python interpreter
if [ -f "./.venv/bin/python3" ]; then
    PY="./.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    PY="python"
fi

exec "$PY" -m controller.main --url "$SIM_URL" $DB_ARG
