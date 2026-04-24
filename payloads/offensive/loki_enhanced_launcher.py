#!/usr/bin/env python3
"""
Enhanced Loki Headless Launcher for KTOx
=========================================
Improved launcher with better Flask initialization and debugging.
Should be written to: /root/KTOx/vendor/loki/ktox_headless_loki_enhanced.py
"""

import sys
import os
import threading
import signal
import logging
import time
import traceback

# Setup paths
_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

# Set environment variables
os.environ['CRYPTOGRAPHY_OPENSSL_NO_LEGACY'] = '1'
os.environ['FLASK_ENV'] = 'production'
os.environ['PYTHONUNBUFFERED'] = '1'

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(asctime)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.expanduser(os.environ.get('LOKI_DATA_DIR', '/root/KTOx/loot/loki') + '/logs/loki_debug.log'))
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Main launcher function"""
    try:
        logger.info("=" * 60)
        logger.info("Loki Headless Service Starting")
        logger.info("=" * 60)

        # Import Loki components
        logger.info("Loading Loki modules...")
        try:
            from init_shared import shared_data
            logger.info("  [✓] init_shared loaded")
        except ImportError as e:
            logger.error(f"  [✗] Failed to load init_shared: {e}")
            raise

        try:
            from Loki import Loki, handle_exit
            logger.info("  [✓] Loki core loaded")
        except ImportError as e:
            logger.error(f"  [✗] Failed to load Loki core: {e}")
            raise

        try:
            from webapp import web_thread, handle_exit_web
            logger.info("  [✓] webapp loaded")
        except ImportError as e:
            logger.error(f"  [✗] Failed to load webapp: {e}")
            raise

        # Initialize Loki
        logger.info("Initializing Loki...")
        shared_data.load_config()
        logger.info("  [✓] Config loaded")

        shared_data.webapp_should_exit = False
        shared_data.display_should_exit = True
        logger.info("  [✓] Flags set")

        # Start web server
        logger.info("Starting Flask WebUI...")
        try:
            web_thread.start()
            logger.info("  [✓] Web thread started")
            time.sleep(2)  # Give Flask time to bind to port
        except Exception as e:
            logger.error(f"  [✗] Failed to start web server: {e}")
            traceback.print_exc()
            raise

        # Start Loki engine
        logger.info("Starting Loki engine...")
        try:
            loki = Loki(shared_data)
            lt = threading.Thread(target=loki.run, daemon=True)
            lt.start()
            logger.info("  [✓] Loki engine started")
        except Exception as e:
            logger.error(f"  [✗] Failed to start Loki engine: {e}")
            traceback.print_exc()
            raise

        # Setup signal handlers
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            try:
                handle_exit(sig, frame, lt, web_thread)
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("=" * 60)
        logger.info("Loki is READY and running!")
        logger.info(f"WebUI available at: http://{os.environ.get('BJORN_IP', 'localhost')}:8000")
        logger.info("=" * 60)

        # Main loop
        while not shared_data.should_exit:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                break

        logger.info("Loki shutting down...")
        sys.exit(0)

    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"FATAL ERROR: {e}")
        logger.error("=" * 60)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
