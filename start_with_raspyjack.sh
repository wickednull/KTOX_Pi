#!/bin/bash
# Start KTOx with RaspyJack Cardputer support
# This script launches both the WebSocket server and main device

set -e

KTOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$KTOX_DIR"

# Configuration
WS_HOST="${RJ_WS_HOST:-0.0.0.0}"
WS_PORT="${RJ_WS_PORT:-8765}"
WS_FPS="${RJ_FPS:-10}"
FRAME_PATH="${RJ_FRAME_PATH:-/dev/shm/ktox_last.jpg}"
INPUT_SOCK="${RJ_INPUT_SOCK:-/dev/shm/ktox_input.sock}"
LOG_DIR="${KTOX_DIR}/loot"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  KTOx with RaspyJack Cardputer Support║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Verify paths exist
if [ ! -f "device_server.py" ]; then
    echo -e "${RED}✗ device_server.py not found${NC}"
    exit 1
fi

if [ ! -f "ktox_device.py" ]; then
    echo -e "${RED}✗ ktox_device.py not found${NC}"
    exit 1
fi

# Create necessary directories
mkdir -p "$LOG_DIR"
mkdir -p /dev/shm

echo -e "${GREEN}✓ Configuration:${NC}"
echo "  WebSocket Host: $WS_HOST"
echo "  WebSocket Port: $WS_PORT"
echo "  Frame Rate: $WS_FPS FPS"
echo "  Frame Path: $FRAME_PATH"
echo "  Input Socket: $INPUT_SOCK"
echo "  Log Directory: $LOG_DIR"
echo ""

# Check if ports/sockets are already in use
if [ -S "$INPUT_SOCK" ]; then
    echo -e "${YELLOW}⚠ Input socket exists, removing: $INPUT_SOCK${NC}"
    rm -f "$INPUT_SOCK"
fi

# Function to cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down KTOx...${NC}"
    kill $WS_PID $DEVICE_PID 2>/dev/null || true
    wait $WS_PID $DEVICE_PID 2>/dev/null || true
    rm -f "$INPUT_SOCK"
    echo -e "${GREEN}✓ Cleanup complete${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start WebSocket server
echo -e "${BLUE}Starting WebSocket server...${NC}"
export RJ_WS_HOST="$WS_HOST"
export RJ_WS_PORT="$WS_PORT"
export RJ_FPS="$WS_FPS"
export RJ_FRAME_PATH="$FRAME_PATH"
export RJ_INPUT_SOCK="$INPUT_SOCK"

python3 device_server.py > "$LOG_DIR/device_server.log" 2>&1 &
WS_PID=$!
echo -e "${GREEN}✓ WebSocket server started (PID: $WS_PID)${NC}"

# Give server time to start
sleep 2

# Check if WebSocket server is running
if ! kill -0 $WS_PID 2>/dev/null; then
    echo -e "${RED}✗ WebSocket server failed to start${NC}"
    cat "$LOG_DIR/device_server.log"
    exit 1
fi

# Start KTOx main device
echo -e "${BLUE}Starting KTOx main device...${NC}"
python3 ktox_device.py > "$LOG_DIR/ktox_device.log" 2>&1 &
DEVICE_PID=$!
echo -e "${GREEN}✓ KTOx device started (PID: $DEVICE_PID)${NC}"

# Give device time to initialize
sleep 3

# Verify both are running
if ! kill -0 $WS_PID 2>/dev/null || ! kill -0 $DEVICE_PID 2>/dev/null; then
    echo -e "${RED}✗ One or more processes failed${NC}"
    if ! kill -0 $WS_PID 2>/dev/null; then
        echo "WebSocket server error:"
        tail -20 "$LOG_DIR/device_server.log"
    fi
    if ! kill -0 $DEVICE_PID 2>/dev/null; then
        echo "KTOx device error:"
        tail -20 "$LOG_DIR/ktox_device.log"
    fi
    exit 1
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║    KTOx Ready for RaspyJack Control   ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Connection Details:${NC}"
echo "  WebSocket: ws://$WS_HOST:$WS_PORT"
echo "  Use this URL in RaspyJack Cardputer app"
echo ""
echo -e "${BLUE}Features:${NC}"
echo "  • Real-time remote control via Cardputer"
echo "  • Live screen streaming"
echo "  • All 8 buttons mapped and working"
echo "  • Full payload support"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo "  WebSocket: tail -f $LOG_DIR/device_server.log"
echo "  Device: tail -f $LOG_DIR/ktox_device.log"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

# Monitor both processes
while true; do
    sleep 1

    if ! kill -0 $WS_PID 2>/dev/null; then
        echo -e "${RED}✗ WebSocket server crashed${NC}"
        break
    fi

    if ! kill -0 $DEVICE_PID 2>/dev/null; then
        echo -e "${RED}✗ KTOx device crashed${NC}"
        break
    fi
done

cleanup
