#!/usr/bin/env bash
# Idempotent EC2 deploy. Pulls code + dependencies, then (re)launches the
# NiceGUI app inside a detached `screen` session named `vaultiq` so it
# survives the SSH connection closing.
#
#     ssh ubuntu@<host> bash -s < scripts/_deploy_remote.sh
#
# Operational commands once it's running:
#     screen -ls                         # list sessions
#     screen -r vaultiq                  # attach (detach with Ctrl-A then D)
#     screen -S vaultiq -X quit          # stop the app
#     tail -f /home/ubuntu/vaultiq.log   # follow logs without attaching
set -euo pipefail
cd /home/ubuntu/langchain_interrupt_demo

SESSION=vaultiq
LOG=/home/ubuntu/vaultiq.log

echo '== one-time cleanup of the old systemd unit (if present) =='
if systemctl list-unit-files 2>/dev/null | grep -q '^vaultiq\.service'; then
  sudo systemctl disable --now vaultiq.service 2>/dev/null || true
  sudo rm -f /etc/systemd/system/vaultiq.service
  sudo systemctl daemon-reload || true
  echo '   removed /etc/systemd/system/vaultiq.service'
fi

echo '== killing any stray app processes =='
pkill -f 'streamlit run'           2>/dev/null || true
pkill -f 'demo/bin/python.*app.py' 2>/dev/null || true
sleep 1

echo "== killing any existing screen session ($SESSION) =="
screen -S "$SESSION" -X quit 2>/dev/null || true
sleep 1

echo '== git pull =='
# diagnostic helpers may have been scp'd earlier and are now committed
rm -f scripts/_*.py
git pull --ff-only

echo '== pip install =='
demo/bin/pip install --quiet --upgrade -r requirements.txt

echo '== version check =='
demo/bin/python - <<'PY'
import nicegui, sys
print('nicegui', nicegui.__version__, 'python', sys.version.split()[0])
PY

# Make sure `screen` is available.
if ! command -v screen >/dev/null 2>&1; then
  echo '== installing screen =='
  sudo apt-get update -qq
  sudo apt-get install -y -qq screen
fi

CRON_LINE="@reboot /bin/bash /home/ubuntu/langchain_interrupt_demo/scripts/_screen_start.sh >>/home/ubuntu/vaultiq.log 2>&1"
echo '== upserting @reboot crontab entry =='
chmod +x /home/ubuntu/langchain_interrupt_demo/scripts/_screen_start.sh
existing=$(crontab -l 2>/dev/null || true)
filtered=$(printf '%s\n' "$existing" | grep -v '_screen_start.sh' || true)
printf '%s\n%s\n' "$filtered" "$CRON_LINE" | sed '/^$/d' | crontab -
crontab -l | grep -F '_screen_start.sh' || { echo '!! crontab install failed'; exit 1; }

echo "== launching $SESSION in a detached screen =="
bash /home/ubuntu/langchain_interrupt_demo/scripts/_screen_start.sh

echo '== waiting for port 8505 =='
ok=0
for i in {1..30}; do
  if ss -ltn '( sport = :8505 )' | grep -q 8505; then
    echo "  ✅ listener ready after ${i}s"
    ok=1
    break
  fi
  sleep 1
done

echo '== screen sessions =='
screen -ls || true

if [[ "$ok" -ne 1 ]]; then
  echo '!! port 8505 not listening — last 30 log lines:'
  tail -n 30 "$LOG" || true
  exit 1
fi

echo '== last 10 log lines =='
tail -n 10 "$LOG" || true
