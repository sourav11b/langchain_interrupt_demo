#!/usr/bin/env bash
# Remote deploy / restart script for the EC2 demo box.
# Run via:  ssh ubuntu@<host> bash -s < scripts/_deploy_remote.sh
set -euo pipefail
cd /home/ubuntu/langchain_interrupt_demo

echo '== killing any existing UI process =='
pkill -f 'streamlit run' 2>/dev/null || true
pkill -f 'demo/bin/python.*app.py' 2>/dev/null || true
pkill -f 'nicegui' 2>/dev/null || true
sleep 2

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

echo '== launching nicegui app (detached) =='
rm -f /tmp/vaultiq.log
setsid bash -c 'demo/bin/python app.py >/tmp/vaultiq.log 2>&1 &'
sleep 8

echo '== status =='
ps -ef | grep -E 'python.*app.py' | grep -v grep || echo 'NO PROCESS'
ss -ltn | grep 8501 || echo 'NO LISTENER'

echo '== log tail =='
tail -40 /tmp/vaultiq.log || true
