#!/usr/bin/env bash
# Install PyBoy Game Boy emulator dependencies for KTOx
# Usage: sudo bash scripts/install_pyboy.sh
set -euo pipefail

info()  { printf "\e[1;32m[INFO]\e[0m %s\n"  "$*"; }
warn()  { printf "\e[1;33m[WARN]\e[0m %s\n"  "$*"; }

info "Installing PyBoy dependencies..."

# SDL2 library (required by PyBoy)
apt-get update
apt-get install -y --no-install-recommends libsdl2-dev

# PyBoy (Game Boy emulator) - use piwheels for pre-built ARM wheel
info "Installing PyBoy from piwheels (pre-built ARM wheel)..."
pip3 install --break-system-packages --extra-index-url https://www.piwheels.org/simple pyboy

# Create ROMs directory
mkdir -p /root/KTOx/roms

# Verify
python3 -c "from pyboy import PyBoy; print('[OK] PyBoy installed')" \
  || warn "PyBoy import failed - check errors above"

info "Done! Place .gb/.gbc ROMs in /root/KTOx/roms/"
