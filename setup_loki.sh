#!/bin/bash
# setup_loki.sh — Initialize and configure Loki reconnaissance engine
# Run this after initial KTOx installation to enable Loki from the LCD menu

set -e

KTOX_DIR="${1:-.}"
LOKI_VENDOR_DIR="$KTOX_DIR/vendor/loki"
LOKI_REPO="https://github.com/brainphreak/loki-recon.git"

echo "=================================================="
echo "🔍 LOKI RECONNAISSANCE ENGINE SETUP"
echo "=================================================="

# Check if we're in the right place
if [ ! -d "$KTOX_DIR/payloads" ]; then
    echo "❌ Error: Not in KTOx directory"
    echo "   Usage: ./setup_loki.sh [ktox_dir]"
    echo "   Example: ./setup_loki.sh /root/KTOx"
    exit 1
fi

echo "📍 KTOx directory: $KTOX_DIR"
echo "📍 Loki directory: $LOKI_VENDOR_DIR"

# Remove incomplete submodule if it exists
if [ -d "$LOKI_VENDOR_DIR" ] && [ ! -f "$LOKI_VENDOR_DIR/loki.py" ]; then
    echo "🗑️  Removing incomplete Loki installation..."
    rm -rf "$LOKI_VENDOR_DIR"
fi

# Clone/update loki-recon if needed
if [ ! -d "$LOKI_VENDOR_DIR" ]; then
    echo "📥 Cloning loki-recon from GitHub..."
    git clone "$LOKI_REPO" "$LOKI_VENDOR_DIR"
elif [ ! -f "$LOKI_VENDOR_DIR/loki.py" ]; then
    echo "🔄 Updating Loki installation..."
    cd "$LOKI_VENDOR_DIR"
    git pull origin main
    cd -
fi

# Check if loki.py exists now
if [ ! -f "$LOKI_VENDOR_DIR/loki.py" ]; then
    echo "❌ Failed to set up Loki"
    exit 1
fi

echo "✅ Loki core files present"

# Set up Python virtual environment if needed
if [ ! -f "$LOKI_VENDOR_DIR/.venv/bin/python3" ]; then
    echo "🐍 Creating Python virtual environment..."
    cd "$LOKI_VENDOR_DIR"

    # Detect package manager and install dependencies
    if command -v apt-get &> /dev/null; then
        echo "📦 Installing system dependencies (apt)..."
        apt-get update
        apt-get install -y nmap smbclient freerdp2-x11 python3-venv python3-pip
    elif command -v dnf &> /dev/null; then
        echo "📦 Installing system dependencies (dnf)..."
        dnf install -y nmap samba-client freerdp python3-venv python3-pip
    elif command -v pacman &> /dev/null; then
        echo "📦 Installing system dependencies (pacman)..."
        pacman -S nmap samba freerdp python python-pip
    elif command -v zypper &> /dev/null; then
        echo "📦 Installing system dependencies (zypper)..."
        zypper install -y nmap samba freerdp python3-venv python3-pip
    else
        echo "⚠️  Could not detect package manager"
        echo "   Please install manually: nmap, smbclient, freerdp"
    fi

    # Create and activate venv
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
    deactivate

    cd - > /dev/null
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Generate and install KTOx's bundled Loki themes after Python deps exist.
LOKI_PYTHON="$LOKI_VENDOR_DIR/.venv/bin/python3"
if [ ! -x "$LOKI_PYTHON" ]; then
    LOKI_PYTHON="python3"
fi
if [ -f "$KTOX_DIR/payloads/offensive/install_loki_themes.py" ]; then
    echo "🎨 Installing KTOx cyberpunk Loki themes..."
    if ! "$LOKI_PYTHON" -c "import PIL" &> /dev/null; then
        "$LOKI_PYTHON" -m pip install pillow || \
            echo "⚠️  Could not install Pillow for Loki theme generation"
    fi
    "$LOKI_PYTHON" "$KTOX_DIR/payloads/offensive/install_loki_themes.py" "$KTOX_DIR" --activate neon_runner || \
        echo "⚠️  Could not install and activate bundled Loki themes"
fi

# Verify installation
if python3 "$LOKI_VENDOR_DIR/loki.py" --help &> /dev/null; then
    echo "✅ Loki is ready to use"
else
    echo "⚠️  Loki verification failed"
    echo "   Try running: cd $LOKI_VENDOR_DIR && source .venv/bin/activate && python3 loki.py --help"
fi

echo ""
echo "=================================================="
echo "✅ LOKI SETUP COMPLETE"
echo "=================================================="
echo ""
echo "Access Loki from the LCD menu:"
echo "  Payloads → Offensive → Loki Engine"
echo ""
echo "Or from command line:"
echo "  python3 $KTOX_DIR/payloads/offensive/loki_manager.py start"
echo "  python3 $KTOX_DIR/payloads/offensive/loki_manager.py status"
echo "  python3 $KTOX_DIR/payloads/offensive/loki_manager.py stop"
echo ""
echo "Web UI: http://[ip]:8000/"
echo ""
