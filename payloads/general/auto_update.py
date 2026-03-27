#!/usr/bin/env python3
"""
KTOx_Pi payload — OTA Update
==============================
Downloads the latest KTOx_Pi zip from GitHub and installs it,
preserving your loot folder throughout.

Uses GitHub's zip download — no git required, always works.

Controls
--------
  KEY1   start update
  KEY3   exit without updating
"""

import os, sys, time, signal, shutil, zipfile, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ── Constants ────────────────────────────────────────────────────────────────

KTOX_DIR     = "/root/KTOx"
LOOT_DIR     = KTOX_DIR + "/loot"
TMP_DIR      = "/tmp/ktox_update"
BACKUP_DIR   = "/root/ktox_backups"
SERVICES     = ["ktox.service", "ktox-device.service", "ktox-webui.service"]

# GitHub zip download URL — always gets latest main branch
ZIP_URL   = "https://github.com/wickednull/KTOx_Pi/archive/refs/heads/main.zip"
# API URL to check latest commit without downloading
API_URL   = "https://api.github.com/repos/wickednull/KTOx_Pi/commits/main"

PINS = {"KEY1": 21, "KEY2": 20, "KEY3": 16}
W, H = 128, 128

# ── LCD setup ────────────────────────────────────────────────────────────────

if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

try:
    FONT_SM = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
    FONT_MD = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
except Exception:
    FONT_SM = FONT_MD = ImageFont.load_default()

RED       = "#8B0000"
RED_BRT   = "#cc1a1a"
BG        = "#060101"
TEXT      = "#c8c8c8"
DIM       = "#4a2020"
GREEN     = "#2ecc71"
YELLOW    = "#f39c12"

# ── Drawing ──────────────────────────────────────────────────────────────────

