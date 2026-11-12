#!/usr/bin/env bash
# Crash recovery demonstration test
set -euo pipefail

echo "=================================================================="
echo "Starting Crash Recovery Test (C13)"
echo "=================================================================="

RUN_DIR="runs/crash_test"
DB_PATH="controller_crash_test.db"
rm -rf "$RUN_DIR" "$DB_PATH"*

# 1. Start simulator server in background
echo "1. Starting simulator server on public_01_dev..."
PYTHONPATH=. ./.venv/bin/python3 -m sim serve --scenario scenarios/public_01_dev.yaml --run-dir "$RUN_DIR" > /tmp/sim_crash.log 2>&1 &
SIM_PID=$!

trap "kill -9 $SIM_PID 2>/dev/null || true" EXIT

# Wait for simulator to be ready
echo "Waiting for simulator..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8700/health > /dev/null; then
        echo "Simulator is ready!"
        break
    fi
    sleep 0.5
done

# 2. Start controller in background
echo "2. Starting controller loop..."
CONTROLLER_DB="$DB_PATH" ./run.sh http://127.0.0.1:8700 > /tmp/controller_crash.log 2>&1 &
CTRL_PID=$!

# Wait until controller has completed setup and made initial progress
echo "Waiting for initial controller checkpoint..."
for i in {1..30}; do
    if PYTHONPATH=. ./.venv/bin/python3 -c "
from controller.db import Database
db = Database('$DB_PATH')
cp = db.load_checkpoint()
assert cp is not None and cp.sim_minute >= 1440
" 2>/dev/null; then
        echo "Checkpoint detected on running controller!"
        break
    fi
    sleep 0.1
done

# 3. Simulate sudden crash: send SIGKILL (-9)
echo "3. Sending SIGKILL to controller (PID: $CTRL_PID)..."
kill -9 "$CTRL_PID" 2>/dev/null || true
wait "$CTRL_PID" 2>/dev/null || true
echo "Controller process killed mid-run."

# Verify checkpoint exists in database
echo "4. Checking SQLite checkpoint before restart..."
PYTHONPATH=. ./.venv/bin/python3 -c "
from controller.db import Database
db = Database('$DB_PATH')
cp = db.load_checkpoint()
print('Persisted Checkpoint before restart:', cp)
assert cp is not None
assert cp.last_event_id > 0
assert cp.sim_minute >= 1440
"

# 4. Restart controller against the same world
echo "5. Restarting controller to resume simulation..."
CONTROLLER_DB="$DB_PATH" ./run.sh http://127.0.0.1:8700 >> /tmp/controller_crash.log 2>&1

echo "6. Checking final checkpoint after completion..."
PYTHONPATH=. ./.venv/bin/python3 -c "
from controller.db import Database
db = Database('$DB_PATH')
cp = db.load_checkpoint()
print('Final Checkpoint:', cp)
assert cp.sim_minute == 11520
print('Crash recovery verification PASSED successfully!')
"

echo "=================================================================="
echo "Crash Recovery Test Complete!"
echo "=================================================================="
