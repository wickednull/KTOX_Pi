#!/usr/bin/env python3
"""
KTOx_Pi payload — OTA Update
==============================
Pulls the latest KTOx_Pi from github.com/wickednull/KTOx_Pi,
backs up loot, restarts all three ktox services.

Shows live progress on the 1.44" LCD throughout.

Controls
--------
  KEY1   start update
  KEY3   exit without updating
"""

import os, sys, time, signal, subprocess, shutil
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
BACKUP_DIR   = "/root/ktox_backups"
REPO_URL     = "https://github.com/wickednull/KTOx_Pi.git"
BRANCH       = "main"
WEBUI_SERVICES = ["ktox-device.service", "ktox-webui.service"]

PINS = {"KEY1": 21, "KEY2": 20, "KEY3": 16}
W, H = 128, 128

# ── LCD setup ────────────────────────────────────────────────────────────────

if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

if HAS_HW:
    try:
        FONT_SM = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
        FONT_MD = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
    except Exception:
        FONT_SM = FONT_MD = ImageFont.load_default()
else:
    FONT_SM = FONT_MD = None

RED       = "#8B0000"
RED_BRITE = "#cc1a1a"
BG        = "#060101"
TEXT      = "#c8c8c8"
DIM       = "#4a2020"
GREEN     = "#2ecc71"
YELLOW    = "#f39c12"

# ── Drawing helpers ──────────────────────────────────────────────────────────

