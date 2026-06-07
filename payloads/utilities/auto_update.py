#!/usr/bin/env python3
"""
RaspyJack *payload* – Auto-Update (LCD-friendly)
===============================================
Backs-up the current **/root/KTOx** folder, pulls the latest changes
from GitHub and restarts the *raspyjack* systemd service – while showing a
simple progress UI on the 1.44-inch LCD.

Controls
--------
* **KEY1**  - launch update immediately.
* **KEY3**  - abort and return to menu.

After update, it runs:
  /root/KTOx/install.sh
then reboots (after LCD/GPIO cleanup).
"""

# ---------------------------------------------------------------------------
# 0) Imports & path tweak
# ---------------------------------------------------------------------------
import os, sys, time, signal, subprocess, tarfile, shutil, tempfile, urllib.request
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
DIAGNOSE_ONLY = "--diagnose" in sys.argv

# ---------------------------- Third-party libs ----------------------------
if not DIAGNOSE_ONLY:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    from _display_helper import ScaledDraw

    # Shared input helper (WebUI virtual + GPIO)
    from _input_helper import get_button
else:
    GPIO = LCD_1in44 = LCD_Config = Image = ImageDraw = ImageFont = ScaledDraw = None
    get_button = None

# ---------------------------------------------------------------------------
# 1) Constants
# ---------------------------------------------------------------------------
RASPYJACK_DIR   = "/root/KTOx"
PAYLOADS_DIR    = "/root/KTOx/payloads"
BACKUP_DIR      = "/root"
SERVICE_NAMES   = ["ktox", "ktox-device", "ktox-webui", "ktox-sdr"]
GIT_REMOTE      = "origin"
GIT_BRANCH      = "main"
DEFAULT_GIT_URL = "https://github.com/wickednull/KTOx_Pi.git"
DEFAULT_ARCHIVE_URL = "https://codeload.github.com/wickednull/KTOx_Pi/tar.gz/refs/heads/main"
GIT_TIMEOUT     = 120
INSTALL_SCRIPT  = "/root/KTOx/install.sh"
REQUIRED_SDR_FILES = [
    "services/sdr_server.py",
    "sdr/device.py",
    "sdr/diagnostics.py",
    "sdr/demod.py",
    "sdr/receiver.py",
    "sdr/signals.py",
    "sdr/trunking.py",
    "static/sdr/index.html",
    "tools/validate_sdr_suite.py",
    "scripts/install_sdr.sh",
]

PINS = {"KEY1": 21, "KEY3": 16}

# ---------------------------------------------------------------------------
# 2) Hardware init
# ---------------------------------------------------------------------------
if not DIAGNOSE_ONLY:
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values():
        GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD.LCD_Clear()

    WIDTH, HEIGHT = LCD.width, LCD.height
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(10 * LCD_1in44.LCD_SCALE))
else:
    LCD = None
    WIDTH = HEIGHT = 0
    FONT = None

# ---------------------------------------------------------------------------
# 3) Helper to show centred text
# ---------------------------------------------------------------------------

def show(lines, *, invert=False, spacing=2):
    if isinstance(lines, str):
        lines = lines.split("\n")
    bg = "white" if invert else "black"
    fg = "black" if invert else "#00FF00"
    img  = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ScaledDraw(img)
    sizes = [draw.textbbox((0, 0), l, font=FONT)[2:] for l in lines]
    total_h = sum(h + spacing for _, h in sizes) - spacing
    y = (HEIGHT - total_h) // 2
    for line, (w, h) in zip(lines, sizes):
        x = (WIDTH - w) // 2
        draw.text((x, y), line, font=FONT, fill=fg)
        y += h + spacing
    LCD.LCD_ShowImage(img, 0, 0)

# ---------------------------------------------------------------------------
# 4) Button helper
# ---------------------------------------------------------------------------

def pressed() -> str | None:
    if DIAGNOSE_ONLY:
        return None
    return get_button(PINS, GPIO)

