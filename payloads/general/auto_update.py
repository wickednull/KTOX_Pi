#!/usr/bin/env python3
"""
KTOx_Pi OTA Update — DarkSec Edition
====================================
Pulls the latest KTOx_Pi code, backs up loot, installs deps,
and restarts services. Shows live progress on 1.44" LCD.
"""

import os, sys, time, signal, shutil, tempfile
from pathlib import Path
from datetime import datetime
import subprocess

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False

# ── Constants ─────────────────────────────────────────
KTOX_DIR      = "/root/KTOx"
LOOT_DIR      = KTOX_DIR + "/loot"
BACKUP_DIR    = "/root/ktox_backups"
REPO_URL      = "https://github.com/wickednull/KTOx_Pi.git"
BRANCH        = "main"
WEBUI_SERVICES = ["ktox-device.service", "ktox-webui.service"]

PINS = {"KEY1": 21, "KEY3": 16}
W, H = 128, 128

# ── LCD setup ───────────────────────────────────────
if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)

try:
    FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
    FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
except:
    FONT_SM = FONT_MD = ImageFont.load_default()

# ── Colors ──────────────────────────────────────────
BG        = "#060101"
TEXT      = "#c8c8c8"
GREEN     = "#2ecc71"
YELLOW    = "#f39c12"
RED       = "#8B0000"
RED_BRITE = "#cc1a1a"
DIM       = "#4a2020"

