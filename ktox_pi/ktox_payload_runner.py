#!/usr/bin/env python3
# ktox_payload_runner.py — KTOx Payload Engine
#
# Loads and runs payloads in a sandboxed subprocess.
# Supports both KTOx-native payloads and KTOx-compatible payloads.
#
# Payload format (KTOx compatible):
#   - Single Python file (.py)
#   - Drop into /root/KTOx/payloads/<category>/
#   - Uses LCD_1in44 / LCD_Config API (shimmed to our ST7735)
#   - Loot written to /root/KTOx/loot/ is automatically
#     redirected to /root/ktox_loot/payloads/<payload_name>/
#   - KEY3 = exit (universal panic button)
#
# Payload categories (mirrors KTOx):
#   reconnaissance/
#   interception/
#   exfiltration/
#   remote_access/
#   wifi/
#   general/
#   custom/          ← user-added payloads

import os
import sys
import subprocess
import threading
import time
import shutil
import json
from pathlib import Path
from datetime import datetime

KTOX_DIR     = "/root/KTOx"
PAYLOAD_DIR  = f"{KTOX_DIR}/payloads"
LOOT_DIR     = "/root/ktox_loot"
KTOX_LOOT = "/root/KTOx/loot"   # symlinked → ktox_loot/payloads

# Category display names and icons
CATEGORIES = [
    ("reconnaissance", "Recon",       "🔎"),
    ("interception",   "Intercept",   "🕵"),
    ("exfiltration",   "Exfiltrate",  "📤"),
    ("remote_access",  "Remote",      "🔌"),
    ("wifi",           "WiFi",        "📡"),
    ("general",        "General",     "⚙"),
    ("custom",         "Custom",      "🔧"),
]


def setup_payload_dirs():
    """
    Create payload directory structure and set up KTOx loot symlink
    so payloads writing to /root/KTOx/loot/ land in ktox_loot.
    """
    for cat, _, _ in CATEGORIES:
        os.makedirs(f"{PAYLOAD_DIR}/{cat}", exist_ok=True)
    os.makedirs(f"{LOOT_DIR}/payloads", exist_ok=True)

    # Symlink /root/KTOx/loot → /root/ktox_loot/payloads
    # so KTOx payloads writing to their expected path work unmodified
    rj_dir = "/root/KTOx"
    os.makedirs(rj_dir, exist_ok=True)
    rj_loot = f"{rj_dir}/loot"
    if not os.path.exists(rj_loot):
        try:
            os.symlink(f"{LOOT_DIR}/payloads", rj_loot)
        except OSError:
            pass  # already exists or no permission


def get_payloads(category):
    """
    Return list of (name, path, meta) for all .py files in a category.
    Reads optional metadata from first 5 lines of the payload file.
    """
    cat_dir = Path(f"{PAYLOAD_DIR}/{category}")
    if not cat_dir.exists():
        return []

    payloads = []
    for f in sorted(cat_dir.glob("*.py")):
        name = f.stem.replace("_", " ").title()
        desc = ""
        # Read first lines for metadata comments
        try:
            lines = f.read_text(errors="ignore").splitlines()[:8]
            for line in lines:
                line = line.strip()
                if line.startswith("# DESC:"):
                    desc = line[7:].strip()
                elif line.startswith("# NAME:"):
                    name = line[7:].strip()
        except:
            pass
        payloads.append((name, str(f), desc))
    return payloads


def get_payload_env(payload_path):
    """
    Build the environment dict for a payload subprocess.
    Injects the shim directory so LCD_1in44 / LCD_Config resolve correctly.
    Also sets KTOX_PAYLOAD=1 so payloads can detect they're running under KTOx.
    """
    env = os.environ.copy()
    shim_dir = f"{KTOX_DIR}"   # LCD_1in44.py and LCD_Config.py live here
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{shim_dir}:{KTOX_DIR}:{pythonpath}"
    env["KTOX_PAYLOAD"]    = "1"
    env["KTOX_LOOT_DIR"]   = f"{LOOT_DIR}/payloads"
    env["KTOX_ROOT"]  = "/root/KTOx"
    return env


class PayloadRunner:
    """
    Runs a payload as an isolated subprocess.
    Streams stdout to a log file and monitors for completion/crash.
    Provides stop() for KEY3 panic exits.
    """

    def __init__(self):
        self._proc    = None
        self._running = False
        self._log_path= None
        self._thread  = None

    def run(self, payload_path, on_line=None, on_exit=None):
        """
        Launch payload in subprocess.

        payload_path — absolute path to .py file
        on_line(str) — callback for each stdout line (for LCD status updates)
        on_exit(rc)  — callback when payload exits
        """
        name     = Path(payload_path).stem
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        loot_sub = f"{LOOT_DIR}/payloads/{name}"
        os.makedirs(loot_sub, exist_ok=True)

        self._log_path = f"{loot_sub}/{name}_{ts}.log"
        self._running  = True

        env = get_payload_env(payload_path)
        # Pass payload-specific loot dir as env var
        env["PAYLOAD_LOOT_DIR"] = loot_sub

        self._proc = subprocess.Popen(
            ["python3", payload_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            cwd="/root/KTOx"   # match KTOx's working directory
        )

        def _reader():
            try:
                with open(self._log_path, "w") as log:
                    for line in self._proc.stdout:
                        line = line.rstrip()
                        log.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
                        log.flush()
                        if on_line and line:
                            on_line(line)
            except:
                pass
            rc = self._proc.wait()
            self._running = False
            if on_exit:
                on_exit(rc)

        self._thread = threading.Thread(target=_reader, daemon=True)
        self._thread.start()

    def stop(self):
        """Send SIGTERM to payload — mirrors KEY3 panic button behavior."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._running = False

    @property
    def running(self):
        return self._running and (self._proc and self._proc.poll() is None)

    @property
    def log_path(self):
        return self._log_path

    def tail_log(self, lines=10):
        """Return last N lines of payload log."""
        if not self._log_path or not os.path.exists(self._log_path):
            return []
        try:
            all_lines = Path(self._log_path).read_text(errors="ignore").splitlines()
            return all_lines[-lines:]
        except:
            return []
