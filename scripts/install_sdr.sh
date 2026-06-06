#!/usr/bin/env bash
set -euo pipefail

info() { echo "[SDR] $*"; }
warn() { echo "[SDR] WARNING: $*" >&2; }
die() { echo "[SDR] ERROR: $*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  die "Run as root: sudo bash scripts/install_sdr.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KTOX_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_PATH="/etc/systemd/system/ktox-sdr.service"
ENABLE_SERVICE="${KTOX_SDR_ENABLE:-ask}"
START_SERVICE="${KTOX_SDR_START:-ask}"

cd "$KTOX_DIR"

info "Installing SDR dependencies"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    hackrf libhackrf0 \
    python3 python3-pip python3-numpy
else
  warn "apt-get not found; install hackrf, libhackrf0, python3, python3-pip, and python3-numpy manually"
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

if [[ -f "$KTOX_DIR/deploy/caddy/Caddyfile" && -d /etc/caddy ]]; then
  info "Installing Caddy SDR proxy route"
  cp "$KTOX_DIR/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
  if command -v caddy >/dev/null 2>&1; then
    caddy validate --config /etc/caddy/Caddyfile || warn "Caddy config validation failed"
  fi
  systemctl reload caddy 2>/dev/null || systemctl restart caddy 2>/dev/null || warn "Could not reload Caddy"
fi

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

info "Done. Open https://<device-ip>/sdr/ when using the HTTPS WebUI, or http://<device-ip>:8081/ for direct HTTP."
info "Useful checks:"
info "  systemctl status ktox-sdr --no-pager"
info "  journalctl -u ktox-sdr -n 80 --no-pager"
