#!/usr/bin/env bash
# Install PyBoy Game Boy emulator dependencies for KTOx
# Usage: sudo bash scripts/install_pyboy.sh
#
# The only pip command confirmed to work on Pi (externally managed env):
#   pip install pyboy --extra-index-url https://www.piwheels.org/simple --break-system-packages

info()  { printf "\e[1;32m[INFO]\e[0m %s\n"  "$*"; }
warn()  { printf "\e[1;33m[WARN]\e[0m %s\n"  "$*"; }
err()   { printf "\e[1;31m[ERR ]\e[0m %s\n"  "$*"; exit 1; }

# SDL2 library (required by PyBoy)
info "Updating package list..."
apt-get update || warn "apt-get update failed, continuing anyway"

info "Installing libsdl2-dev..."
apt-get install -y --no-install-recommends libsdl2-dev \
  || warn "libsdl2-dev install failed — PyBoy may still work if SDL2 is already present"

# PyBoy — use piwheels for pre-built ARM wheel.
# --break-system-packages is required on Pi OS Bookworm (externally managed env).
# --extra-index-url pulls the pre-compiled ARM wheel; building from source takes 20+ min.
info "Installing PyBoy from piwheels (pre-built ARM wheel)..."
pip install pyboy \
    --extra-index-url https://www.piwheels.org/simple \
    --break-system-packages \
  || python3 -m pip install pyboy \
       --extra-index-url https://www.piwheels.org/simple \
       --break-system-packages \
  || err "PyBoy install failed — see errors above"

# Create ROMs directory
mkdir -p /root/KTOx/roms

# Verify
python3 -c "from pyboy import PyBoy; print('[OK] PyBoy installed successfully')" \
  || warn "PyBoy import check failed — may still work at runtime"

info "Done!  Place .gb / .gbc ROM files in /root/KTOx/roms/"