# ---------------------------------------------------------------------------
# 5) Core update logic
# ---------------------------------------------------------------------------

def backup() -> tuple[bool, str]:
    """Create a timestamped tar.gz containing Raspyjack."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive = os.path.join(BACKUP_DIR, f"ktox_backup_{ts}.tar.gz")
    try:
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(RASPYJACK_DIR, arcname=os.path.basename(RASPYJACK_DIR))
        if os.path.exists(archive) and os.path.getsize(archive) > 0:
            return True, archive
        return False, "backup empty"
    except Exception as exc:
        return False, str(exc)

def check_space(min_mb: int = 200) -> tuple[bool, str]:
    try:
        usage = shutil.disk_usage(BACKUP_DIR)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < min_mb:
            return False, f"low space: {free_mb}MB"
        return True, f"{free_mb}MB free"
    except Exception as exc:
        return False, f"disk {exc}"

def ensure_dependencies() -> tuple[bool, str]:
    """Install missing dependencies via apt when needed."""
    cmd_map = {
        "git": "git",
        "tar": "tar",
        "systemctl": "systemd",
        "nmap": "nmap",
        "tcpdump": "tcpdump",
        "arp-scan": "arp-scan",
        "ettercap": "ettercap-text-only",
        "php": "php",
        "tshark": "tshark",
        "dnsmasq": "dnsmasq",
        "airmon-ng": "aircrack-ng",
        "aireplay-ng": "aircrack-ng",
        "airodump-ng": "aircrack-ng",
    }
    missing_cmds = [c for c in cmd_map if shutil.which(c) is None]
    missing_pkgs = sorted({cmd_map[c] for c in missing_cmds})

    py_pkgs = {
        "evdev": "python3-evdev",
        "requests": "python3-requests",
        "PIL": "python3-pil",
        "RPi": "python3-rpi.gpio",
        "netifaces": "python3-netifaces",
        "scapy": "python3-scapy",
        "pyudev": "python3-pyudev",
    }
    missing_py = []
    try:
        import importlib
        for mod, pkg in py_pkgs.items():
            try:
                importlib.import_module(mod)
            except Exception:
                missing_py.append(pkg)
    except Exception:
        pass

    to_install = sorted(set(missing_pkgs + missing_py))
    if to_install:
        try:
            subprocess.run(["apt-get", "update", "-qq"], check=True)
            subprocess.run(["apt-get", "install", "-y", "--no-install-recommends"] + to_install, check=True)
        except subprocess.CalledProcessError as exc:
            return False, f"apt failed {exc.returncode}"

    return True, "ok"

def backup_payloads() -> tuple[bool, str]:
    """Copy current payloads to a temp dir for restore after update."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dst = f"/tmp/ktox_payloads_backup_{ts}"
    try:
        if not os.path.isdir(PAYLOADS_DIR):
            return False, "payloads dir missing"
        shutil.copytree(PAYLOADS_DIR, dst)
        return True, dst
    except Exception as exc:
        return False, str(exc)

def restore_custom_payloads(backup_dir: str) -> tuple[bool, str]:
    """Restore only payloads that are not present in the repo version."""
    try:
        if not os.path.isdir(backup_dir):
            return False, "payloads backup missing"
        os.makedirs(PAYLOADS_DIR, exist_ok=True)
        current = set(os.listdir(PAYLOADS_DIR))
        restored = 0
        for name in os.listdir(backup_dir):
            if name.startswith("."):
                continue
            src = os.path.join(backup_dir, name)
            dst = os.path.join(PAYLOADS_DIR, name)
            if name not in current and os.path.isfile(src):
                shutil.copy2(src, dst)
                restored += 1
        return True, f"restored {restored}"
    except Exception as exc:
        return False, str(exc)

def _short_git_error(result: subprocess.CompletedProcess | None = None, fallback: str = "") -> str:
    if result is None:
        return fallback[:160]
    msg = ((result.stderr or "").strip() or (result.stdout or "").strip() or fallback).strip()
    lines = [line.strip() for line in msg.splitlines() if line.strip()]
    return (lines[-1] if lines else fallback)[:160]

