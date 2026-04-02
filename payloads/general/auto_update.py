#!/usr/bin/env python3
"""
KTOx_Pi Payload — OTA Update
==============================
Pulls the latest KTOx_Pi from GitHub, backs up loot, installs deps, and restarts services.

Controls
--------
  KEY1 = Start update
  KEY3 = Exit without updating
"""

import os, sys, time, signal, subprocess, shutil
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ── Constants ────────────────────────────────────────────────────────────────
KTOX_DIR      = "/root/KTOx"
LOOT_DIR      = KTOX_DIR + "/loot"
BACKUP_DIR    = "/root/ktox_backups"
REPO_URL      = "https://github.com/wickednull/KTOx_Pi.git"
BRANCH        = "main"
WEBUI_SERVICES = ["ktox-device.service", "ktox-webui.service"]

PINS = {"KEY1": 21, "KEY3": 16}
W, H = 128, 128

# ── LCD setup ───────────────────────────────────────────────────────────────
if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

try:
    FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
    FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
except Exception:
    FONT_SM = FONT_MD = ImageFont.load_default()

# ── Colors ────────────────────────────────────────────────────────────────
RED       = "#8B0000"
RED_BRITE = "#cc1a1a"
BG        = "#060101"
TEXT      = "#c8c8c8"
DIM       = "#4a2020"
GREEN     = "#2ecc71"
YELLOW    = "#f39c12"

