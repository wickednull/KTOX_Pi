#!/usr/bin/env python3
"""
_debug_helper.py — KTOx Central Debug Logger
=============================================
All payloads should import and use log() for consistent, timestamped
debug output written to /root/KTOx/loot/ktox_debug.log.

Usage:
    from _debug_helper import log
    log("Starting scan", tag="DEAUTH")
    log("Monitor mode failed", level="ERROR", tag="MON")
"""

import os
import time

LOG_FILE = "/root/KTOx/loot/ktox_debug.log"
MAX_BYTES = 1_000_000   # rotate at 1 MB


def log(msg: str, level: str = "INFO", tag: str = "KTOX") -> None:
    """
    Write a timestamped entry to the debug log and stdout.

    Args:
        msg:   Message text.
        level: Severity label — INFO, WARN, ERROR, DEBUG.
        tag:   Module/payload identifier (e.g. "DEAUTH", "MON").
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:<5}] [{tag}] {msg}"
    print(line, flush=True)
    try:
        log_dir = os.path.dirname(LOG_FILE)
        os.makedirs(log_dir, exist_ok=True)
        # Simple rotation: rename existing file when it exceeds MAX_BYTES
        try:
            if os.path.getsize(LOG_FILE) > MAX_BYTES:
                rotated = LOG_FILE + ".1"
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(LOG_FILE, rotated)
        except OSError:
            pass
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass  # Never let logging crash a payload
