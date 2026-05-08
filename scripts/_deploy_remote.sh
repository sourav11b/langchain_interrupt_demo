#!/usr/bin/env bash
# Idempotent EC2 deploy. Runs git pull + pip install, installs the systemd
# unit if it's not already there, then restarts the service.
#
#     ssh ubuntu@<host> bash -s < scripts/_deploy_remote.sh
set -euo pipefail
cd /home/ubuntu/langchain_interrupt_demo

echo '== killing any stray manual processes =='
pkill -f 'streamlit run'              2>/dev/null || true
pkill -f 'demo/bin/python.*app.py'    2>/dev/null || true
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

echo '== systemd =='
bash scripts/install_service.sh

echo '== status =='
systemctl --no-pager status vaultiq.service | head -10
ss -ltn | grep 8505 || echo 'NO LISTENER on 8505'