def _show(title, lines, status_col=TEXT):
    """Render a status screen. lines = list of (text, colour) or plain str."""
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Top bar
    draw.rectangle([0, 0, W, 11], fill="#0d0000")
    draw.line([0, 11, W, 11], fill=RED, width=1)
    tw = draw.textbbox((0,0), "KTOx_Pi UPDATE", font=FONT_SM)[2]
    draw.text(((W-tw)//2, 1), "KTOx_Pi UPDATE", font=FONT_SM, fill=RED_BRITE)

    # Title
    draw.rectangle([0, 12, W, 25], fill="#1a0000")
    draw.line([0, 25, W, 25], fill=RED, width=1)
    tw2 = draw.textbbox((0,0), title, font=FONT_MD)[2]
    draw.text(((W-tw2)//2, 14), title, font=FONT_MD, fill=status_col)

    # Content lines
    y = 29
    for item in lines:
        if isinstance(item, tuple):
            txt, col = item
        else:
            txt, col = str(item), TEXT
        draw.text((4, y), str(txt)[:22], font=FONT_SM, fill=col)
        y += 12
        if y > 110:
            break

    # Bottom bar
    draw.rectangle([0, 117, W, H], fill="#0d0000")
    draw.line([0, 117, W, 117], fill=RED, width=1)

    if HAS_HW:
        LCD.LCD_ShowImage(img, 0, 0)


def _btn():
    if not HAS_HW:
        return None
    for name, pin in PINS.items():
        if GPIO.input(pin) == 0:
            return name
    return None


def _wait_release():
    if HAS_HW:
        while any(GPIO.input(p) == 0 for p in PINS.values()):
            time.sleep(0.05)


def _run(cmd, timeout=120):
    """Run command, return (returncode, combined_output)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout,
            shell=isinstance(cmd, str)
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "Timeout"
    except Exception as e:
        return -1, str(e)


# ── Update steps ─────────────────────────────────────────────────────────────

def check_internet():
    rc, _ = _run(["curl", "-s", "--connect-timeout", "5",
                  "--max-time", "8", "-o", "/dev/null",
                  "https://github.com"], timeout=15)
    return rc == 0


def backup_loot():
    """Back up loot dir only (not the whole install — that's huge)."""
    if not Path(LOOT_DIR).exists():
        return True, "No loot to back up"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{BACKUP_DIR}/loot_backup_{ts}"
    try:
        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        shutil.copytree(LOOT_DIR, dest)
        return True, f"Saved to {dest}"
    except Exception as e:
        return False, str(e)


def _py_valid(path):
    """Return True if path is a valid Python file (syntax check)."""
    import py_compile
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except Exception:
        return False


def _safe_copy(src_path, dst_path, skipped):
    """
    Copy src_path → dst_path only if the file passes a Python syntax
    check (for .py files).  Broken files are skipped so a bad upstream
    commit can never overwrite a working installation.
    """
    import shutil as _shutil
    if src_path.suffix == ".py" and not _py_valid(src_path):
        skipped.append(src_path.name)
        print(f"[OTA] SKIP {src_path.name}: syntax error in downloaded file")
        return
    _shutil.copy2(src_path, dst_path)


def do_git_pull():
    """
    Clone the latest repo to a temp dir, then copy files into KTOX_DIR
    exactly as install.sh does — preserving the installed file layout.
    A direct git reset --hard would overwrite the flat install structure
    with the raw repo layout, breaking the services.

    Every .py file is syntax-checked before being deployed.  Files that
    fail the check are skipped so a corrupted upstream commit cannot
    overwrite a working installation.
    """
    import shutil as _shutil

    tmp = f"/tmp/ktox_update_{int(time.time())}"
    skipped = []

    try:
        rc, out = _run(
            ["git", "clone", "--depth=1", "--single-branch", "--no-tags",
             "-b", BRANCH, REPO_URL, tmp],
            timeout=300,
        )
        if rc != 0:
            return False, f"Clone failed: {out[:60]}"

        src = Path(tmp)
        dst = Path(KTOX_DIR)

        # Core device files — mirror install.sh priority:
        #   root-level file wins; fall back to ktox_pi/ if absent.
        # This ensures the canonical root version (e.g. with `except Exception`
        # for OSError from spidev) is always what gets deployed, not the older
        # ktox_pi/ variant that only catches ImportError.
        for fname in [
            "ktox_device.py", "LCD_1in44.py", "LCD_Config.py",
            "ktox_lcd.py", "ktox_payload_runner.py",
        ]:
            s = src / fname                    # root-level preferred
            if not s.exists():
                s = src / "ktox_pi" / fname    # fall back to ktox_pi/
            if s.exists():
                _safe_copy(s, dst / fname, skipped)

        # ktox_input.py lives in ktox_pi/; install as both names so that
        # `import ktox_input as rj_input` (root ktox_device.py) and
        # `import rj_input` (older scripts) both work after update.
        ki_src = src / "ktox_pi" / "ktox_input.py"
        if ki_src.exists():
            _safe_copy(ki_src, dst / "ktox_input.py", skipped)
            _safe_copy(ki_src, dst / "rj_input.py",   skipped)

        # Files from repo root → flat into KTOX_DIR
        root_files = [
            "device_server.py", "web_server.py", "nmap_parser.py",
            "scan.py", "spoof.py", "requirements.txt",
            "ktox.py", "ktox_mitm.py", "ktox_advanced.py",
            "ktox_extended.py", "ktox_defense.py", "ktox_stealth.py",
            "ktox_netattack.py", "ktox_wifi.py", "ktox_dashboard.py",
            "ktox_repl.py", "ktox_config.py",
            "ktox_device_pi.py",
            "payload_compat.py",
        ]
        for fname in root_files:
            s = src / fname
            if s.exists():
                _safe_copy(s, dst / fname, skipped)

        # Directories that must never be overwritten — user data lives here
        PRESERVE_DIRS = {
            "roms",        # Game Boy / emulator ROMs uploaded by user
            "loot",        # Captured credentials / scan results
            "screensaver", # User GIF screensavers (img/screensaver/)
        }

        # Directories — replace in-place (keep loot/ and credentials untouched)
        # For payloads/ we do a file-by-file validated copy instead of rmtree+copytree
        # so a single bad file in the repo can't nuke the whole payloads directory.
        for dname in ["web", "wifi", "Responder", "DNSSpoof", "assets", "scripts"]:
            if dname in PRESERVE_DIRS:
                continue
            s = src / dname
            d = dst / dname
            if s.exists():
                if d.exists():
                    _shutil.rmtree(d)
                _shutil.copytree(s, d)

        # payloads/ — validated file-by-file copy, skipping preserve dirs
        src_payloads = src / "payloads"
        dst_payloads = dst / "payloads"
        if src_payloads.exists():
            for src_file in src_payloads.rglob("*"):
                if src_file.is_dir():
                    continue
                rel = src_file.relative_to(src_payloads)
                # Skip any path that passes through a preserved directory name
                if any(part in PRESERVE_DIRS for part in rel.parts):
                    continue
                dst_file = dst_payloads / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                _safe_copy(src_file, dst_file, skipped)

        # img/logo.bmp
        s = src / "img" / "logo.bmp"
        if s.exists():
            (dst / "img").mkdir(exist_ok=True)
            _shutil.copy2(s, dst / "img" / "logo.bmp")

        # Check if requirements.txt changed (while tmp still exists)
        needs_pip = False
        try:
            new_req = (src / "requirements.txt").read_text()
            cur_req_path = dst / "requirements.txt"
            needs_pip = not cur_req_path.exists() or cur_req_path.read_text() != new_req
        except Exception:
            needs_pip = True  # Can't tell — run pip to be safe

        # Record the upstream commit hash for version tracking
        _, commit = _run(["git", "-C", tmp, "rev-parse", "--short", "HEAD"])
        commit = commit.strip()
        try:
            (dst / ".ktox_version").write_text(commit + "\n")
        except Exception:
            pass

        if skipped:
            msg = f"HEAD:{commit} skip:{len(skipped)}"
        else:
            msg = f"HEAD: {commit}"
        return True, msg, needs_pip

    except Exception as e:
        return False, str(e)[:60], False
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def install_deps():
    req = Path(KTOX_DIR + "/requirements.txt")
    if not req.exists():
        return True, "No requirements.txt"
    rc, out = _run(
        ["pip3", "install", "--break-system-packages", "-q",
         "-r", str(req)],
        timeout=300
    )
    return rc == 0, out[:60] if rc != 0 else "deps updated"


def restart_services():
    """
    Restart webUI services (device_server + web_server) immediately.
    Schedule ktox.service (the LCD/menu parent process) to restart after a
    short delay so this script can finish displaying its final screen before
    the parent process is killed and re-spawned.
    """
    failed = []
    for svc in WEBUI_SERVICES:
        rc, out = _run(["systemctl", "restart", svc], timeout=20)
        if rc != 0:
            failed.append(svc.split(".")[0])
    # Delay-restart the menu service so we can show "UPDATE DONE" first
    try:
        subprocess.Popen(
            ["bash", "-c", "sleep 6 && systemctl restart ktox.service"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception:
        pass
    if failed:
        return False, "Failed: " + ",".join(failed)
    return True, "Services restarting"


def get_current_version():
    """Get installed commit hash from version file written by auto_update."""
    vfile = Path(KTOX_DIR + "/.ktox_version")
    try:
        v = vfile.read_text().strip()
        if v:
            return v
    except Exception:
        pass
    return "unknown"


def get_remote_version():
    """Get latest commit hash from GitHub without full fetch."""
    rc, out = _run(
        ["git", "ls-remote", REPO_URL, f"refs/heads/{BRANCH}"],
        timeout=15
    )
    if rc == 0 and out:
        return out.split()[0][:7]
    return "unknown"


# ── Main ─────────────────────────────────────────────────────────────────────

signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

_show("READY", [
    ("KEY1 = Update now", TEXT),
    ("KEY3 = Exit", DIM),
    "",
    (f"Installed: {get_current_version()}", DIM),
    ("github.com/wickednull", DIM),
    ("/KTOx_Pi", DIM),
])

try:
    # Wait for KEY1 or KEY3
    while True:
        btn = _btn()
        if btn == "KEY3":
            _show("Cancelled", [("No changes made.", DIM)], status_col=DIM)
            time.sleep(1.5)
            sys.exit(0)
        if btn == "KEY1":
            _wait_release()
            break
        time.sleep(0.1)

    # ── Step 1: Check internet ────────────────────────────────────────────
    _show("Checking...", [("Connecting to GitHub…", DIM)])
    if not check_internet():
        _show("NO INTERNET", [
            ("Cannot reach GitHub.", YELLOW),
            ("Check your network", TEXT),
            ("and try again.", TEXT),
        ], status_col=YELLOW)
        time.sleep(4)
        sys.exit(1)

    # ── Step 2: Check if update needed ───────────────────────────────────
    current = get_current_version()
    _show("Checking...", [
        (f"Current: {current}", TEXT),
        ("Checking remote…", DIM),
    ])
    remote = get_remote_version()
    if current != "unknown" and remote != "unknown" and current == remote[:7]:
        _show("UP TO DATE", [
            (f"Version: {current}", GREEN),
            ("Nothing to update.", TEXT),
        ], status_col=GREEN)
        time.sleep(3)
        sys.exit(0)

    _show("UPDATE FOUND", [
        (f"Current: {current}", TEXT),
        (f"Remote:  {remote[:7]}", GREEN),
        "",
        ("KEY1 = Install", TEXT),
        ("KEY3 = Cancel", DIM),
    ], status_col=GREEN)

    # Confirm
    deadline = time.time() + 30
    confirmed = False
    while time.time() < deadline:
        btn = _btn()
        if btn == "KEY1":
            _wait_release()
            confirmed = True
            break
        if btn == "KEY3":
            _wait_release()
            break
        time.sleep(0.1)

    if not confirmed:
        _show("Cancelled", [("No changes made.", DIM)], status_col=DIM)
        time.sleep(1.5)
        sys.exit(0)

    # ── Step 3: Backup loot ───────────────────────────────────────────────
    _show("BACKING UP", [("Saving loot…", DIM)])
    ok, msg = backup_loot()
    _show("BACKING UP", [
        (("✔ " if ok else "✖ ") + msg[:20], GREEN if ok else YELLOW)
    ])
    time.sleep(0.8)

    # ── Step 4: Git pull ──────────────────────────────────────────────────
    _show("DOWNLOADING", [
        ("Pulling from GitHub…", DIM),
        ("This may take a", DIM),
        ("minute…", DIM),
    ])
    ok, msg, needs_pip = do_git_pull()
    if not ok:
        _show("UPDATE FAILED", [
            ("Git pull failed:", YELLOW),
            (msg[:22], TEXT),
            "",
            ("Loot is safe.", DIM),
        ], status_col=YELLOW)
        time.sleep(5)
        sys.exit(1)
    _show("DOWNLOADING", [("✔ " + msg, GREEN)])
    time.sleep(0.8)

    # ── Step 5: Install deps (only if requirements.txt changed) ──────────
    if needs_pip:
        _show("INSTALLING", [("Updating packages…", DIM)])
        ok, msg = install_deps()
        _show("INSTALLING", [
            (("✔ " if ok else "⚠ ") + msg[:22], GREEN if ok else YELLOW)
        ])
        time.sleep(0.8)
    else:
        _show("INSTALLING", [("deps unchanged, skip", DIM)])
        time.sleep(0.5)

    # ── Step 6: Restart services ──────────────────────────────────────────
    _show("RESTARTING", [("Restarting services…", DIM)])
    ok, msg = restart_services()

    if ok:
        _show("UPDATE DONE", [
            ("✔ KTOx_Pi updated!", GREEN),
            (f"  {msg}", DIM),
            "",
            ("Restarting now…", TEXT),
        ], status_col=GREEN)
        time.sleep(3)
        # The ktox.service restart will kill this process
    else:
        _show("PARTIAL", [
            (msg[:22], YELLOW),
            ("Manual restart may", TEXT),
            ("be needed.", TEXT),
        ], status_col=YELLOW)
        time.sleep(4)

finally:
    if HAS_HW:
        try:
            GPIO.cleanup()
        except Exception:
            pass
