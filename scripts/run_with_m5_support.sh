#!/bin/bash
#
# run_with_m5_support.sh
# Starts KTOX_Pi with M5Cardputer remote control support enabled
#
# Usage: sudo ./run_with_m5_support.sh [FPS]
# Example: sudo ./run_with_m5_support.sh 6
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FPS="${1:-6}"

# Validate root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must run as root"
    exit 1
fi

# Load frame capture configuration
if [ -f "$SCRIPT_DIR/.env.frame_capture" ]; then
    set -a
    source "$SCRIPT_DIR/.env.frame_capture"
    set +a
fi

# Override FPS if provided as argument
if [ -n "$1" ] && [ "$1" != "--help" ]; then
    export RJ_FRAME_FPS="$1"
fi

# Ensure required directories exist
mkdir -p /dev/shm
mkdir -p /root/KTOx

# Log configuration
echo "[M5 Support] Frame capture configuration:"
echo "  RJ_FRAME_MIRROR=${RJ_FRAME_MIRROR:-1}"
echo "  RJ_FRAME_PATH=${RJ_FRAME_PATH:-/dev/shm/ktox_last.jpg}"
echo "  RJ_FRAME_FPS=${RJ_FRAME_FPS:-6}"
echo "  RJ_WS_HOST=${RJ_WS_HOST:-0.0.0.0}"
echo "  RJ_WS_PORT=${RJ_WS_PORT:-8765}"
echo ""

# Start KTOX_Pi
cd "$SCRIPT_DIR"
python3 ktox_device_root.py
