#!/usr/bin/env bash
# Install PyBoy Game Boy emulator dependencies for KTOx
# Usage: sudo bash scripts/install_pyboy.sh
set -euo pipefail

info()  { printf "\e[1;32m[INFO]\e[0m %s\n"  "$*"; }
warn()  { printf "\e[1;33m[WARN]\e[0m %s\n"  "$*"; }

info "Installing PyBoy dependencies..."

# Build dependencies (needed if pip falls back to compiling from source on ARM)
apt-get install -y --no-install-recommends \
  libsdl2-dev python3-dev cython3 2>/dev/null \
  || warn "Some build deps failed — pip install may still work via wheel"

# PyBoy (Game Boy emulator)
pip3 install --break-system-packages pyboy 2>/dev/null \
  || pip3 install pyboy 2>/dev/null \
  || warn "PyBoy install failed"

# Create ROMs directory
mkdir -p /root/KTOx/roms

# Verify
python3 -c "from pyboy import PyBoy; print('[OK] PyBoy installed')" 2>/dev/null \
  || warn "PyBoy import failed - check errors above"

info "Done! Place .gb/.gbc ROMs in /root/KTOx/roms/"
