"""HackRF command wrapper for the KTOX SDR Suite."""

from __future__ import annotations

import shutil
import subprocess
import threading
from glob import glob
from pathlib import Path
from typing import Any


class HackRFManager:
    def __init__(self, runner: Any | None = None):
        self.runner = runner or subprocess
        self._active_process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def tools_available(self) -> dict[str, bool]:
        if self.runner is not subprocess:
            return {
                "hackrf_info": True,
                "hackrf_transfer": True,
                "hackrf_sweep": True,
                "lsusb": True,
            }
        return {
            "hackrf_info": shutil.which("hackrf_info") is not None,
            "hackrf_transfer": shutil.which("hackrf_transfer") is not None,
            "hackrf_sweep": shutil.which("hackrf_sweep") is not None,
            "lsusb": shutil.which("lsusb") is not None,
        }

    def _run(self, args: list[str], timeout: int = 15):
        return self.runner.run(args, timeout=timeout, capture_output=True, text=True, check=False)

    def usb_devices(self) -> dict:
        try:
            result = self._run(["lsusb"], timeout=5)
        except FileNotFoundError:
            return {"available": False, "error": "lsusb not installed", "devices": []}
        except Exception as exc:
            return {"available": False, "error": str(exc), "devices": []}
        text = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        devices = [line.strip() for line in text.splitlines() if line.strip()]
        hackrf = [
            line for line in devices
            if "1d50:6089" in line.lower() or "hackrf" in line.lower() or "openmoko" in line.lower()
        ]
        return {
            "available": result.returncode == 0,
            "devices": devices,
            "hackrf": hackrf,
            "error": "" if result.returncode == 0 else text.strip(),
        }

    def get_info(self) -> dict:
        tools = self.tools_available()
        try:
            result = self._run(["hackrf_info"], timeout=10)
        except FileNotFoundError:
            return {"available": False, "connected": False, "error": "hackrf_info not installed", "tools": tools}
        except Exception as exc:
            return {"available": False, "connected": False, "error": str(exc), "tools": tools}
        text = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0:
            usb = self.usb_devices() if tools.get("lsusb") else {"available": False, "devices": [], "hackrf": []}
            return {
                "available": False,
                "connected": False,
                "error": text.strip() or "hackrf_info failed",
                "raw": text.strip(),
                "tools": tools,
                "usb": usb,
            }
        info = {"available": True, "connected": True, "raw": text.strip(), "tools": tools}
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
        info["usb"] = self.usb_devices() if tools.get("lsusb") else {"available": False, "devices": [], "hackrf": []}
        return info

    def connect(self) -> dict:
        tools = self.tools_available()
        usb = self.usb_devices() if tools.get("lsusb") else {"available": False, "devices": [], "hackrf": []}
        info = self.get_info()
        info["tools"] = tools
        info["usb"] = usb
        info["connected"] = bool(info.get("available"))
        if not tools.get("hackrf_info"):
            info["error"] = "hackrf_info not installed; install the hackrf package"
        elif not info["connected"] and usb.get("hackrf"):
            info["error"] = info.get("error") or "HackRF is visible on USB but libhackrf could not open it"
        elif not info["connected"] and tools.get("lsusb"):
            info["error"] = info.get("error") or "No HackRF USB device found; plug it in and check cable/power"
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
        start_mhz = max(1, int(round(int(start_hz) / 1000000)))
        stop_mhz = max(start_mhz + 1, int(round(int(stop_hz) / 1000000)))
        args = [
            "hackrf_sweep",
            "-f",
            f"{start_mhz}:{stop_mhz}",
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

    def read_iq_samples(
        self,
        frequency: int,
        sample_rate: int = 20000000,
        sample_count: int = 512,
    ) -> dict:
        samples_to_read = max(1, int(sample_count))
        byte_count = samples_to_read * 2
        args = [
            "hackrf_transfer",
            "-r",
            "-",
            "-f",
            str(int(frequency)),
            "-s",
            str(int(sample_rate)),
            "-n",
            str(samples_to_read),
        ]
        try:
            if self.runner is subprocess:
                result = self.runner.run(args, timeout=10, capture_output=True, check=False)
                raw = result.stdout or b""
                err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            else:
                result = self._run(args, timeout=10)
                raw = (result.stdout or "").encode("latin1", errors="ignore")
                err = result.stderr or ""
        except FileNotFoundError:
            return {"ok": False, "error": "hackrf_transfer not installed", "samples": []}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "samples": []}
        if result.returncode != 0:
            return {"ok": False, "error": err or "hackrf_transfer failed", "samples": []}
        samples = [(byte - 256 if byte > 127 else byte) / 128.0 for byte in raw[:byte_count]]
        return {"ok": True, "samples": samples, "bytes": len(raw), "requested_samples": samples_to_read}

    def hardware_test(
        self,
        frequency: int = 2437000000,
        sample_rate: int = 20000000,
    ) -> dict:
        info = self.connect()
        rx = self.read_iq_samples(frequency, sample_rate=sample_rate, sample_count=256)
        sweep_start = max(1000000, int(frequency) - 5000000)
        sweep_stop = min(6000000000, int(frequency) + 5000000)
        sweep = self.run_sweep(sweep_start, sweep_stop, bin_width=1000000)
        return {
            "ok": bool(info.get("connected")) and bool(rx.get("ok")) and bool(sweep.get("ok")),
            "connect": info,
            "rx": {key: value for key, value in rx.items() if key != "samples"},
            "sweep": {
                "ok": sweep.get("ok", False),
                "error": sweep.get("error", ""),
                "stdout_preview": (sweep.get("stdout") or "")[:1000],
            },
        }

    def serial_ports(self) -> dict:
        try:
            from serial.tools import list_ports
        except Exception as exc:
            devices = sorted(set(glob("/dev/ttyUSB*") + glob("/dev/ttyACM*") + glob("/dev/serial/by-id/*")))
            return {
                "available": bool(devices),
                "pyserial": False,
                "error": str(exc),
                "ports": [{"device": device, "description": "serial device"} for device in devices],
            }
        ports = []
        for port in list_ports.comports():
            ports.append(
                {
                    "device": port.device,
                    "name": port.name,
                    "description": port.description,
                    "hwid": port.hwid,
                    "vid": port.vid,
                    "pid": port.pid,
                    "serial_number": port.serial_number,
                    "manufacturer": port.manufacturer,
                    "product": port.product,
                }
            )
        return {"available": bool(ports), "pyserial": True, "ports": ports}

    def serial_probe(self, port: str, baudrate: int = 115200) -> dict:
        if not port:
            return {"ok": False, "error": "serial port is required"}
        try:
            import serial
        except Exception as exc:
            return {"ok": False, "error": f"pyserial unavailable: {exc}"}
        try:
            with serial.Serial(port=port, baudrate=int(baudrate), timeout=0.5, write_timeout=0.5) as handle:
                return {
                    "ok": True,
                    "port": port,
                    "baudrate": int(baudrate),
                    "open": handle.is_open,
                    "in_waiting": int(getattr(handle, "in_waiting", 0)),
                }
        except Exception as exc:
            return {"ok": False, "port": port, "baudrate": int(baudrate), "error": str(exc)}

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
