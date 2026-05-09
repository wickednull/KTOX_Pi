#!/usr/bin/env python3
"""
Loki Reconnaissance Engine Manager
===================================
Start, stop, and manage the Loki reconnaissance server
"""

import os
import sys
import subprocess
import time
import signal
from pathlib import Path

# Add KTOX paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

KTOX_ROOT = Path(__file__).parent.parent.parent
VENDOR_LOKI = KTOX_ROOT / "vendor" / "loki"
LOOT_DIR = KTOX_ROOT / "loot"
LOKI_PID_FILE = LOOT_DIR / "loki.pid"
LOKI_PORT = 8000

def ensure_loki_installed():
    """Check if Loki is properly installed."""
    if not VENDOR_LOKI.exists():
        print(f"❌ Loki not found at {VENDOR_LOKI}")
        print("   Please ensure vendor/loki is properly cloned from:")
        print("   https://github.com/brainphreak/loki-recon")
        return False
    return True

def get_loki_process():
    """Get Loki process info if running."""
    if not LOKI_PID_FILE.exists():
        return None
    try:
        with open(LOKI_PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        # Check if process exists
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return None

def start_loki():
    """Start the Loki server."""
    print("\n" + "="*50)
    print("🔍 STARTING LOKI RECONNAISSANCE ENGINE")
    print("="*50)

    if not ensure_loki_installed():
        return False

    # Check if already running
    if get_loki_process():
        print("⚠️  Loki is already running!")
        return True

    # Ensure loot directory exists
    LOOT_DIR.mkdir(parents=True, exist_ok=True)

    # Start Loki server
    try:
        loki_script = VENDOR_LOKI / "loki.py"
        if not loki_script.exists():
            print("❌ Could not find Loki entry point")
            print(f"   Expected at: {loki_script}")
            return False

        print(f"\n📍 Starting: {loki_script}")
        print(f"🔌 Port: {LOKI_PORT}")

        # Create environment with PYTHONPATH
        env = os.environ.copy()
        env['PYTHONPATH'] = str(VENDOR_LOKI) + ":" + str(VENDOR_LOKI / "loki")
        env['LOKI_PORT'] = str(LOKI_PORT)
        env['LOKI_DATA_DIR'] = str(LOOT_DIR / "loki_data")

        # Start as background process with log file for debugging
        log_file = LOOT_DIR / "loki.log"
        with open(log_file, 'w') as lf:
            proc = subprocess.Popen(
                [sys.executable, str(loki_script)],
                stdout=lf,
                stderr=subprocess.STDOUT,
                cwd=str(VENDOR_LOKI),
                env=env
            )

        # Save PID
        with open(LOKI_PID_FILE, 'w') as f:
            f.write(str(proc.pid))

        # Wait for startup
        time.sleep(3)

        # Verify it's running
        if get_loki_process():
            print(f"✅ Loki started successfully (PID: {proc.pid})")
            print(f"🌐 Access at: http://localhost:{LOKI_PORT}")
            return True
        else:
            print("❌ Failed to start Loki")
            # Show last lines of log for debugging
            if log_file.exists():
                with open(log_file, 'r') as lf:
                    lines = lf.readlines()[-10:]
                    if lines:
                        print("📋 Last log output:")
                        for line in lines:
                            print(f"   {line.rstrip()}")
            return False

    except Exception as e:
        print(f"❌ Error starting Loki: {e}")
        return False

def stop_loki():
    """Stop the Loki server."""
    print("\n" + "="*50)
    print("🛑 STOPPING LOKI RECONNAISSANCE ENGINE")
    print("="*50)

    pid = get_loki_process()
    if not pid:
        print("⚠️  Loki is not running")
        return True

    try:
        print(f"📍 Stopping Loki (PID: {pid})")
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)

        # Verify it stopped
        try:
            os.kill(pid, 0)
            # Still running, force kill
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        # Remove PID file
        if LOKI_PID_FILE.exists():
            LOKI_PID_FILE.unlink()

        print("✅ Loki stopped successfully")
        return True

    except Exception as e:
        print(f"❌ Error stopping Loki: {e}")
        return False

def get_status():
    """Get Loki server status."""
    pid = get_loki_process()
    if pid:
        print(f"✅ Loki is running (PID: {pid})")
        print(f"🌐 Access at: http://localhost:{LOKI_PORT}")
        return True
    else:
        print("⚠️  Loki is not running")
        return False

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: loki_manager.py <start|stop|status|restart>")
        print("\nExamples:")
        print("  loki_manager.py start   - Start Loki server")
        print("  loki_manager.py stop    - Stop Loki server")
        print("  loki_manager.py status  - Check Loki status")
        print("  loki_manager.py restart - Restart Loki server")
        return 1

    command = sys.argv[1].lower()

    if command == "start":
        return 0 if start_loki() else 1
    elif command == "stop":
        return 0 if stop_loki() else 1
    elif command == "status":
        return 0 if get_status() else 1
    elif command == "restart":
        stop_loki()
        time.sleep(1)
        return 0 if start_loki() else 1
    else:
        print(f"❌ Unknown command: {command}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