# ── Helpers ────────────────────────────────────────────────────────────────
def _show(title, lines, status_col=TEXT):
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # Top bar
    draw.rectangle([0,0,W,11], fill="#0d0000")
    draw.line([0,11,W,11], fill=RED, width=1)
    tw = draw.textbbox((0,0), "KTOx_Pi UPDATE", font=FONT_SM)[2]
    draw.text(((W-tw)//2, 1), "KTOx_Pi UPDATE", font=FONT_SM, fill=RED_BRITE)
    # Title
    draw.rectangle([0,12,W,25], fill="#1a0000")
    draw.line([0,25,W,25], fill=RED, width=1)
    tw2 = draw.textbbox((0,0), title, font=FONT_MD)[2]
    draw.text(((W-tw2)//2, 14), title, font=FONT_MD, fill=status_col)
    # Content lines
    y = 29
    for item in lines:
        if isinstance(item, tuple):
            txt, col = item
        else:
            txt, col = str(item), TEXT
        draw.text((4,y), str(txt)[:22], font=FONT_SM, fill=col)
        y += 12
        if y > 110: break
    # Bottom bar
    draw.rectangle([0,117,W,H], fill="#0d0000")
    draw.line([0,117,W,117], fill=RED, width=1)
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
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, shell=isinstance(cmd,str))
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "Timeout"
    except Exception as e:
        return -1, str(e)

# ── Update steps ──────────────────────────────────────────────────────────
def check_internet():
    rc, _ = _run(["curl","-s","--connect-timeout","5","-o","/dev/null","https://github.com"], timeout=15)
    return rc == 0

def backup_loot():
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

def do_git_pull():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ktox_update_")
    try:
        rc, out = _run(f"git clone --depth=1 -b {BRANCH} {REPO_URL} {tmp}", timeout=150)
        if rc != 0: return False, f"Clone failed: {out[:60]}"
        src, dst = Path(tmp), Path(KTOX_DIR)
        # Copy core files only
        for fname in ["ktox_device.py","LCD_1in44.py","LCD_Config.py","rj_input.py","ktox_lcd.py","ktox_payload_runner.py"]:
            s = src/"ktox_pi"/fname
            if s.exists(): shutil.copy2(s,dst/fname)
        return True, "Git pull OK"
    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def install_deps():
    req = Path(KTOX_DIR+"/requirements.txt")
    if not req.exists(): return True, "No requirements.txt"
    rc, out = _run(f"pip3 install --break-system-packages -q -r {req}", timeout=180)
    return rc == 0, out[:60] if rc!=0 else "Deps OK"

def restart_services():
    failed = []
    for svc in WEBUI_SERVICES:
        rc, _ = _run(f"systemctl restart {svc}", timeout=20)
        if rc != 0: failed.append(svc)
    # Schedule parent service restart
    try:
        subprocess.Popen(["bash","-c","sleep 5 && systemctl restart ktox.service"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except Exception: pass
    if failed:
        return False, "Failed: "+",".join(failed)
    return True, "Services restarting"

def get_current_version():
    vfile = Path(KTOX_DIR+"/.ktox_version")
    try:
        v = vfile.read_text().strip()
        return v if v else "unknown"
    except Exception:
        return "unknown"

def get_remote_version():
    rc, out = _run(f"git ls-remote {REPO_URL} refs/heads/{BRANCH}", timeout=15)
    if rc==0 and out: return out.split()[0][:7]
    return "unknown"

# ── Main ────────────────────────────────────────────────────────────────
signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

_show("READY", [("KEY1 = Update now", TEXT),("KEY3 = Exit", DIM),
                "",(f"Installed: {get_current_version()}", DIM)])

try:
    while True:
        btn = _btn()
        if btn=="KEY3":
            _show("Cancelled",[("No changes made.",DIM)], status_col=DIM)
            time.sleep(1.5)
            sys.exit(0)
        if btn=="KEY1":
            _wait_release()
            break
        time.sleep(0.1)

    _show("Checking...", [("Connecting to GitHub…", DIM)])
    if not check_internet():
        _show("NO INTERNET",[("Cannot reach GitHub.",YELLOW),("Check network",TEXT)], status_col=YELLOW)
        time.sleep(4)
        sys.exit(1)

    current, remote = get_current_version(), get_remote_version()
    if current!="unknown" and remote!="unknown" and current==remote[:7]:
        _show("UP TO DATE", [(f"Version: {current}", GREEN),("Nothing to update.",TEXT)], status_col=GREEN)
        time.sleep(3)
        sys.exit(0)

    _show("UPDATE FOUND", [(f"Current: {current}", TEXT),(f"Remote: {remote[:7]}", GREEN),
                           ("", ""),("KEY1 = Install", TEXT),("KEY3 = Cancel", DIM)], status_col=GREEN)

    # Confirm
    deadline, confirmed = time.time()+30, False
    while time.time()<deadline:
        btn = _btn()
        if btn=="KEY1": _wait_release(); confirmed=True; break
        if btn=="KEY3": _wait_release(); break
        time.sleep(0.1)

    if not confirmed:
        _show("Cancelled",[("No changes made.",DIM)], status_col=DIM)
        time.sleep(1.5)
        sys.exit(0)

    # Backup loot
    _show("BACKING UP",[("Saving loot…",DIM)])
    ok, msg = backup_loot()
    _show("BACKING UP", [(("✔ " if ok else "✖ ")+msg[:22], GREEN if ok else YELLOW)])
    time.sleep(0.8)

    # Git pull
    _show("DOWNLOADING",[("Pulling from GitHub…",DIM),("This may take a minute…",DIM)])
    ok, msg = do_git_pull()
    if not ok:
        _show("UPDATE FAILED",[("Git pull failed:",YELLOW),(msg[:22],TEXT),("Loot safe.",DIM)], status_col=YELLOW)
        time.sleep(5)
        sys.exit(1)
    _show("DOWNLOADING",[("✔ "+msg,GREEN)])
    time.sleep(0.8)

    # Install deps
    _show("INSTALLING",[("Updating packages…",DIM)])
    ok, msg = install_deps()
    _show("INSTALLING", [(("✔ " if ok else "⚠ ")+msg[:22], GREEN if ok else YELLOW)])
    time.sleep(0.8)

    # Restart services
    _show("RESTARTING",[("Restarting services…",DIM)])
    ok, msg = restart_services()
    if ok:
        _show("UPDATE DONE",[("✔ KTOx_Pi updated!",GREEN),(f"{msg}",DIM),("", ""),("Restarting…",TEXT)], status_col=GREEN)
        time.sleep(3)
    else:
        _show("PARTIAL", [(msg[:22],YELLOW),("Manual restart may",TEXT),("be needed.",TEXT)], status_col=YELLOW)
        time.sleep(4)

finally:
    if HAS_HW:
        try: GPIO.cleanup()
        except Exception: pass
