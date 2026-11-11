#!/usr/bin/env bash
# ==============================================================================
# Renvue - Render Background Worker Entrypoint
# Runs Taskiq scheduler in the background and Taskiq worker in the foreground.
# Uses --workers 1 to keep RAM footprint safely under Render Starter's 512MB limit.
# ==============================================================================

set -euo pipefail

# Ensure src is in python path
export PYTHONPATH="${PYTHONPATH:-src}"

echo "[STARTUP] Starting Taskiq Scheduler in background..."
uv run taskiq scheduler -d src background.worker:scheduler &
SCHEDULER_PID=$!

# Trap signals for graceful shutdown of background scheduler
cleanup() {
    echo "[SHUTDOWN] Terminating Taskiq scheduler (PID: $SCHEDULER_PID)..."
    kill -TERM "$SCHEDULER_PID" 2>/dev/null || true
    wait "$SCHEDULER_PID" 2>/dev/null || true
}
trap cleanup SIGINT SIGTERM EXIT

echo "[STARTUP] Starting Taskiq Worker in foreground (--workers 1)..."
exec uv run taskiq worker -d src background.worker:broker --workers 1
