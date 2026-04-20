#!/usr/bin/env bash
# Install PyBoy Game Boy emulator for KTOx (ARM / Raspberry Pi)
# Usage: sudo bash scripts/install_pyboy.sh
#
# Strategy:
#   1. piwheels.org  — pre-built ARM wheels, zero compilation, no disk issues
#   2. PyPI binary   — fallback if piwheels doesn't have this exact ABI
#   3. system cython + no-build-isolation — last resort, avoids Cython recompile
#
# Why NOT pip default on ARM:
#   pip falls back to source when no wheel exists for armv7l.
#   Building Cython 3 from source fills /tmp (No space left on device).

set -e

info() { printf "\e[1;32m[INFO]\e[0m %s\n" "$*"; }
warn() { printf "\e[1;33m[WARN]\e[0m %s\n" "$*"; }
err()  { printf "\e[1;31m[ERR ]\e[0m %s\n" "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 0. Free disk space before attempting anything
# ---------------------------------------------------------------------------
info "Freeing disk space before install..."
pip3 cache purge 2>/dev/null || true
apt-get clean 2>/dev/null || true
rm -rf /tmp/pip-* /tmp/cc*.s 2>/dev/null || true

AVAIL=$(df /tmp --output=avail -BM 2>/dev/null | tail -1 | tr -d 'M ')
info "Free space in /tmp: ${AVAIL:-?} MB"
if [ -n "$AVAIL" ] && [ "$AVAIL" -lt 150 ]; then
    warn "/tmp has less than 150 MB free — using /var/tmp as build dir"
    export TMPDIR=/var/tmp
    mkdir -p "$TMPDIR"
fi

# ---------------------------------------------------------------------------
# 1. Runtime system libraries  (never need compilation)
# ---------------------------------------------------------------------------
info "Installing system libraries..."
apt-get install -y --no-install-recommends \
    libsdl2-2.0-0 python3-numpy \
  || warn "apt install partial — continuing"

# ---------------------------------------------------------------------------
# 2. pip install — piwheels first (pre-compiled ARM binaries)
# ---------------------------------------------------------------------------
PIWHEELS="--extra-index-url https://www.piwheels.org/simple"
BREAK="--break-system-packages"
PREFER="--prefer-binary"

info "Trying piwheels.org (pre-built ARM wheel — no compilation)..."
if pip3 install $PREFER $PIWHEELS $BREAK "pyboy>=2.0" 2>/dev/null; then
    info "Installed from piwheels (break-system-packages)"
    INSTALLED=1
elif pip3 install $PREFER $PIWHEELS "pyboy>=2.0" 2>/dev/null; then
    info "Installed from piwheels (standard)"
    INSTALLED=1

# ---------------------------------------------------------------------------
# 3. PyPI binary-only fallback
# ---------------------------------------------------------------------------
elif pip3 install $PREFER --only-binary=:all: $BREAK "pyboy>=2.0" 2>/dev/null; then
    info "Installed from PyPI (binary-only)"
    INSTALLED=1

# ---------------------------------------------------------------------------
# 4. No-build-isolation with system cython (avoids downloading+building Cython)
# ---------------------------------------------------------------------------
else
    info "Binary install failed. Trying --no-build-isolation with system cython..."
    apt-get install -y --no-install-recommends \
        libsdl2-dev python3-dev cython3 \
      || warn "Dev deps partial"

    if pip3 install $BREAK --no-build-isolation "pyboy>=2.0" 2>/dev/null; then
        info "Installed with system cython (no-build-isolation)"
        INSTALLED=1
    elif pip3 install --no-build-isolation "pyboy>=2.0" 2>/dev/null; then
        info "Installed with system cython"
        INSTALLED=1
    else
        INSTALLED=0
    fi
fi

if [ "${INSTALLED:-0}" -eq 0 ]; then
    err "All install methods failed. Check disk space (df -h) and try:
  pip3 install --extra-index-url https://www.piwheels.org/simple --prefer-binary pyboy"
fi

# ---------------------------------------------------------------------------
# 5. Ensure numpy is importable
# ---------------------------------------------------------------------------
python3 -c "import numpy" 2>/dev/null \
  || pip3 install $PREFER $PIWHEELS $BREAK numpy 2>/dev/null \
  || warn "numpy check failed — screen pixel access may not work"

# ---------------------------------------------------------------------------
# 6. ROMs directory + verify
# ---------------------------------------------------------------------------
mkdir -p /root/KTOx/roms

if python3 -c "
from pyboy import PyBoy
import importlib.metadata
v = importlib.metadata.version('pyboy')
print(f'[OK] PyBoy {v} ready')
" 2>/dev/null; then
    info "Verification passed."
else
    err "PyBoy installed but import check failed. Run:
  python3 -c \"from pyboy import PyBoy\""
fi

info "Done! Place .gb / .gbc ROMs in /root/KTOx/roms/"
