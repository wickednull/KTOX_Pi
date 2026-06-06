"""HackRF command wrapper for the KTOX SDR Suite."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any


class HackRFManager:
    def __init__(self, runner: Any | None = None):
        self.runner = runner or subprocess
        self._active_process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def tools_available(self) -> dict[str, bool]:
        return {
            "hackrf_info": shutil.which("hackrf_info") is not None,
            "hackrf_transfer": shutil.which("hackrf_transfer") is not None,
            "hackrf_sweep": shutil.which("hackrf_sweep") is not None,
        }

    def _run(self, args: list[str], timeout: int = 15):
        return self.runner.run(args, timeout=timeout, capture_output=True, text=True, check=False)

    def get_info(self) -> dict:
        try:
            result = self._run(["hackrf_info"], timeout=10)
        except FileNotFoundError:
            return {"available": False, "error": "hackrf_info not installed"}
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        text = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0:
            return {"available": False, "error": text.strip() or "hackrf_info failed"}
        info = {"available": True, "raw": text.strip()}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = [part.strip() for part in line.split(":", 1)]
            norm = key.lower().replace(" ", "_")
            if norm == "serial_number":
                info["serial_number"] = value
            elif norm == "board_id_number":
                info["board"] = value
            elif norm == "firmware_version":
                info["firmware"] = value
            elif norm == "part_id_number":
                info["part_id"] = value
        return info

    def capture_iq(
        self,
        output_path: str | Path,
        frequency: int,
        sample_rate: int = 20000000,
        duration_sec: int = 5,
        lna_gain: int = 16,
        vga_gain: int = 20,
    ) -> dict:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        samples = max(1, int(sample_rate) * max(1, int(duration_sec)))
        args = [
            "hackrf_transfer",
            "-r",
            str(output),
            "-f",
            str(int(frequency)),
            "-s",
            str(int(sample_rate)),
            "-n",
            str(samples),
            "-l",
            str(int(lna_gain)),
            "-g",
            str(int(vga_gain)),
        ]
        try:
            result = self._run(args, timeout=max(10, int(duration_sec) + 10))
        except FileNotFoundError:
            return {"ok": False, "error": "hackrf_transfer not installed", "path": str(output)}
        if result.returncode != 0:
            return {"ok": False, "error": (result.stderr or result.stdout or "capture failed").strip(), "path": str(output)}
        return {"ok": True, "path": str(output), "size": output.stat().st_size if output.exists() else 0}

    def transmit_iq(
        self,
        input_path: str | Path,
        frequency: int,
        sample_rate: int = 20000000,
        txvga_gain: int = 0,
        repeat: bool = False,
    ) -> dict:
        source = Path(input_path)
        if not source.exists():
            return {"ok": False, "error": "IQ file not found", "path": str(source)}
        args = [
            "hackrf_transfer",
            "-t",
            str(source),
            "-f",
            str(int(frequency)),
            "-s",
            str(int(sample_rate)),
            "-x",
            str(int(txvga_gain)),
        ]
        if repeat:
            args.append("-R")
        try:
            result = self._run(args, timeout=60)
        except FileNotFoundError:
            return {"ok": False, "error": "hackrf_transfer not installed", "path": str(source)}
        if result.returncode != 0:
            return {"ok": False, "error": (result.stderr or result.stdout or "transmit failed").strip(), "path": str(source)}
        return {"ok": True, "path": str(source)}

    def run_sweep(
        self,
        start_hz: int,
        stop_hz: int,
        bin_width: int = 1000000,
        dwell_ms: int = 100,
    ) -> dict:
        args = [
            "hackrf_sweep",
            "-f",
            f"{int(start_hz)}:{int(stop_hz)}",
            "-w",
            str(int(bin_width)),
            "-1",
        ]
        try:
            result = self._run(args, timeout=60)
        except FileNotFoundError:
            return {"ok": False, "error": "hackrf_sweep not installed", "stdout": ""}
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout or "",
            "error": "" if result.returncode == 0 else (result.stderr or "hackrf_sweep failed"),
        }

    def start_rx_stream(self, args: list[str]) -> subprocess.Popen:
        with self._lock:
            if self._active_process and self._active_process.poll() is None:
                raise RuntimeError("HackRF stream already active")
            self._active_process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return self._active_process

    def stop_active_process(self) -> bool:
        with self._lock:
            proc = self._active_process
            self._active_process = None
        if not proc or proc.poll() is not None:
            return False
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        return True
