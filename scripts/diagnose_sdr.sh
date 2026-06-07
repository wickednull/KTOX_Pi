#!/usr/bin/env bash
set -u

KTOX_DIR="${KTOX_DIR:-/root/KTOx}"
SERVICE="ktox-sdr.service"

section() { echo; echo "== $* =="; }
check_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    ls -ld "$path"
  else
    echo "MISSING $path"
  fi
}

section "SDR install root"
echo "KTOX_DIR=$KTOX_DIR"
check_file "$KTOX_DIR"
check_file "$KTOX_DIR/services/sdr_server.py"
check_file "$KTOX_DIR/static/sdr/index.html"
check_file "$KTOX_DIR/tools/validate_sdr_suite.py"
check_file "$KTOX_DIR/scripts/install_sdr.sh"

section "Search for sdr_server.py"
find /root -path '*/services/sdr_server.py' -print 2>/dev/null | sed 's/^/FOUND /' || true

section "Systemd unit"
systemctl cat "$SERVICE" 2>/dev/null || echo "Unit $SERVICE is not installed"

section "Service status"
systemctl status "$SERVICE" --no-pager 2>/dev/null || true

section "Port 8081"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp | grep ':8081' || echo "Nothing is listening on 8081"
else
  netstat -ltnp 2>/dev/null | grep ':8081' || echo "Nothing is listening on 8081"
fi

section "Local HTTP check"
curl -I --max-time 3 http://127.0.0.1:8081/ 2>&1 || true

section "Recent SDR logs"
journalctl -u "$SERVICE" -n 40 --no-pager 2>/dev/null || true