def _git(args: list[str], *, check: bool = False, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", RASPYJACK_DIR, *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

def ensure_git_remote() -> tuple[bool, str]:
    """Ensure the OTA checkout has a usable origin remote and safe.directory entry."""
    try:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", RASPYJACK_DIR],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        remote = _git(["remote", "get-url", GIT_REMOTE], check=False, timeout=20)
        url = (remote.stdout or "").strip()
        if remote.returncode != 0 or not url:
            added = _git(["remote", "add", GIT_REMOTE, DEFAULT_GIT_URL], check=False, timeout=20)
            if added.returncode != 0:
                set_url = _git(["remote", "set-url", GIT_REMOTE, DEFAULT_GIT_URL], check=False, timeout=20)
                if set_url.returncode != 0:
                    return False, f"remote repair failed: {_short_git_error(set_url)}"
            return True, DEFAULT_GIT_URL
        return True, url
    except subprocess.TimeoutExpired:
        return False, "git remote check timed out"
    except Exception as exc:
        return False, f"git remote check failed: {exc}"

def github_probe(remote_url: str) -> tuple[bool, str]:
    """Probe GitHub independently so fetch failures are not mislabeled as no internet."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote_url or DEFAULT_GIT_URL, GIT_BRANCH],
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "github probe timed out"
    except Exception as exc:
        return False, f"github probe failed: {exc}"
    if result.returncode != 0:
        return False, f"github probe failed: {_short_git_error(result, 'ls-remote failed')}"
    if f"refs/heads/{GIT_BRANCH}" not in (result.stdout or ""):
        return False, f"github branch {GIT_BRANCH} not found"
    return True, "github reachable"

def _copy_repo_tree(src_root: str, dst_root: str) -> None:
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

def _download_archive(archive: str) -> tuple[bool, str]:
    errors = []
    try:
        request = urllib.request.Request(DEFAULT_ARCHIVE_URL, headers={"User-Agent": "KTOX-OTA"})
        with urllib.request.urlopen(request, timeout=GIT_TIMEOUT) as response, open(archive, "wb") as handle:
            shutil.copyfileobj(response, handle)
        if os.path.getsize(archive) > 0:
            return True, "urllib"
        errors.append("urllib empty archive")
    except Exception as exc:
        errors.append(f"urllib {str(exc)[:80]}")

    for command in (
        ["curl", "-L", "-A", "KTOX-OTA", "-o", archive, DEFAULT_ARCHIVE_URL],
        ["wget", "-O", archive, DEFAULT_ARCHIVE_URL],
    ):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=GIT_TIMEOUT)
        except FileNotFoundError:
            errors.append(f"{command[0]} missing")
            continue
        except subprocess.TimeoutExpired:
            errors.append(f"{command[0]} timed out")
            continue
        if result.returncode == 0 and os.path.isfile(archive) and os.path.getsize(archive) > 0:
            return True, command[0]
        errors.append(f"{command[0]} {_short_git_error(result, 'download failed')}")
    return False, "; ".join(errors)[-240:]

def _find_archive_root(tmp: str) -> str | None:
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

def archive_update() -> tuple[bool, str]:
    """Fallback update path for devices where GitHub works but git fetch does not."""
    try:
        with tempfile.TemporaryDirectory(prefix="ktox-ota-") as tmp:
            archive = os.path.join(tmp, "main.tar.gz")
            download_ok, download_msg = _download_archive(archive)
            if not download_ok:
                return False, f"archive download failed: {download_msg}"
            with tarfile.open(archive, "r:gz") as tar:
                def safe_members():
                    tmp_abs = os.path.abspath(tmp)
                    for member in tar.getmembers():
                        target = os.path.abspath(os.path.join(tmp, member.name))
                        if target.startswith(tmp_abs + os.sep):
                            yield member
                tar.extractall(tmp, members=safe_members())
            root = _find_archive_root(tmp)
            if not root:
                return False, "archive missing repo root"
            missing_remote = [name for name in REQUIRED_SDR_FILES if not os.path.isfile(os.path.join(root, name))]
            if missing_remote:
                return False, f"archive missing {missing_remote[0]}"
            _copy_repo_tree(root, RASPYJACK_DIR)
            missing_local = [name for name in REQUIRED_SDR_FILES if not os.path.isfile(os.path.join(RASPYJACK_DIR, name))]
            if missing_local:
                return False, f"archive local missing {missing_local[0]}"
            return True, f"archive fallback OK via {download_msg}"
    except Exception as exc:
        return False, f"archive fallback failed: {str(exc)[:120]}"

def git_update() -> tuple[bool, str]:
    """Fast-forward pull the latest changes."""
    try:
        ok, remote_url = ensure_git_remote()
        if not ok:
            return False, remote_url
        fetch = _git(
            ["fetch", "--prune", GIT_REMOTE, f"{GIT_BRANCH}:refs/remotes/{GIT_REMOTE}/{GIT_BRANCH}"],
            check=False,
            timeout=GIT_TIMEOUT,
        )
        if fetch.returncode != 0:
            probe_ok, probe_msg = github_probe(remote_url)
            fetch_msg = _short_git_error(fetch, f"git fetch rc={fetch.returncode}")
            if not probe_ok:
                archive_ok, archive_msg = archive_update()
                if archive_ok:
                    return True, archive_msg
                return False, f"{probe_msg}; fetch failed: {fetch_msg}; {archive_msg}"
            archive_ok, archive_msg = archive_update()
            if archive_ok:
                return True, archive_msg
            return False, f"fetch failed: {fetch_msg}; {archive_msg}"
        tree = _git(["ls-tree", "-r", "--name-only", f"{GIT_REMOTE}/{GIT_BRANCH}"], check=True, timeout=GIT_TIMEOUT)
        names = set((tree.stdout or "").splitlines())
        missing_remote = [name for name in REQUIRED_SDR_FILES if name not in names]
        if missing_remote:
            return False, f"remote missing {missing_remote[0]} ({remote_url})"
        _git(["reset", "--hard", f"{GIT_REMOTE}/{GIT_BRANCH}"], check=True, timeout=GIT_TIMEOUT)
        missing_local = [name for name in REQUIRED_SDR_FILES if not os.path.isfile(os.path.join(RASPYJACK_DIR, name))]
        if missing_local:
            head = _git(["rev-parse", "--short", "HEAD"], check=False, timeout=20)
            return False, f"local missing {missing_local[0]} after {(head.stdout or '').strip()}"
        return True, "OK"
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or "").strip() or f"git error {exc.returncode}"
        return False, msg
    except subprocess.TimeoutExpired:
        return False, "git update timed out"

def diagnose_git_update() -> list[str]:
    lines = ["KTOX OTA diagnostics"]
    ok, remote_url = ensure_git_remote()
    lines.append(f"remote: {'ok' if ok else 'fail'} {remote_url}")
    if ok:
        probe_ok, probe_msg = github_probe(remote_url)
        lines.append(f"github: {'ok' if probe_ok else 'fail'} {probe_msg}")
    branch = _git(["branch", "--show-current"], check=False, timeout=20)
    lines.append(f"branch: {(branch.stdout or '').strip() or _short_git_error(branch, 'unknown')}")
    head = _git(["rev-parse", "--short", "HEAD"], check=False, timeout=20)
    lines.append(f"head: {(head.stdout or '').strip() or _short_git_error(head, 'unknown')}")
    remote_head = _git(["rev-parse", "--short", f"{GIT_REMOTE}/{GIT_BRANCH}"], check=False, timeout=20)
    lines.append(f"remote-head: {(remote_head.stdout or '').strip() or _short_git_error(remote_head, 'not fetched')}")
    missing_local = [name for name in REQUIRED_SDR_FILES if not os.path.isfile(os.path.join(RASPYJACK_DIR, name))]
    lines.append(f"required-files: {'ok' if not missing_local else 'missing ' + missing_local[0]}")
    return lines

def restart_service() -> tuple[bool, str]:
    for svc in SERVICE_NAMES:
        try:
            exists = subprocess.run(
                ["systemctl", "list-unit-files", f"{svc}.service", "--no-legend"],
                check=False, capture_output=True, text=True
            )
            if svc == "ktox-sdr" and not (exists.stdout or "").strip():
                continue
            subprocess.run(["systemctl", "restart", svc], check=True)
        except subprocess.CalledProcessError as exc:
            return False, f"{svc} {exc.returncode}"
    return True, "restarted"

def run_install_script() -> tuple[bool, str]:
    """Run /root/KTOx/install.sh before reboot."""
    if not os.path.isfile(INSTALL_SCRIPT):
        return False, "install script missing"
    if not os.access(INSTALL_SCRIPT, os.X_OK):
        return False, "install script not executable"
    try:
        res = subprocess.run(
            ["bash", INSTALL_SCRIPT],
            cwd=RASPYJACK_DIR,
            capture_output=True,
            text=True
        )
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "").strip()
            err = err.splitlines()[-1] if err else f"rc={res.returncode}"
            return False, err[:120]
        return True, "ok"
    except Exception as exc:
        return False, str(exc)[:120]

def do_reboot_now() -> tuple[bool, str]:
    try:
        subprocess.run(["sync"], check=False)
        subprocess.run(["systemctl", "reboot"], check=True)
        return True, "rebooting"
    except Exception as exc:
        return False, str(exc)

# ---------------------------------------------------------------------------
# 6) Main
# ---------------------------------------------------------------------------

if DIAGNOSE_ONLY:
    for line in diagnose_git_update():
        print(line)
    raise SystemExit(0)

running = True
should_reboot = False

signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

show(["Auto-Update", "KEY1: start", "KEY3: exit"])

try:
    while running:
        btn = pressed()
        if btn == "KEY1":
            while pressed() == "KEY1":
                time.sleep(0.05)

            # 0. Prechecks
            ok, info = check_space()
            if not ok:
                show(["No space", info], invert=True); time.sleep(4); break

            ok, info = ensure_dependencies()
            if not ok:
                show(["Deps install", info], invert=True); time.sleep(4); break

            # 1. Backup
            show(["Backing-up…"])
            ok, info = backup()
            if not ok:
                show(["Backup failed", info], invert=True); time.sleep(4); break

            # 1b. Backup payloads for restore
            show(["Saving payloads…"])
            ok, payloads_backup = backup_payloads()
            if not ok:
                show(["Payload save fail", payloads_backup], invert=True); time.sleep(4); break

            # 2. Pull latest
            show(["Updating…"])
            ok, info = git_update()
            if not ok:
                show(["Update failed", info], invert=True); time.sleep(4); break

            # 2b. Restore custom payloads
            show(["Restoring payloads…"])
            ok, info = restore_custom_payloads(payloads_backup)
            if not ok:
                show(["Restore failed", info], invert=True); time.sleep(4); break

            # 3. Restart service
            show(["Restarting…"])
            ok, info = restart_service()
            if not ok:
                show(["Restart failed", info], invert=True); time.sleep(4); break

            # 4. Re-run installer BEFORE reboot
            show(["Running installer…"])
            ok, info = run_install_script()
            if not ok:
                show(["Install failed", info], invert=True); time.sleep(5); break

            show(["Update done!", "Reboot…"])
            time.sleep(1.5)

            should_reboot = True
            running = False

        elif btn == "KEY3":
            running = False
        else:
            time.sleep(0.1)
finally:
    try:
        LCD.LCD_Clear()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass

# reboot AFTER cleanup
if should_reboot:
    do_reboot_now()
