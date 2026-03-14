#!/bin/bash
# run_autonomous.sh — Launch the autonomous build loop
#
# Usage:
#   chmod +x run_autonomous.sh
#   ./run_autonomous.sh
#
# Options:
#   MAX_ITERATIONS=50 ./run_autonomous.sh   # limit iterations (default: 100)
#   COOLDOWN=10 ./run_autonomous.sh         # seconds between iterations (default: 5)
#   TIMEOUT=1200 ./run_autonomous.sh        # seconds before killing a frozen Claude (default: 900)

set -euo pipefail

MAX_ITERATIONS="${MAX_ITERATIONS:-100}"
COOLDOWN="${COOLDOWN:-5}"
TIMEOUT="${TIMEOUT:-900}"  # 15 min max per iteration
ITERATION=0
LOG_FILE="build_log_$(date +%Y%m%d_%H%M%S).txt"
HEARTBEAT_PID=""

# ── helpers ──────────────────────────────────────────────────────────────────

start_heartbeat() {
    local start=$SECONDS
    while true; do
        sleep 30
        local elapsed=$(( SECONDS - start ))
        local mins=$(( elapsed / 60 ))
        local secs=$(( elapsed % 60 ))
        echo "  ⏳ Claude still running... ${mins}m${secs}s elapsed (timeout at ${TIMEOUT}s)" >&2
    done &
    HEARTBEAT_PID=$!
}

stop_heartbeat() {
    if [ -n "$HEARTBEAT_PID" ]; then
        kill "$HEARTBEAT_PID" 2>/dev/null || true
        HEARTBEAT_PID=""
    fi
}

next_task() {
    grep -m1 '\- \[ \]' TASK_LOG.md 2>/dev/null | sed 's/.*\[ \] //' | cut -c1-80 || echo "(unknown)"
}

# ── main loop ─────────────────────────────────────────────────────────────────

echo "🚀 Starting autonomous build loop"
echo "   Max iterations : $MAX_ITERATIONS"
echo "   Cooldown       : ${COOLDOWN}s"
echo "   Timeout/iter   : ${TIMEOUT}s"
echo "   Log file       : $LOG_FILE"
echo "---"

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))

    PENDING=$(grep -c '\- \[ \]' TASK_LOG.md 2>/dev/null || true)
    DONE=$(grep -c '\- \[x\]' TASK_LOG.md 2>/dev/null || true)
    BLOCKED=$(grep -c '\- \[!\]' TASK_LOG.md 2>/dev/null || true)

    echo ""
    echo "═══════════════════════════════════════════════"
    echo "  Iteration $ITERATION / $MAX_ITERATIONS — $(date '+%H:%M:%S')"
    echo "  📊 ✅ $DONE done | ⏳ $PENDING pending | 🚧 $BLOCKED blocked"
    echo "═══════════════════════════════════════════════"

    if [ "$PENDING" -eq 0 ]; then
        echo ""
        echo "🏁 ALL TASKS COMPLETE!"
        echo "   ✅ $DONE completed | 🚧 $BLOCKED blocked"
        break
    fi

    echo "  📌 Next task: $(next_task)"
    echo "  🤖 Launching Claude (timeout: ${TIMEOUT}s)..."
    echo ""

    start_heartbeat
    ITER_START=$SECONDS

    # unbuffer fakes a TTY so Claude streams output even when piped;
    # falls back to script(1) if unbuffer (expect package) is not installed
    set +e
    if command -v unbuffer &>/dev/null; then
        timeout "$TIMEOUT" unbuffer claude \
            --dangerously-skip-permissions \
            --max-turns 50 \
            -p "Read TASK_LOG.md. Find the FIRST task marked [ ]. Implement it fully — write all code, create all files, run tests. When done, mark it [x] in TASK_LOG.md with a brief note. Then git add and commit. If a task is impossible or blocked, mark it [!] with explanation and move to the next [ ] task. Work on ONE task per invocation." \
            2>&1 | tee -a "$LOG_FILE"
    else
        # script -q allocates a PTY; -c runs the command; output goes to LOG_FILE directly
        echo "  ℹ️  unbuffer not found — install with: sudo apt install expect"
        script -q -e -f "$LOG_FILE" -c "timeout $TIMEOUT claude \
            --dangerously-skip-permissions \
            --max-turns 50 \
            -p 'Read TASK_LOG.md. Find the FIRST task marked [ ]. Implement it fully — write all code, create all files, run tests. When done, mark it [x] in TASK_LOG.md with a brief note. Then git add and commit. If a task is impossible or blocked, mark it [!] with explanation and move to the next [ ] task. Work on ONE task per invocation.'"
    fi
    EXIT_CODE=${PIPESTATUS[0]}
    set -e

    stop_heartbeat

    ELAPSED=$(( SECONDS - ITER_START ))

    if [ "$EXIT_CODE" -eq 124 ]; then
        echo ""
        echo "⚠️  TIMEOUT after ${ELAPSED}s — Claude was killed. Check $LOG_FILE for last output."
    elif [ "$EXIT_CODE" -ne 0 ]; then
        echo ""
        echo "⚠️  Claude exited with code $EXIT_CODE after ${ELAPSED}s."
    else
        echo ""
        echo "✔  Claude finished in ${ELAPSED}s."
    fi

    # Git status after each iteration
    echo ""
    echo "📁 Changes since last commit:"
    git diff --stat HEAD~1 2>/dev/null || echo "  (no commits yet)"

    echo "⏱️  Cooling down ${COOLDOWN}s..."
    sleep "$COOLDOWN"
done

stop_heartbeat

if [ $ITERATION -ge $MAX_ITERATIONS ]; then
    echo ""
    echo "⚠️  Reached max iterations ($MAX_ITERATIONS). Check TASK_LOG.md for remaining tasks."
fi

echo ""
echo "📋 Final status:"
grep -c '\- \[x\]' TASK_LOG.md 2>/dev/null | xargs -I{} echo "   ✅ {} completed"
grep -c '\- \[ \]' TASK_LOG.md 2>/dev/null | xargs -I{} echo "   ⏳ {} pending"
grep -c '\- \[!\]' TASK_LOG.md 2>/dev/null | xargs -I{} echo "   🚧 {} blocked"
