#!/usr/bin/env bash
# One-time installer: register and start vaultiq.service via systemd.
# Idempotent — safe to run on every deploy.
#
#     bash scripts/install_service.sh
set -euo pipefail

REPO=/home/ubuntu/langchain_interrupt_demo
UNIT_SRC="$REPO/scripts/vaultiq.service"
UNIT_DST=/etc/systemd/system/vaultiq.service

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "missing $UNIT_SRC" >&2
  exit 1
fi

echo '== installing systemd unit =='
sudo install -m 0644 "$UNIT_SRC" "$UNIT_DST"
sudo systemctl daemon-reload

echo '== enabling + (re)starting vaultiq =='
sudo systemctl enable vaultiq.service >/dev/null
sudo systemctl restart vaultiq.service

# wait for the listener to come up
for i in {1..15}; do
  if ss -ltn '( sport = :8505 )' | grep -q 8505; then
    echo "  ✅ listener ready after ${i}s"
    break
  fi
  sleep 1
done

echo '== status =='
systemctl --no-pager --full status vaultiq.service | head -20

echo '== last 10 log lines =='
journalctl -u vaultiq -n 10 --no-pager || true
