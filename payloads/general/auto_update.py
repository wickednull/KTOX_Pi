#!/usr/bin/env python3
"""
KTOx_Pi payload - OTA Update
============================
LCD-friendly OTA updater for the device menu.

This file intentionally keeps its own direct LCD/GPIO UI because the KTOX
device menu launches payloads/general/auto_update.py.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime


DIAGNOSE_ONLY = "--diagnose" in sys.argv

KTOX_DIR = "/root/KTOx"
PAYLOADS_DIR = os.path.join(KTOX_DIR, "payloads")
LOOT_DIR = os.path.join(KTOX_DIR, "loot")
BACKUP_DIR = "/root/ktox_backups"
REPO_URL = "https://github.com/wickednull/KTOx_Pi.git"
ARCHIVE_URL = "https://codeload.github.com/wickednull/KTOx_Pi/tar.gz/refs/heads/main"
BRANCH = "main"
REMOTE = "origin"
TIMEOUT = 120
STATUS_LOG = "/tmp/ktox_ota_status.log"
SERVICES = ["ktox", "ktox-device", "ktox-webui", "ktox-sdr"]
REQUIRED_FILES = [
    "install.sh",
    "ktox_device.py",
    "web_server.py",
    "payloads/general/auto_update.py",
    "payloads/utilities/auto_update.py",
]

PINS = {"KEY1": 21, "KEY3": 16}
W, H = 128, 128

HAS_HW = False
if not DIAGNOSE_ONLY:
    try:
        import RPi.GPIO as GPIO
        import LCD_1in44
        import LCD_Config  # noqa: F401
        from PIL import Image, ImageDraw, ImageFont

        HAS_HW = True
    except Exception:
        HAS_HW = False

if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    try:
        FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
        FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 9)
    except Exception:
        FONT_SM = FONT_MD = ImageFont.load_default()
else:
    GPIO = LCD = Image = ImageDraw = ImageFont = None
    FONT_SM = FONT_MD = None

RED = "#8B0000"
RED_BRITE = "#cc1a1a"
BG = "#060101"
TEXT = "#c8c8c8"
DIM = "#4a2020"
GREEN = "#2ecc71"
YELLOW = "#f39c12"


def log_status(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
    try:
        with open(STATUS_LOG, "a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass
    print(message, flush=True)


def _show(title: str, lines: list[str | tuple[str, str]], status_col: str = TEXT) -> None:
    log_status(f"{title}: " + " | ".join(str(item[0] if isinstance(item, tuple) else item) for item in lines))
    if not HAS_HW:
        return

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 11], fill="#0d0000")
    draw.line([0, 11, W, 11], fill=RED, width=1)
    tw = draw.textbbox((0, 0), "KTOx_Pi UPDATE", font=FONT_SM)[2]
    draw.text(((W - tw) // 2, 1), "KTOx_Pi UPDATE", font=FONT_SM, fill=RED_BRITE)

    draw.rectangle([0, 12, W, 25], fill="#1a0000")
    draw.line([0, 25, W, 25], fill=RED, width=1)
    tw2 = draw.textbbox((0, 0), title, font=FONT_MD)[2]
    draw.text(((W - tw2) // 2, 14), title[:20], font=FONT_MD, fill=status_col)

    y = 29
    for item in lines:
        txt, col = item if isinstance(item, tuple) else (str(item), TEXT)
        draw.text((4, y), str(txt)[:22], font=FONT_SM, fill=col)
        y += 12
        if y > 110:
            break

    draw.rectangle([0, 117, W, H], fill="#0d0000")
    draw.line([0, 117, W, 117], fill=RED, width=1)
    LCD.LCD_ShowImage(img, 0, 0)


def _btn() -> str | None:
    if not HAS_HW:
        return None
    for name, pin in PINS.items():
        if GPIO.input(pin) == 0:
            return name
    return None


def _wait_release() -> None:
    if HAS_HW:
        while any(GPIO.input(pin) == 0 for pin in PINS.values()):
            time.sleep(0.05)


def _run(cmd: list[str], *, cwd: str | None = None, timeout: int = TIMEOUT) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        msg = ((result.stderr or "").strip() or (result.stdout or "").strip()).strip()
        return result.returncode, msg
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as exc:
        return 1, str(exc)


def short_msg(msg: str, fallback: str = "") -> str:
    lines = [line.strip() for line in str(msg or fallback).splitlines() if line.strip()]
    return (lines[-1] if lines else fallback)[:120]


def check_space() -> tuple[bool, str]:
    try:
        free = shutil.disk_usage(KTOX_DIR).free // (1024 * 1024)
        return (free >= 100), f"{free} MB free"
    except Exception as exc:
        return False, str(exc)[:80]


def ensure_git_remote() -> tuple[bool, str]:
    if not os.path.isdir(os.path.join(KTOX_DIR, ".git")):
        return False, "missing .git; run manual git clone/reset once"
    _run(["git", "-C", KTOX_DIR, "config", "--global", "--add", "safe.directory", KTOX_DIR], timeout=20)
    rc, url = _run(["git", "-C", KTOX_DIR, "remote", "get-url", REMOTE], timeout=20)
    if rc != 0:
        rc, msg = _run(["git", "-C", KTOX_DIR, "remote", "add", REMOTE, REPO_URL], timeout=20)
        return (rc == 0), (REPO_URL if rc == 0 else short_msg(msg, "remote add failed"))
    if "github.com/wickednull/KTOx_Pi" not in url:
        rc, msg = _run(["git", "-C", KTOX_DIR, "remote", "set-url", REMOTE, REPO_URL], timeout=20)
        return (rc == 0), (REPO_URL if rc == 0 else short_msg(msg, "remote repair failed"))
    return True, url.strip()


def github_probe() -> tuple[bool, str]:
    rc, msg = _run(["git", "ls-remote", "--heads", REPO_URL, BRANCH], timeout=TIMEOUT)
    if rc != 0:
        return False, f"github probe failed: {short_msg(msg, f'rc={rc}')}"
    if f"refs/heads/{BRANCH}" not in msg:
        return False, f"github branch {BRANCH} not found"
    return True, "github reachable"


def download_archive(path: str) -> tuple[bool, str]:
    errors = []
    try:
        request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "KTOX-OTA"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(path, "wb") as handle:
            shutil.copyfileobj(response, handle)
        if os.path.getsize(path) > 0:
            return True, "urllib"
    except Exception as exc:
        errors.append(f"urllib {str(exc)[:80]}")

    for cmd in (
        ["curl", "-L", "-A", "KTOX-OTA", "-o", path, ARCHIVE_URL],
        ["wget", "-O", path, ARCHIVE_URL],
    ):
        rc, msg = _run(cmd, timeout=TIMEOUT)
        if rc == 0 and os.path.isfile(path) and os.path.getsize(path) > 0:
            return True, cmd[0]
        errors.append(f"{cmd[0]} {short_msg(msg, f'rc={rc}')}")
    return False, "; ".join(errors)[-180:]


def find_archive_root(tmp: str) -> str | None:
    for name in os.listdir(tmp):
        candidate = os.path.join(tmp, name)
        if (
            os.path.isdir(candidate)
            and os.path.isfile(os.path.join(candidate, "install.sh"))
            and os.path.isdir(os.path.join(candidate, "payloads"))
            and os.path.isdir(os.path.join(candidate, "web"))
        ):
            return candidate
    return None


def copy_repo_tree(src_root: str, dst_root: str) -> None:
    skip = {".git", "__pycache__", ".agents", ".codex"}
    for name in os.listdir(src_root):
        if name in skip:
            continue
        src = os.path.join(src_root, name)
        dst = os.path.join(dst_root, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def archive_update() -> tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory(prefix="ktox-ota-") as tmp:
            archive = os.path.join(tmp, "main.tar.gz")
            ok, msg = download_archive(archive)
            if not ok:
                return False, f"archive download failed: {msg}"
            with tarfile.open(archive, "r:gz") as tar:
                tmp_abs = os.path.abspath(tmp)
                members = []
                for member in tar.getmembers():
                    target = os.path.abspath(os.path.join(tmp, member.name))
                    if target.startswith(tmp_abs + os.sep):
                        members.append(member)
                tar.extractall(tmp, members=members)
            root = find_archive_root(tmp)
            if not root:
                return False, "archive missing repo root"
            missing = [name for name in REQUIRED_FILES if not os.path.isfile(os.path.join(root, name))]
            if missing:
                return False, f"archive missing {missing[0]}"
            copy_repo_tree(root, KTOX_DIR)
            return True, f"archive fallback OK via {msg}"
    except Exception as exc:
        return False, f"archive fallback failed: {str(exc)[:100]}"


def resolve_fetched_ref() -> tuple[bool, str]:
    for ref in (f"refs/remotes/{REMOTE}/{BRANCH}", "FETCH_HEAD", f"{REMOTE}/{BRANCH}"):
        rc, msg = _run(["git", "-C", KTOX_DIR, "rev-parse", "--verify", f"{ref}^{{commit}}"], timeout=20)
        if rc == 0 and msg:
            return True, msg.splitlines()[-1].strip()
    return False, "fetched ref missing"


def git_update() -> tuple[bool, str]:
    ok, remote_msg = ensure_git_remote()
    if not ok:
        archive_ok, archive_msg = archive_update()
        return (archive_ok, archive_msg if archive_ok else f"{remote_msg}; {archive_msg}")

    rc, msg = _run(["git", "-C", KTOX_DIR, "fetch", "--prune", REMOTE, f"{BRANCH}:refs/remotes/{REMOTE}/{BRANCH}"])
    if rc != 0:
        probe_ok, probe_msg = github_probe()
        archive_ok, archive_msg = archive_update()
        if archive_ok:
            return True, archive_msg
        return False, f"{probe_msg}; fetch failed: {short_msg(msg, f'rc={rc}')}; {archive_msg}"

    ref_ok, fetched_ref = resolve_fetched_ref()
    if not ref_ok:
        archive_ok, archive_msg = archive_update()
        if archive_ok:
            return True, archive_msg
        return False, f"{fetched_ref}; fetch output: {short_msg(msg, 'no fetch output')}; {archive_msg}"

    rc, msg = _run(["git", "-C", KTOX_DIR, "ls-tree", "-r", "--name-only", fetched_ref])
    if rc != 0:
        archive_ok, archive_msg = archive_update()
        if archive_ok:
            return True, archive_msg
        return False, f"tree failed: {short_msg(msg, f'rc={rc}')}; {archive_msg}"
    names = set(msg.splitlines())
    missing = [name for name in REQUIRED_FILES if name not in names]
    if missing:
        return False, f"remote missing {missing[0]} ({remote_msg})"

    rc, msg = _run(["git", "-C", KTOX_DIR, "reset", "--hard", fetched_ref])
    if rc != 0:
        return False, f"reset failed: {short_msg(msg, f'rc={rc}')}"
    return True, "git reset OK"


def backup_loot() -> tuple[bool, str]:
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if not os.path.isdir(LOOT_DIR):
            return True, "no loot"
        dst = os.path.join(BACKUP_DIR, f"loot_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copytree(LOOT_DIR, dst)
        return True, os.path.basename(dst)
    except Exception as exc:
        return False, str(exc)[:100]


def run_installer() -> tuple[bool, str]:
    script = os.path.join(KTOX_DIR, "install.sh")
    if not os.path.isfile(script):
        return False, "install.sh missing"
    rc, msg = _run(["bash", script], cwd=KTOX_DIR, timeout=900)
    return (rc == 0), ("installer OK" if rc == 0 else short_msg(msg, f"installer rc={rc}"))


def restart_services() -> tuple[bool, str]:
    failed = []
    for service in SERVICES:
        rc, _ = _run(["systemctl", "list-unit-files", f"{service}.service"], timeout=20)
        if rc != 0:
            continue
        rc, msg = _run(["systemctl", "restart", service], timeout=60)
        if rc != 0:
            failed.append(f"{service}: {short_msg(msg, f'rc={rc}')}")
    return (not failed), ("services OK" if not failed else "; ".join(failed)[:120])


def diagnose() -> list[str]:
    lines = ["KTOX OTA diagnostics"]
    ok, remote = ensure_git_remote()
    lines.append(f"remote: {'ok' if ok else 'fail'} {remote}")
    probe_ok, probe_msg = github_probe()
    lines.append(f"github: {'ok' if probe_ok else 'fail'} {probe_msg}")
    rc, branch = _run(["git", "-C", KTOX_DIR, "branch", "--show-current"], timeout=20)
    lines.append(f"branch: {branch if rc == 0 else short_msg(branch, f'rc={rc}')}")
    rc, head = _run(["git", "-C", KTOX_DIR, "rev-parse", "--short", "HEAD"], timeout=20)
    lines.append(f"head: {head if rc == 0 else short_msg(head, f'rc={rc}')}")
    for name in REQUIRED_FILES:
        lines.append(f"file {name}: {'ok' if os.path.isfile(os.path.join(KTOX_DIR, name)) else 'missing'}")
    lines.append(f"log: {STATUS_LOG}")
    return lines


def run_update() -> None:
    _show("CHECKING", [("Checking disk...", DIM)])
    ok, msg = check_space()
    if not ok:
        _show("NO SPACE", [(msg, YELLOW)], YELLOW)
        time.sleep(4)
        return

    _show("BACKUP", [("Saving loot...", DIM)])
    ok, msg = backup_loot()
    if not ok:
        _show("BACKUP FAILED", [(msg, YELLOW)], YELLOW)
        time.sleep(4)
        return

    _show("UPDATING", [("Fetching GitHub...", DIM), ("Fallback enabled", TEXT)])
    ok, msg = git_update()
    if not ok:
        _show("UPDATE FAILED", [(msg[:22], YELLOW), (msg[22:44], TEXT), (msg[44:66], TEXT)], YELLOW)
        time.sleep(6)
        return

    _show("INSTALLING", [(msg, GREEN), ("Running install.sh", DIM)])
    ok, msg = run_installer()
    if not ok:
        _show("INSTALL FAILED", [(msg[:22], YELLOW), (msg[22:44], TEXT), (msg[44:66], TEXT)], YELLOW)
        time.sleep(6)
        return

    _show("RESTARTING", [("Restarting services", DIM)])
    ok, msg = restart_services()
    if not ok:
        _show("RESTART WARN", [(msg[:22], YELLOW), ("Reboot still advised", TEXT)], YELLOW)
        time.sleep(4)

    _show("UPDATE DONE", [("KTOx_Pi updated", GREEN), ("Reboot now", TEXT)])
    time.sleep(2)
    _run(["sync"], timeout=20)
    _run(["systemctl", "reboot"], timeout=20)


def main() -> int:
    if DIAGNOSE_ONLY:
        for line in diagnose():
            print(line)
        return 0

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    _show("OTA UPDATE", [("KEY1 = Update now", TEXT), ("KEY3 = Exit", TEXT), ("github.com/wickednull", DIM)])

    try:
        if not HAS_HW:
            run_update()
            return 0
        while True:
            btn = _btn()
            if btn == "KEY1":
                _wait_release()
                run_update()
                return 0
            if btn == "KEY3":
                _wait_release()
                return 0
            time.sleep(0.1)
    finally:
        if HAS_HW:
            try:
                LCD.LCD_Clear()
            except Exception:
                pass
            try:
                GPIO.cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
