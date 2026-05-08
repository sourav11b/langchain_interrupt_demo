#!/usr/bin/env bash
# Idempotent launcher for the VaultIQ NiceGUI app inside a detached `screen`
# session. Used by both `_deploy_remote.sh` and the `@reboot` crontab entry,
# so the dashboard auto-comes-up after an EC2 reboot.
#
#     bash /home/ubuntu/langchain_interrupt_demo/scripts/_screen_start.sh
set -euo pipefail

REPO=/home/ubuntu/langchain_interrupt_demo
SESSION=vaultiq
LOG=/home/ubuntu/vaultiq.log

# If the session is already up, do nothing — keeps `@reboot` and manual
# re-runs from spawning duplicates.
if screen -ls 2>/dev/null | grep -qE "[0-9]+\.${SESSION}\b"; then
  echo "screen session '$SESSION' already running; nothing to do"
  exit 0
fi

cd "$REPO"
: > "$LOG"
screen -dmS "$SESSION" bash -lc "
  cd $REPO
  export VAULTIQ_PORT=8505
  export VAULTIQ_HOST=0.0.0.0
  export PYTHONUNBUFFERED=1
  exec demo/bin/python app.py >>'$LOG' 2>&1
"
echo "launched screen session '$SESSION' (log: $LOG)"
