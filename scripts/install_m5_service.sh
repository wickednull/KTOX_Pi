#!/bin/bash
#
# install_m5_service.sh
# Install KTOX_Pi with M5Cardputer support as a systemd service
#
# Usage: sudo ./scripts/install_m5_service.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_FILE="$REPO_DIR/ktox-with-m5.service"

if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must run as root"
    exit 1
fi

if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: $SERVICE_FILE not found"
    exit 1
fi

echo "Installing KTOX_Pi M5Cardputer systemd service..."
echo "Repository: $REPO_DIR"

# Update service file with correct paths
sed -e "s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|" \
    "$SERVICE_FILE" > /etc/systemd/system/ktox-with-m5.service

# Set permissions
chmod 644 /etc/systemd/system/ktox-with-m5.service

# Reload systemd
systemctl daemon-reload

echo "✓ Service installed at /etc/systemd/system/ktox-with-m5.service"
echo ""
echo "Enable on boot:"
echo "  sudo systemctl enable ktox-with-m5"
echo ""
echo "Start service:"
echo "  sudo systemctl start ktox-with-m5"
echo ""
echo "Monitor logs:"
echo "  sudo journalctl -u ktox-with-m5 -f"
