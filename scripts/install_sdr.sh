#!/usr/bin/env bash
set -euo pipefail

info() { echo "[SDR] $*"; }
warn() { echo "[SDR] WARNING: $*" >&2; }
die() { echo "[SDR] ERROR: $*" >&2; exit 1; }
require_file() {
  local rel="$1"
  [[ -f "$KTOX_DIR/$rel" ]] || die "Missing $KTOX_DIR/$rel. Copy or pull the current repo files into $KTOX_DIR before installing SDR."
}
wait_for_http() {
  local url="${1:-http://127.0.0.1:8081/}"
  local tries="${2:-30}"
  local delay="${3:-1}"
  local _i
  for _i in $(seq 1 "$tries"); do
    if curl -fsS -o /dev/null "$url"; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

if [[ "$(id -u)" -ne 0 ]]; then
  die "Run as root: sudo bash scripts/install_sdr.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KTOX_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_PATH="/etc/systemd/system/ktox-sdr.service"
ENABLE_SERVICE="${KTOX_SDR_ENABLE:-ask}"
START_SERVICE="${KTOX_SDR_START:-ask}"

cd "$KTOX_DIR"

require_file "services/sdr_server.py"
require_file "sdr/trunking.py"
require_file "static/sdr/index.html"
require_file "tools/validate_sdr_suite.py"

info "Installing SDR dependencies"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    hackrf libhackrf0 usbutils \
    python3 python3-pip python3-numpy
else
  warn "apt-get not found; install hackrf, libhackrf0, usbutils, python3, python3-pip, and python3-numpy manually"
fi

info "Installing Python requirements"
if [[ -f "$KTOX_DIR/requirements.txt" ]]; then
  python3 -m pip install --break-system-packages -r "$KTOX_DIR/requirements.txt" 2>/dev/null \
    || python3 -m pip install -r "$KTOX_DIR/requirements.txt"
else
  warn "requirements.txt not found at $KTOX_DIR"
fi

info "Preparing capture directory"
mkdir -p "$KTOX_DIR/captures"

info "Installing systemd unit at $SERVICE_PATH"
cat > "$SERVICE_PATH" << UNIT
[Unit]
Description=KTOX SDR Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$KTOX_DIR
ExecStart=/usr/bin/python3 $KTOX_DIR/services/sdr_server.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

if [[ "$ENABLE_SERVICE" == "ask" ]]; then
  read -r -p "Enable ktox-sdr at boot? [Y/n] " reply
  if [[ "${reply:-Y}" =~ ^[Yy]$ ]]; then
    ENABLE_SERVICE=1
  else
    ENABLE_SERVICE=0
  fi
fi

if [[ "$ENABLE_SERVICE" =~ ^(1|true|yes|on)$ ]]; then
  info "Enabling ktox-sdr"
  systemctl enable ktox-sdr.service
fi

if [[ "$START_SERVICE" == "ask" ]]; then
  read -r -p "Start ktox-sdr now? [Y/n] " reply
  if [[ "${reply:-Y}" =~ ^[Yy]$ ]]; then
    START_SERVICE=1
  else
    START_SERVICE=0
  fi
fi

if [[ "$START_SERVICE" =~ ^(1|true|yes|on)$ ]]; then
  info "Starting ktox-sdr"
  systemctl restart ktox-sdr.service
  if wait_for_http "http://127.0.0.1:8081/" 30 1; then
    info "SDR Suite is answering on http://127.0.0.1:8081/"
  else
    warn "ktox-sdr did not answer on http://127.0.0.1:8081/"
    systemctl status ktox-sdr --no-pager || true
    journalctl -u ktox-sdr -n 80 --no-pager || true
    die "SDR service did not start cleanly"
  fi
fi

info "Running no-hardware SDR validation"
if python3 "$KTOX_DIR/tools/validate_sdr_suite.py"; then
  info "SDR validation passed"
else
  warn "SDR validation failed; check Python dependencies and logs"
fi

if command -v hackrf_info >/dev/null 2>&1; then
  info "Checking HackRF hardware"
  hackrf_info || warn "hackrf_info did not find a usable HackRF device"
else
  warn "hackrf_info is not available"
fi

info "Done. Open http://<device-ip>:8081/ for the SDR Suite."
info "Useful checks:"
info "  systemctl status ktox-sdr --no-pager"
info "  journalctl -u ktox-sdr -n 80 --no-pager"
