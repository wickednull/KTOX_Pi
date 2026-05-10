#!/usr/bin/env python3
"""Small LCD/button/runtime helpers for KTOx payloads.

The payloads in this tree are launched from the 1.44" LCD menu, but they also
need to survive development hosts where GPIO/LCD modules are not importable.
This module keeps that boundary in one place so payload scripts can focus on
what they actually do.
"""

from __future__ import annotations

import importlib
import importlib.util
import fcntl
import os
import pty
import re
import struct
import termios
import signal
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

PINS = {"UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16}
WIDTH = 128
HEIGHT = 128


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def loot_dir(*parts: str) -> Path:
    path = Path(os.environ.get("KTOX_LOOT_DIR", str(repo_root() / "loot"))).joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


class LCDUI:
    """LCD renderer with a console fallback for non-Pi test environments."""

    def __init__(self, title: str):
        self.title = title
        self.gpio = None
        self.lcd_mod = None
        self.lcd = None
        self.image_mod = None
        self.draw_mod = None
        self.font = None
        self.enabled = False
        self.last_console = 0.0
        self._last_button_time = 0.0
        self._init_hardware()

    def _init_hardware(self) -> None:
        if str(repo_root()) not in sys.path:
            sys.path.insert(0, str(repo_root()))
        if not (_module_available("PIL") and _module_available("LCD_1in44") and _module_available("RPi")):
            return
        try:
            self.gpio = importlib.import_module("RPi.GPIO")
            self.lcd_mod = importlib.import_module("LCD_1in44")
            self.image_mod = importlib.import_module("PIL.Image")
            self.draw_mod = importlib.import_module("PIL.ImageDraw")
            font_mod = importlib.import_module("PIL.ImageFont")

            self.gpio.setmode(self.gpio.BCM)
            for pin in PINS.values():
                self.gpio.setup(pin, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)
            self.lcd = self.lcd_mod.LCD()
            self.lcd.LCD_Init(self.lcd_mod.SCAN_DIR_DFT)
            self.font = font_mod.load_default()
            self.enabled = True
        except (ImportError, RuntimeError, OSError) as exc:
            print(f"[WARN] LCD unavailable: {exc}", file=sys.stderr)
            self.enabled = False
            self.gpio = None
            self.lcd_mod = None
            self.lcd = None
            self.image_mod = None
            self.draw_mod = None
            self.font = None

    def close(self) -> None:
        if self.enabled and self.lcd:
            try:
                self.lcd.LCD_Clear()
            except Exception:
                pass
        if self.gpio:
            try:
                self.gpio.cleanup()
            except Exception:
                pass

    def pressed(self, name: str, debounce: float = 0.18) -> bool:
        if not (self.enabled and self.gpio):
            return False
        if name not in PINS:
            return False
        now = time.monotonic()
        if now - self._last_button_time < debounce:
            return False
        try:
            if self.gpio.input(PINS[name]) == 0:
                self._last_button_time = now
                return True
        except Exception:
            return False
        return False

    def draw_lines(self, title: str, lines: Sequence[str], footer: str = "KEY3=Exit") -> None:
        cleaned = [strip_ansi(str(line)).strip() for line in lines if str(line).strip()]
        if self.enabled and self.lcd and self.image_mod and self.draw_mod:
            img = self.image_mod.new("RGB", (WIDTH, HEIGHT), (7, 0, 0))
            draw = self.draw_mod.Draw(img)
            draw.rectangle((0, 0, WIDTH, 13), fill=(70, 0, 0))
            draw.text((3, 2), title[:18], font=self.font, fill=(255, 80, 80))
            y = 16
            for line in cleaned[-8:]:
                draw.text((2, y), line[:21], font=self.font, fill=(238, 238, 238))
                y += 12
            draw.rectangle((0, 116, WIDTH, 127), fill=(28, 0, 0))
            draw.text((3, 118), footer[:21], font=self.font, fill=(180, 180, 180))
            try:
                self.lcd.LCD_ShowImage(img, 0, 0)
            except Exception:
                pass
            return
        now = time.monotonic()
        if now - self.last_console > 1.0:
            print(f"[{title}] " + " | ".join(cleaned[-4:]))
            self.last_console = now

    def menu(self, title: str, items: Sequence[str], footer: str = "OK=Sel KEY3=Back") -> Optional[int]:
        if not items:
            self.draw_lines(title, ["No items"], "KEY3=Back")
            time.sleep(1)
            return None
        if not self.enabled:
            print(f"[{title}] console fallback; selecting first item: {items[0]}")
            return 0
        selected = 0
        top = 0
        while True:
            visible = list(items[top:top + 7])
            decorated = [("▶ " if top + idx == selected else "  ") + item for idx, item in enumerate(visible)]
            self.draw_lines(title, decorated, footer)
            if self.pressed("UP"):
                selected = (selected - 1) % len(items)
            elif self.pressed("DOWN"):
                selected = (selected + 1) % len(items)
            elif self.pressed("OK") or self.pressed("KEY1"):
                return selected
            elif self.pressed("KEY3"):
                return None
            if selected < top:
                top = selected
            elif selected >= top + 7:
                top = selected - 6
            time.sleep(0.05)


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "")


def append_limited(buffer: List[str], text: str, limit: int = 160) -> None:
    for raw_line in strip_ansi(text).splitlines():
        line = raw_line.strip()
        if line:
            buffer.append(line)
    del buffer[:-limit]


def terminate_process(proc: Optional[subprocess.Popen], timeout: float = 3.0) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=timeout)
        return
    except Exception:
        pass
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def command_result_line(code: Optional[int], stopped: bool = False) -> str:
    if stopped:
        return "Stopped by user"
    if code == 0:
        return "Done"
    if code is None:
        return "Stopped"
    return f"Failed rc={code}"


