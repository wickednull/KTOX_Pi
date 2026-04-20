#!/usr/bin/env bash
# Install PyBoy Game Boy emulator for KTOx
# Usage: sudo bash scripts/install_pyboy.sh
#
# Fixes for ARM (Pi Zero 2 W / Pi 4):
#   - --prefer-binary  avoids source builds that fail when apt cython3 < 3.0
#   - python3-numpy    required by pyboy for screen pixel access
#   - libsdl2-2.0-0   runtime SDL2 library (not just dev headers)
#   - Tries multiple pip methods in order so one failure doesn't abort all

set -e

info() { printf "\e[1;32m[INFO]\e[0m %s\n" "$*"; }
warn() { printf "\e[1;33m[WARN]\e[0m %s\n" "$*"; }
err()  { printf "\e[1;31m[ERR ]\e[0m %s\n" "$*"; }

info "Installing PyBoy dependencies..."

# System packages
# libsdl2-2.0-0  = SDL2 runtime  (pyboy headless still links it)
# libsdl2-dev    = headers needed only if building from source
# python3-dev    = CPython headers for any C extension compilation
# python3-numpy  = required by pyboy.screen for pixel data
# cython3 from apt is 0.29 — we deliberately skip it here and let
# pip pull Cython 3 instead (pyboy >=2 requires Cython 3+).
apt-get install -y --no-install-recommends \
    libsdl2-2.0-0 libsdl2-dev python3-dev python3-numpy \
  || warn "Some apt packages failed — continuing anyway"

info "Installing PyBoy via pip (prefer binary wheels to avoid Cython issues)..."

INSTALLED=0

# Method 1: Debian Bookworm / Pi OS 12 — system pip with break flag
if pip3 install --prefer-binary --break-system-packages "pyboy>=2.0" 2>/dev/null; then
    info "Installed via pip (--break-system-packages)"
    INSTALLED=1

# Method 2: Older Pi OS / Raspbian — no break flag needed
elif pip3 install --prefer-binary "pyboy>=2.0" 2>/dev/null; then
    info "Installed via pip (standard)"
    INSTALLED=1

# Method 3: User install (no root needed, PATH must include ~/.local/bin)
elif pip3 install --prefer-binary --user "pyboy>=2.0" 2>/dev/null; then
    info "Installed via pip (--user)"
    INSTALLED=1

# Method 4: pipx / virtual-env fallback
elif python3 -m pip install --prefer-binary "pyboy>=2.0" 2>/dev/null; then
    info "Installed via python3 -m pip"
    INSTALLED=1
fi

if [ "$INSTALLED" -eq 0 ]; then
    err "All pip methods failed."
    err "Try manually: pip3 install --prefer-binary --break-system-packages pyboy"
    exit 1
fi

# Make sure numpy is importable (pip may have skipped it if apt version was found)
python3 -c "import numpy" 2>/dev/null \
  || pip3 install --prefer-binary --break-system-packages numpy 2>/dev/null \
  || pip3 install --prefer-binary numpy 2>/dev/null \
  || warn "numpy install failed — pyboy screen features may not work"

# ROMs directory
mkdir -p /root/KTOx/roms

# Verify
if python3 -c "from pyboy import PyBoy; print('[OK] PyBoy', __import__('importlib.metadata', fromlist=['version']).version('pyboy'), 'ready')" 2>/dev/null; then
    info "PyBoy import verified successfully."
else
    err "PyBoy installed but import check failed."
    err "Run: python3 -c \"from pyboy import PyBoy\" to debug."
    exit 1
fi

info "Done! Place .gb / .gbc ROMs in /root/KTOx/roms/"
