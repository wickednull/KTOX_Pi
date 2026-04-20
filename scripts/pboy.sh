#!/usr/bin/env bash
# install_pyboy.sh – A more robust installer for PyBoy on KTOx

set -e

info()  { printf "\e[1;32m[INFO]\e[0m %s\n"  "$*"; }
warn()  { printf "\e[1;33m[WARN]\e[0m %s\n"  "$*"; }

info "Installing system dependencies for PyBoy..."
sudo apt update
sudo apt install -y libsdl2-dev python3-dev build-essential cython3

info "Creating Python virtual environment..."
python3 -m venv ~/ktox_pyboy_env
source ~/ktox_pyboy_env/bin/activate

info "Installing PyBoy..."
pip install --upgrade pip
pip install pyboy

info "Verifying installation..."
python3 -c "from pyboy import PyBoy; print('[OK] PyBoy installed successfully')"

info "To run the emulator, activate the environment with: source ~/ktox_pyboy_env/bin/activate"
info "Then run your Python script from within that environment."