def _set_pty_size(fd: int, rows: int = 24, cols: int = 100) -> None:
    size = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, size)


def _send_pty(fd: Optional[int], text: str) -> None:
    if fd is None:
        return
    try:
        os.write(fd, text.encode())
    except OSError:
        pass


def run_pty_command(ui: LCDUI, title: str, cmd: Sequence[str], footer: str = "KEY3=Stop") -> int:
    """Run an interactive terminal command while rendering its output on the LCD.

    Some tools, notably Wifite2, check that stdout is a TTY and/or prompt from a
    terminal even in mostly automated modes.  A normal PIPE makes those tools
    exit immediately (often with rc=0), which looked like a crash on the LCD.
    This helper gives the child a real PTY but keeps the LCD/button controls.
    """
    lines = ["$ " + " ".join(cmd)]
    master_fd: Optional[int] = None
    proc: Optional[subprocess.Popen] = None
    stopped = False
    try:
        master_fd, slave_fd = pty.openpty()
        _set_pty_size(slave_fd)
        proc = subprocess.Popen(
            list(cmd),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            text=False,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, os.O_NONBLOCK)
        while proc.poll() is None:
            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master_fd, 4096)
                except BlockingIOError:
                    chunk = b""
                except OSError:
                    chunk = b""
                if chunk:
                    append_limited(lines, chunk.decode("utf-8", errors="replace"))
            ui.draw_lines(title, lines[-8:] or ["Running..."], footer)
            if ui.pressed("KEY3"):
                stopped = True
                append_limited(lines, "Stopping...")
                _send_pty(master_fd, "q\n")
                time.sleep(0.3)
                terminate_process(proc)
                break
            if ui.pressed("OK") or ui.pressed("KEY1"):
                _send_pty(master_fd, "\r")
            elif ui.pressed("UP"):
                _send_pty(master_fd, "\x1b[A")
            elif ui.pressed("DOWN"):
                _send_pty(master_fd, "\x1b[B")
            time.sleep(0.02)
        while master_fd is not None:
            ready, _, _ = select.select([master_fd], [], [], 0)
            if not ready:
                break
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            append_limited(lines, chunk.decode("utf-8", errors="replace"))
        code = proc.wait(timeout=1) if proc.poll() is None else proc.returncode
        append_limited(lines, command_result_line(code, stopped))
        ui.draw_lines(title, lines[-8:], "OK=Done KEY3=Back")
        wait_for_ack(ui)
        return int(code or 0)
    except FileNotFoundError:
        ui.draw_lines("Missing", [cmd[0], "not installed"], "KEY3=Back")
        time.sleep(2)
        return 127
    except Exception as exc:
        ui.draw_lines("Error", [str(exc)[:42]], "KEY3=Back")
        time.sleep(2)
        return 1
    finally:
        terminate_process(proc)
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass


def run_streaming_command(ui: LCDUI, title: str, cmd: Sequence[str], footer: str = "KEY3=Stop", cwd: Optional[Path] = None) -> int:
    lines = ["$ " + " ".join(cmd)]
    ui.draw_lines(title, lines, footer)
    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )
        assert proc.stdout is not None
        while proc.poll() is None:
            ready, _, _ = select.select([proc.stdout], [], [], 0.1)
            if ready:
                line = proc.stdout.readline()
                if line:
                    append_limited(lines, line)
            ui.draw_lines(title, lines or ["Running..."], footer)
            if ui.pressed("KEY3"):
                append_limited(lines, "Stopping...")
                terminate_process(proc)
                break
        remainder = proc.stdout.read() if proc.stdout else ""
        if remainder:
            append_limited(lines, remainder)
        code = proc.wait(timeout=1) if proc.poll() is None else proc.returncode
        append_limited(lines, command_result_line(code))
        ui.draw_lines(title, lines[-8:], "OK=Done KEY3=Back")
        wait_for_ack(ui)
        return int(code or 0)
    except FileNotFoundError:
        ui.draw_lines("Missing", [cmd[0], "not installed"], "KEY3=Back")
        time.sleep(2)
        return 127
    except Exception as exc:
        ui.draw_lines("Error", [str(exc)[:42]], "KEY3=Back")
        time.sleep(2)
        return 1
    finally:
        terminate_process(proc)


def wait_for_ack(ui: LCDUI, seconds: float = 2.0) -> None:
    if not ui.enabled:
        return
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if ui.pressed("OK") or ui.pressed("KEY3") or ui.pressed("KEY1"):
            return
        time.sleep(0.05)


def wifi_interfaces() -> List[str]:
    interfaces: List[str] = []
    try:
        result = subprocess.run(["iw", "dev"], capture_output=True, text=True, timeout=3)
        interfaces.extend(re.findall(r"Interface\s+(\S+)", result.stdout))
    except Exception:
        pass
    for netdev in Path("/sys/class/net").glob("*"):
        name = netdev.name
        if name.startswith(("wl", "wlan")) and name not in interfaces:
            interfaces.append(name)
    return sorted(interfaces)


def default_gateway() -> Optional[str]:
    try:
        result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=2)
        match = re.search(r"default via (\S+)", result.stdout)
        return match.group(1) if match else None
    except Exception:
        return None


def local_cidrs() -> List[str]:
    cidrs: List[str] = []
    try:
        result = subprocess.run(["ip", "-o", "-4", "addr", "show", "scope", "global"], capture_output=True, text=True, timeout=2)
        cidrs.extend(re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", result.stdout))
    except Exception:
        pass
    if not cidrs:
        cidrs.append("192.168.1.0/24")
    return cidrs


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")