def _show(title, lines, status_col=TEXT):
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,0,W,11],  fill="#0d0000")
    draw.line([0,11,W,11],      fill=RED, width=1)
    tw = draw.textbbox((0,0), "KTOx_Pi UPDATE", font=FONT_SM)[2]
    draw.text(((W-tw)//2, 1),   "KTOx_Pi UPDATE", font=FONT_SM, fill=RED_BRT)
    draw.rectangle([0,12,W,25], fill="#1a0000")
    draw.line([0,25,W,25],      fill=RED, width=1)
    tw2 = draw.textbbox((0,0), title, font=FONT_MD)[2]
    draw.text(((W-tw2)//2, 14), title, font=FONT_MD, fill=status_col)
    y = 29
    for item in lines:
        txt, col = (item[0], item[1]) if isinstance(item, tuple) else (str(item), TEXT)
        draw.text((4, y), str(txt)[:22], font=FONT_SM, fill=col)
        y += 12
        if y > 112: break
    draw.rectangle([0,117,W,H], fill="#0d0000")
    draw.line([0,117,W,117],    fill=RED, width=1)
    if HAS_HW:
        LCD.LCD_ShowImage(img, 0, 0)


def _btn():
    if not HAS_HW: return None
    for name, pin in PINS.items():
        if GPIO.input(pin) == 0:
            return name
    return None


def _wait_release():
    if HAS_HW:
        while any(GPIO.input(p) == 0 for p in PINS.values()):
            time.sleep(0.05)


def _run(cmd, timeout=120):
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, shell=isinstance(cmd, str))
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)


# ── Update logic ─────────────────────────────────────────────────────────────

def check_internet():
    try:
        urllib.request.urlopen("https://github.com", timeout=8)
        return True
    except Exception:
        return False


def get_remote_sha():
    """Get latest commit SHA from GitHub API."""
    try:
        req = urllib.request.Request(
            API_URL,
            headers={"Accept": "application/vnd.github.v3+json",
                     "User-Agent": "KTOx_Pi-OTA"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            import json
            data = json.loads(r.read().decode())
            return data.get("sha", "")[:7]
    except Exception:
        return "unknown"


def get_local_sha():
    """Get SHA from local version file if it exists."""
    ver_file = Path(KTOX_DIR + "/.version")
    if ver_file.exists():
        return ver_file.read_text().strip()[:7]
    return "unknown"


def backup_loot():
    if not Path(LOOT_DIR).exists():
        return True, "No loot to back up"
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{BACKUP_DIR}/loot_{ts}"
    try:
        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        shutil.copytree(LOOT_DIR, dest)
        return True, f"Saved to {dest}"
    except Exception as e:
        return False, str(e)


def download_zip(progress_cb=None):
    """Download the repo zip from GitHub to /tmp/ktox_update.zip"""
    os.makedirs(TMP_DIR, exist_ok=True)
    zip_path = TMP_DIR + "/ktox_update.zip"
    try:
        req = urllib.request.Request(
            ZIP_URL,
            headers={"User-Agent": "KTOx_Pi-OTA"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 8192
            with open(zip_path, "wb") as f:
                while True:
                    data = r.read(chunk)
                    if not data:
                        break
                    f.write(data)
                    downloaded += len(data)
                    if progress_cb and total:
                        progress_cb(downloaded, total)
        return True, zip_path
    except Exception as e:
        return False, str(e)


def install_from_zip(zip_path):
    """
    Extract zip, copy files over /root/KTOx preserving loot/.
    The zip extracts as KTOx_Pi-main/ — map that to /root/KTOx/
    """
    extract_dir = TMP_DIR + "/extracted"
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir)

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
    except Exception as e:
        return False, f"Extract failed: {e}"

    # Find the extracted folder (GitHub names it KTOx_Pi-main)
    entries = os.listdir(extract_dir)
    if not entries:
        return False, "Empty zip"
    src_dir = os.path.join(extract_dir, entries[0])
    if not os.path.isdir(src_dir):
        return False, "Bad zip structure"

    # Copy everything over, preserving loot/ and .webui_* files
    preserve = {"loot", ".webui_token", ".webui_session_secret",
                ".webui_auth.json", ".version"}
    try:
        for item in os.listdir(src_dir):
            if item in preserve:
                continue
            src  = os.path.join(src_dir, item)
            dest = os.path.join(KTOX_DIR, item)
            if os.path.isdir(src):
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)

        # Write version file with commit SHA
        sha = get_remote_sha()
        Path(KTOX_DIR + "/.version").write_text(sha)
        return True, f"Installed ({sha})"
    except Exception as e:
        return False, f"Copy failed: {e}"


def install_deps():
    req = Path(KTOX_DIR + "/requirements.txt")
    if not req.exists():
        return True, "No requirements.txt"
    rc, out = _run(["pip3", "install", "--break-system-packages",
                    "-q", "-r", str(req)], timeout=180)
    return rc == 0, "deps OK" if rc == 0 else out[:60]


def restart_services():
    failed = []
    for svc in SERVICES:
        rc, _ = _run(["systemctl", "restart", svc], timeout=20)
        if rc != 0:
            failed.append(svc.split(".")[0])
    return (False, "Failed: " + ",".join(failed)) if failed else (True, "All restarted")


def cleanup():
    try:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    except Exception:
        pass


# ── Main ─────────────────────────────────────────────────────────────────────

signal.signal(signal.SIGINT,  lambda *_: cleanup() or sys.exit(0))
signal.signal(signal.SIGTERM, lambda *_: cleanup() or sys.exit(0))

local_sha  = get_local_sha()
_show("READY", [
    ("KEY1 = Update now", TEXT),
    ("KEY3 = Exit",       DIM),
    "",
    (f"Installed: {local_sha}", DIM),
    ("wickednull/KTOx_Pi", DIM),
])

try:
    # Wait for KEY1 or KEY3
    while True:
        btn = _btn()
        if btn == "KEY3":
            _show("Cancelled", [("No changes made.", DIM)], DIM)
            time.sleep(1.5)
            sys.exit(0)
        if btn == "KEY1":
            _wait_release()
            break
        time.sleep(0.1)

    # Step 1: Internet check
    _show("Checking...", [("Connecting to GitHub…", DIM)])
    if not check_internet():
        _show("NO INTERNET", [
            ("Cannot reach GitHub.", YELLOW),
            ("Check network.", TEXT),
        ], YELLOW)
        time.sleep(4)
        sys.exit(1)

    # Step 2: Check version
    _show("Checking...", [
        (f"Local:  {local_sha}", TEXT),
        ("Checking remote…", DIM),
    ])
    remote_sha = get_remote_sha()

    if (local_sha != "unknown" and remote_sha != "unknown"
            and local_sha == remote_sha[:7]):
        _show("UP TO DATE", [
            (f"Version: {local_sha}", GREEN),
            ("Nothing to update.", TEXT),
        ], GREEN)
        time.sleep(3)
        sys.exit(0)

    _show("UPDATE FOUND", [
        (f"Local:  {local_sha}", TEXT),
        (f"Remote: {remote_sha[:7]}", GREEN),
        "",
        ("KEY1 = Install", TEXT),
        ("KEY3 = Cancel",  DIM),
    ], GREEN)

    # Confirm
    confirmed = False
    deadline  = time.time() + 30
    while time.time() < deadline:
        btn = _btn()
        if btn == "KEY1": _wait_release(); confirmed = True; break
        if btn == "KEY3": _wait_release(); break
        time.sleep(0.1)

    if not confirmed:
        _show("Cancelled", [("No changes made.", DIM)], DIM)
        time.sleep(1.5)
        sys.exit(0)

    # Step 3: Backup loot
    _show("BACKING UP", [("Saving loot…", DIM)])
    ok, msg = backup_loot()
    _show("BACKING UP", [("✔ " + msg[:20] if ok else "✖ " + msg[:20],
                           GREEN if ok else YELLOW)])
    time.sleep(0.8)

    # Step 4: Download zip with live progress
    _pct = [0]
    def _progress(dl, total):
        _pct[0] = int(dl * 100 / total)

    _show("DOWNLOADING", [("Downloading zip…", DIM), ("This may take a min", DIM)])

    # Run download in thread so we can update screen
    import threading
    result = [None, None]
    def _dl():
        result[0], result[1] = download_zip(_progress)
    t = threading.Thread(target=_dl)
    t.start()
    while t.is_alive():
        _show("DOWNLOADING", [
            (f"Progress: {_pct[0]}%", TEXT),
            ("Downloading…", DIM),
        ])
        time.sleep(1)
    t.join()
    ok, zip_path = result

    if not ok:
        _show("DOWNLOAD FAILED", [
            (zip_path[:22], YELLOW),
            ("Check internet.", TEXT),
        ], YELLOW)
        time.sleep(5)
        cleanup()
        sys.exit(1)
    _show("DOWNLOADING", [("✔ Download complete", GREEN)])
    time.sleep(0.5)

    # Step 5: Install
    _show("INSTALLING", [("Extracting files…", DIM)])
    ok, msg = install_from_zip(zip_path)
    if not ok:
        _show("INSTALL FAILED", [(msg[:22], YELLOW)], YELLOW)
        time.sleep(5)
        cleanup()
        sys.exit(1)
    _show("INSTALLING", [("✔ " + msg[:22], GREEN)])
    time.sleep(0.5)

    # Step 6: Deps
    _show("INSTALLING", [("Updating packages…", DIM)])
    ok, msg = install_deps()
    _show("INSTALLING", [("✔ " + msg[:22] if ok else "⚠ " + msg[:22],
                           GREEN if ok else YELLOW)])
    time.sleep(0.5)

    # Step 7: Restart services
    _show("RESTARTING", [("Restarting services…", DIM)])
    ok, msg = restart_services()

    _show("UPDATE DONE" if ok else "PARTIAL", [
        ("✔ KTOx_Pi updated!" if ok else "⚠ " + msg[:22],
         GREEN if ok else YELLOW),
        (msg if ok else "Manual restart may", DIM),
        ("" if ok else "be needed.", DIM),
    ], GREEN if ok else YELLOW)
    cleanup()
    time.sleep(4)

finally:
    cleanup()
    if HAS_HW:
        try: GPIO.cleanup()
        except Exception: pass