# ── Helpers ─────────────────────────────────────────
def _show(title, lines, status_col=TEXT):
    img  = Image.new("RGB", (W,H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,0,W,11], fill="#0d0000")
    draw.line([0,11,W,11], fill=RED, width=1)
    tw = draw.textbbox((0,0), "KTOx_Pi OTA", font=FONT_SM)[2]
    draw.text(((W-tw)//2,1), "KTOx_Pi OTA", font=FONT_SM, fill=RED_BRITE)
    draw.rectangle([0,12,W,25], fill="#1a0000")
    draw.line([0,25,W,25], fill=RED, width=1)
    tw2 = draw.textbbox((0,0), title, font=FONT_MD)[2]
    draw.text(((W-tw2)//2,14), title, font=FONT_MD, fill=status_col)
    y=29
    for item in lines:
        if isinstance(item, tuple):
            txt,col=item
        else:
            txt,col=str(item),TEXT
        draw.text((4,y,str(txt)[:22]), font=FONT_SM, fill=col)
        y+=12
        if y>110: break
    draw.rectangle([0,117,W,H], fill="#0d0000")
    draw.line([0,117,W,117], fill=RED, width=1)
    if HAS_HW:
        LCD.LCD_ShowImage(img,0,0)

def _btn():
    if not HAS_HW:
        return None
    for name,pin in PINS.items():
        if GPIO.input(pin)==0:
            return name
    return None

def _wait_release():
    if HAS_HW:
        while any(GPIO.input(p)==0 for p in PINS.values()):
            time.sleep(0.05)

def _run(cmd, timeout=120):
    """Run shell command, return (rc, output)."""
    try:
        r=subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd,str))
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "Timeout"
    except Exception as e:
        return -1, str(e)

# ── Update Steps ───────────────────────────────────
def check_internet():
    rc,_=_run(["curl","-s","--connect-timeout","5","-o","/dev/null","https://github.com"], timeout=15)
    return rc==0

def backup_loot():
    if not Path(LOOT_DIR).exists():
        return True,"No loot to backup"
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    dest=f"{BACKUP_DIR}/loot_backup_{ts}"
    try:
        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        shutil.copytree(LOOT_DIR,dest)
        return True,f"Saved to {dest}"
    except Exception as e:
        return False,str(e)

def get_current_version():
    vfile = Path(KTOX_DIR+"/.ktox_version")
    try: return vfile.read_text().strip()
    except: return "unknown"

def get_remote_version():
    rc,out=_run(f"git ls-remote {REPO_URL} refs/heads/{BRANCH}", timeout=15)
    if rc==0 and out: return out.split()[0][:7]
    return "unknown"

def do_git_pull_safe():
    tmp_dir = Path(tempfile.gettempdir())/f"ktox_update_{int(time.time())}"
    tmp_dir.mkdir(exist_ok=True)
    try:
        rc,out=_run(f"git clone --depth=1 -b {BRANCH} {REPO_URL} {tmp_dir}", timeout=180)
        if rc!=0: return False,f"Clone failed: {out}"
        dst=Path(KTOX_DIR)
        exclude=["loot",".ktox_version"]
        rsync_cmd=f'rsync -a --exclude={" --exclude=".join(exclude)} {tmp_dir}/ {dst}/'
        rc,out=_run(rsync_cmd, timeout=120)
        if rc!=0: return False,f"Rsync failed: {out}"
        rc,commit=_run(f"git -C {tmp_dir} rev-parse --short HEAD", timeout=10)
        if rc==0 and commit.strip():
            try: (dst/".ktox_version").write_text(commit.strip()+"\n")
            except: pass
        return True,f"Updated to {commit.strip() if commit else 'unknown'}"
    except Exception as e:
        return False,str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def install_deps():
    req = Path(KTOX_DIR+"/requirements.txt")
    if not req.exists(): return True,"No requirements.txt"
    rc,out=_run(f"pip3 install --break-system-packages -q -r {req}", timeout=180)
    return rc==0,out if rc!=0 else "deps OK"

def restart_services():
    failed=[]
    for svc in WEBUI_SERVICES:
        rc,out=_run(["systemctl","restart",svc], timeout=20)
        if rc!=0: failed.append(svc.split(".")[0])
    try:
        subprocess.Popen(["bash","-c","sleep 6 && systemctl restart ktox.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except: pass
    if failed: return False,"Failed: "+",".join(failed)
    return True,"Services restarting"

# ── Main OTA Flow ──────────────────────────────────
signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

_show("READY", [
    ("KEY1 = Update now", TEXT),
    ("KEY3 = Exit", DIM),
    "",
    (f"Installed: {get_current_version()}", DIM),
    ("github.com/wickednull", DIM),
])

# Wait for KEY1 or KEY3
while True:
    btn=_btn()
    if btn=="KEY3": _show("Cancelled",[("No changes made.",DIM)],status_col=DIM); time.sleep(1.5); sys.exit(0)
    if btn=="KEY1": _wait_release(); break
    time.sleep(0.1)

_show("Checking...",[("Connecting to GitHub…",DIM)])
if not check_internet():
    _show("NO INTERNET",[("Cannot reach GitHub.",YELLOW),("Check network.",TEXT)],status_col=YELLOW)
    time.sleep(4)
    sys.exit(1)

current=get_current_version()
remote=get_remote_version()
if current!="unknown" and remote!="unknown" and current==remote[:7]:
    _show("UP TO DATE",[(f"Version: {current}",GREEN),("Nothing to update.",TEXT)],status_col=GREEN)
    time.sleep(3)
    sys.exit(0)

_show("UPDATE FOUND",[(f"Current: {current}",TEXT),(f"Remote: {remote[:7]}",GREEN),("KEY1=Install",TEXT),("KEY3=Cancel",DIM)],status_col=GREEN)

# Confirm update
deadline=time.time()+30
confirmed=False
while time.time()<deadline:
    btn=_btn()
    if btn=="KEY1": _wait_release(); confirmed=True; break
    if btn=="KEY3": _wait_release(); break
    time.sleep(0.1)
if not confirmed:
    _show("Cancelled",[("No changes made.",DIM)],status_col=DIM)
    time.sleep(1.5)
    sys.exit(0)

# Step: Backup loot
_show("BACKING UP",[("Saving loot…",DIM)])
ok,msg=backup_loot()
_show("BACKING UP",[(("✔ " if ok else "✖ ")+msg,GREEN if ok else YELLOW)])
time.sleep(0.8)

# Step: Git pull / rsync
_show("DOWNLOADING",[("Pulling from GitHub…",DIM),("Please wait…",DIM)])
ok,msg=do_git_pull_safe()
_show("DOWNLOADING",[(("✔ " if ok else "✖ ")+msg,GREEN if ok else YELLOW)])
time.sleep(0.8)

# Step: Install deps
_show("INSTALLING",[("Updating packages…",DIM)])
ok2,msg2=install_deps()
_show("INSTALLING",[(("✔ " if ok2 else "⚠ ")+str(msg2),GREEN if ok2 else YELLOW)])
time.sleep(0.8)

# Step: Restart services
_show("RESTARTING",[("Restarting services…",DIM)])
ok3,msg3=restart_services()
_show("RESTARTING",[(("✔ " if ok3 else "⚠ ")+msg3,GREEN if ok3 else YELLOW)])
time.sleep(2)

_show("DONE",[("Update complete.",GREEN if ok and ok2 else YELLOW),("Restarting services…",TEXT)])
time.sleep(3)
