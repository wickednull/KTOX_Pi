"""Capture, sweep, and preset helpers for the KTOX SDR Suite."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any
from typing import Iterable


def build_capture_path(captures_dir: str | Path, frequency: int, suffix: str = "iq") -> Path:
    root = Path(captures_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_suffix = "".join(ch for ch in suffix if ch.isalnum() or ch in ("-", "_")) or "iq"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"ktox_{safe_suffix}_{int(frequency)}hz_{timestamp}.bin"
    path = (root / filename).resolve()
    if path.parent != root:
        raise ValueError("capture path escaped capture root")
    return path


def capture_metadata(path: str | Path, frequency: int, sample_rate: int, notes: str = "") -> dict:
    target = Path(path)
    return {
        "filename": target.name,
        "frequency": int(frequency),
        "sample_rate": int(sample_rate),
        "size": target.stat().st_size if target.exists() else 0,
        "notes": notes,
    }


class PresetStore:
    """Stores user-defined receiver presets."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def list(self, category: str | None = None, query: str = "") -> list[dict[str, Any]]:
        rows = self._read()
        if category:
            wanted = category.strip().lower()
            rows = [row for row in rows if str(row.get("category") or "custom").lower() == wanted]
        if query:
            needle = query.strip().lower()
            rows = [row for row in rows if needle in json.dumps(row, sort_keys=True).lower()]
        return sorted(rows, key=lambda row: (str(row.get("category") or "custom"), str(row.get("label") or ""), int(row.get("frequency") or 0)))

    def categories(self) -> list[str]:
        return sorted({str(row.get("category") or "custom") for row in self._read()})

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        frequency = int(payload.get("frequency") or 0)
        if frequency <= 0:
            raise ValueError("frequency is required")
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "label": str(payload.get("label") or f"Custom {frequency} Hz"),
            "frequency": frequency,
            "mode": str(payload.get("mode") or "nfm").lower(),
            "bandwidth": int(payload.get("bandwidth") or 12500),
            "sample_rate": int(payload.get("sample_rate") or 2000000),
            "step": int(payload.get("step") or 12500),
            "category": str(payload.get("category") or "custom").strip().lower() or "custom",
            "notes": str(payload.get("notes") or ""),
            "created_at": float(payload.get("created_at") or time.time()),
        }
        rows = [item for item in self._read() if item.get("id") != row["id"]]
        rows.append(row)
        self._write(rows)
        return row

    def delete(self, preset_id: str) -> bool:
        rows = self._read()
        kept = [item for item in rows if item.get("id") != preset_id]
        if len(kept) == len(rows):
            return False
        self._write(kept)
        return True

    def export_json(self) -> str:
        return json.dumps({"schema": "ktox-sdr-custom-presets-v1", "custom_presets": self.list()}, indent=2, sort_keys=True) + "\n"

    def import_json(self, payload: str | dict[str, Any]) -> dict[str, Any]:
        data = json.loads(payload) if isinstance(payload, str) else payload
        rows = data.get("custom_presets") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError("custom_presets list is required")
        imported = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            self.add(row)
            imported += 1
        return {"ok": True, "imported": imported}


def get_frequency_presets() -> dict:
    return {
        "weather": {
            "label": "NOAA Weather",
            "mode": "nfm",
            "bandwidth": 12500,
            "sample_rate": 2000000,
            "step": 25000,
            "frequencies": [
                {"label": "WX 1", "hz": 162550000},
                {"label": "WX 2", "hz": 162400000},
                {"label": "WX 3", "hz": 162475000},
                {"label": "WX 4", "hz": 162425000},
                {"label": "WX 5", "hz": 162450000},
                {"label": "WX 6", "hz": 162500000},
                {"label": "WX 7", "hz": 162525000},
            ],
        },
        "airband": {
            "label": "Airband",
            "mode": "am",
            "bandwidth": 25000,
            "sample_rate": 2000000,
            "step": 25000,
            "frequencies": [
                {"label": "Emergency 121.500", "hz": 121500000},
                {"label": "Civil Airband", "start": 118000000, "stop": 137000000},
                {"label": "Military UHF Air", "start": 225000000, "stop": 400000000},
            ],
        },
        "marine": {
            "label": "Marine VHF",
            "mode": "nfm",
            "bandwidth": 12500,
            "sample_rate": 2000000,
            "step": 25000,
            "frequencies": [
                {"label": "CH 16 Distress", "hz": 156800000},
                {"label": "CH 9 Calling", "hz": 156450000},
                {"label": "AIS 1", "hz": 161975000, "mode": "raw", "bandwidth": 25000},
                {"label": "AIS 2", "hz": 162025000, "mode": "raw", "bandwidth": 25000},
            ],
        },
        "rail": {
            "label": "Railroad",
            "mode": "nfm",
            "bandwidth": 12500,
            "sample_rate": 2000000,
            "step": 12500,
            "frequencies": [
                {"label": "AAR 160-161 MHz", "start": 160215000, "stop": 161565000},
                {"label": "EOT 457.9375", "hz": 457937500},
                {"label": "HOT 452.9375", "hz": 452937500},
            ],
        },
        "ham_2m": {
            "label": "Ham Radio 2m",
            "mode": "nfm",
            "bandwidth": 12500,
            "sample_rate": 2000000,
            "step": 5000,
            "frequencies": [
                {"label": "2m Calling", "hz": 146520000},
                {"label": "2m Repeaters", "start": 144000000, "stop": 148000000},
                {"label": "APRS", "hz": 144390000},
            ],
        },
        "ham_70cm": {
            "label": "Ham Radio 70cm",
            "mode": "nfm",
            "bandwidth": 12500,
            "sample_rate": 2000000,
            "step": 12500,
            "frequencies": [
                {"label": "70cm Calling", "hz": 446000000},
                {"label": "70cm Repeaters", "start": 420000000, "stop": 450000000},
                {"label": "DMR Hotspot", "hz": 433450000, "mode": "raw"},
            ],
        },
        "public_safety": {
            "label": "Public Safety",
            "mode": "nfm",
            "bandwidth": 12500,
            "sample_rate": 2000000,
            "step": 12500,
            "frequencies": [
                {"label": "VHF Public Safety", "start": 150000000, "stop": 174000000},
                {"label": "UHF Public Safety", "start": 450000000, "stop": 470000000},
                {"label": "700 MHz Public Safety", "start": 769000000, "stop": 775000000, "mode": "raw", "bandwidth": 12500},
                {"label": "800 MHz Public Safety", "start": 851000000, "stop": 869000000, "mode": "raw", "bandwidth": 12500},
            ],
        },
        "fm": {
            "label": "FM Broadcast",
            "mode": "wfm",
            "bandwidth": 180000,
            "sample_rate": 2400000,
            "step": 200000,
            "frequencies": [
                {"label": "88-108 MHz", "start": 88000000, "stop": 108000000},
                {"label": "Local 88.1", "hz": 88100000},
                {"label": "Local 98.1", "hz": 98100000},
                {"label": "Local 107.9", "hz": 107900000},
            ],
        },
        "adsb": {
            "label": "ADS-B",
            "mode": "raw",
            "bandwidth": 2000000,
            "sample_rate": 2000000,
            "step": 1000000,
            "frequencies": [{"label": "1090ES", "hz": 1090000000}],
        },
        "ais": {
            "label": "AIS",
            "mode": "raw",
            "bandwidth": 25000,
            "sample_rate": 2000000,
            "step": 25000,
            "frequencies": [
                {"label": "AIS 1", "hz": 161975000},
                {"label": "AIS 2", "hz": 162025000},
            ],
        },
        "ism_433": {
            "label": "ISM 433 MHz",
            "mode": "raw",
            "bandwidth": 200000,
            "sample_rate": 2000000,
            "step": 25000,
            "frequencies": [
                {"label": "433.920", "hz": 433920000},
                {"label": "433 ISM Band", "start": 433050000, "stop": 434790000},
            ],
        },
        "ism_915": {
            "label": "ISM 915 MHz",
            "mode": "raw",
            "bandwidth": 500000,
            "sample_rate": 2000000,
            "step": 100000,
            "frequencies": [
                {"label": "915 Center", "hz": 915000000},
                {"label": "902-928 MHz", "start": 902000000, "stop": 928000000},
            ],
        },
        "wifi_2g": {
            "label": "WiFi 2.4 GHz",
            "mode": "raw",
            "bandwidth": 20000000,
            "sample_rate": 20000000,
            "step": 5000000,
            "frequencies": [
                {"label": f"CH {channel}", "hz": 2407000000 + channel * 5000000}
                for channel in range(1, 14)
            ],
        },
        "bluetooth": {
            "label": "Bluetooth",
            "mode": "raw",
            "bandwidth": 2000000,
            "sample_rate": 4000000,
            "step": 1000000,
            "frequencies": [{"label": "BT center", "hz": 2441000000}],
        },
        "gsm": {
            "label": "GSM",
            "mode": "raw",
            "bandwidth": 2000000,
            "sample_rate": 4000000,
            "step": 200000,
            "frequencies": [
                {"label": "GSM 850", "start": 824000000, "stop": 894000000},
                {"label": "GSM 900", "start": 880000000, "stop": 960000000},
                {"label": "DCS 1800", "start": 1710000000, "stop": 1880000000},
                {"label": "PCS 1900", "start": 1850000000, "stop": 1990000000},
            ],
        },
        "satellite": {
            "label": "Satellite",
            "mode": "nfm",
            "bandwidth": 40000,
            "sample_rate": 2000000,
            "step": 5000,
            "frequencies": [
                {"label": "NOAA APT", "start": 137000000, "stop": 138000000},
                {"label": "L-Band Inmarsat", "start": 1525000000, "stop": 1559000000, "mode": "raw", "bandwidth": 2000000},
            ],
        },
    }


def get_quickstart_profiles() -> dict:
    """One-click SDR setups that combine tuning, scan ranges, VFOs, and watch rules."""
    return {
        "weather_watch": {
            "label": "Weather Watch",
            "description": "NOAA weather VFOs plus alerting on the primary weather channel.",
            "receiver": {"frequency": 162550000, "mode": "nfm", "bandwidth": 12500, "sample_rate": 2000000, "step": 25000},
            "scan_ranges": [{"label": "NOAA Weather", "start": 162400000, "stop": 162550000, "threshold_db": -70}],
            "vfos": [
                {"label": "NOAA WX 1", "frequency": 162550000, "mode": "nfm", "bandwidth": 12500, "squelch": -85},
                {"label": "NOAA WX 2", "frequency": 162400000, "mode": "nfm", "bandwidth": 12500, "squelch": -85},
                {"label": "NOAA WX 3", "frequency": 162475000, "mode": "nfm", "bandwidth": 12500, "squelch": -85},
            ],
            "alert_rules": [{"label": "NOAA WX 1 open", "frequency": 162550000, "tolerance_hz": 25000, "min_peak_db": -75}],
        },
        "airband_watch": {
            "label": "Airband Watch",
            "description": "AM airband monitoring with emergency frequency and civil band scan range.",
            "receiver": {"frequency": 121500000, "mode": "am", "bandwidth": 25000, "sample_rate": 2000000, "step": 25000},
            "scan_ranges": [{"label": "Civil Airband", "start": 118000000, "stop": 137000000, "threshold_db": -65}],
            "vfos": [
                {"label": "Air Emergency", "frequency": 121500000, "mode": "am", "bandwidth": 25000, "squelch": -90},
                {"label": "Air Common", "frequency": 123450000, "mode": "am", "bandwidth": 25000, "squelch": -90},
            ],
            "alert_rules": [{"label": "Air emergency active", "frequency": 121500000, "tolerance_hz": 25000, "min_peak_db": -70}],
        },
        "public_safety_survey": {
            "label": "Public Safety Survey",
            "description": "Survey common VHF/UHF/700/800 public-safety ranges for authorized unencrypted traffic.",
            "receiver": {"frequency": 155000000, "mode": "nfm", "bandwidth": 12500, "sample_rate": 2000000, "step": 12500},
            "scan_ranges": [
                {"label": "VHF Public Safety", "start": 150000000, "stop": 174000000, "threshold_db": -70},
                {"label": "UHF Public Safety", "start": 450000000, "stop": 470000000, "threshold_db": -70},
                {"label": "800 MHz Public Safety", "start": 851000000, "stop": 869000000, "threshold_db": -75},
            ],
            "vfos": [
                {"label": "VHF Survey", "frequency": 155000000, "mode": "nfm", "bandwidth": 12500, "squelch": -85},
                {"label": "UHF Survey", "frequency": 460000000, "mode": "nfm", "bandwidth": 12500, "squelch": -85},
                {"label": "800 Survey", "frequency": 855000000, "mode": "raw", "bandwidth": 12500, "squelch": -80},
            ],
            "alert_rules": [{"label": "VHF survey active", "frequency": 155000000, "tolerance_hz": 100000, "min_peak_db": -75}],
        },
        "adsb_tracker": {
            "label": "ADS-B Tracker",
            "description": "Configure HackRF for 1090 MHz ADS-B capture and watch activity.",
            "receiver": {"frequency": 1090000000, "mode": "raw", "bandwidth": 2000000, "sample_rate": 2000000, "step": 1000000},
            "scan_ranges": [{"label": "ADS-B 1090", "start": 1089000000, "stop": 1091000000, "threshold_db": -80}],
            "vfos": [{"label": "ADS-B 1090ES", "frequency": 1090000000, "mode": "raw", "bandwidth": 2000000, "squelch": -90}],
            "alert_rules": [{"label": "ADS-B active", "frequency": 1090000000, "tolerance_hz": 1000000, "min_peak_db": -85}],
        },
        "fm_rds": {
            "label": "FM + RDS",
            "description": "Wide FM broadcast setup with RDS-ready defaults.",
            "receiver": {"frequency": 98100000, "mode": "wfm", "bandwidth": 180000, "sample_rate": 2400000, "step": 200000},
            "scan_ranges": [{"label": "FM Broadcast", "start": 88000000, "stop": 108000000, "threshold_db": -55}],
            "vfos": [
                {"label": "FM 88.1", "frequency": 88100000, "mode": "wfm", "bandwidth": 180000, "squelch": -95},
                {"label": "FM 98.1", "frequency": 98100000, "mode": "wfm", "bandwidth": 180000, "squelch": -95},
                {"label": "FM 107.9", "frequency": 107900000, "mode": "wfm", "bandwidth": 180000, "squelch": -95},
            ],
            "alert_rules": [{"label": "FM 98.1 active", "frequency": 98100000, "tolerance_hz": 200000, "min_peak_db": -60}],
            "decoder": {"decoder": "rds", "frequency": 98100000, "mode": "wfm"},
        },
    }


def get_scan_plans() -> dict:
    """Reusable multi-range scan plans for common discovery tasks."""
    return {
        "weather_sweep": {
            "label": "Weather Sweep",
            "description": "Scan all NOAA weather channels and save active transmitters.",
            "mode": "nfm",
            "sample_rate": 2000000,
            "ranges": [
                {"label": "NOAA Weather", "start": 162400000, "stop": 162550000, "threshold_db": -75, "save_hits": True},
            ],
        },
        "airband_sweep": {
            "label": "Airband Sweep",
            "description": "Scan civil and UHF airband ranges with AM defaults.",
            "mode": "am",
            "sample_rate": 2000000,
            "ranges": [
                {"label": "Civil Airband", "start": 118000000, "stop": 137000000, "threshold_db": -65, "save_hits": True},
                {"label": "Military UHF Air", "start": 225000000, "stop": 400000000, "threshold_db": -70, "save_hits": True},
            ],
        },
        "public_safety_sweep": {
            "label": "Public Safety Sweep",
            "description": "Survey common authorized public-safety ranges and save clear activity candidates.",
            "mode": "nfm",
            "sample_rate": 2000000,
            "ranges": [
                {"label": "VHF Public Safety", "start": 150000000, "stop": 174000000, "threshold_db": -70, "save_hits": True},
                {"label": "UHF Public Safety", "start": 450000000, "stop": 470000000, "threshold_db": -70, "save_hits": True},
                {"label": "700 MHz Public Safety", "start": 769000000, "stop": 775000000, "threshold_db": -75, "save_hits": True, "mode": "raw"},
                {"label": "800 MHz Public Safety", "start": 851000000, "stop": 869000000, "threshold_db": -75, "save_hits": True, "mode": "raw"},
            ],
        },
        "ham_sweep": {
            "label": "Ham Sweep",
            "description": "Scan 2m and 70cm amateur ranges plus APRS/calling activity.",
            "mode": "nfm",
            "sample_rate": 2000000,
            "ranges": [
                {"label": "2m Amateur", "start": 144000000, "stop": 148000000, "threshold_db": -70, "save_hits": True},
                {"label": "70cm Amateur", "start": 420000000, "stop": 450000000, "threshold_db": -70, "save_hits": True},
            ],
        },
        "ism_sweep": {
            "label": "ISM Sweep",
            "description": "Scan common ISM/IoT ranges for active devices.",
            "mode": "raw",
            "sample_rate": 2000000,
            "ranges": [
                {"label": "433 MHz ISM", "start": 433050000, "stop": 434790000, "threshold_db": -65, "save_hits": True},
                {"label": "902-928 MHz ISM", "start": 902000000, "stop": 928000000, "threshold_db": -70, "save_hits": True},
            ],
        },
    }


def parse_hackrf_sweep(output: str | Iterable[str]) -> list[dict]:
    lines = output.splitlines() if isinstance(output, str) else list(output)
    rows = []
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            start_hz = int(parts[2])
            stop_hz = int(parts[3])
            bin_width = int(parts[4])
            samples = int(parts[5])
            powers = [float(value) for value in parts[6:] if value]
        except ValueError:
            continue
        rows.append(
            {
                "date": parts[0],
                "time": parts[1],
                "start_hz": start_hz,
                "stop_hz": stop_hz,
                "bin_width": bin_width,
                "samples": samples,
                "powers_db": powers,
            }
        )
    return rows


def capture_stats(captures: Iterable[dict]) -> dict:
    rows = list(captures)
    total_size = sum(int(row.get("size") or 0) for row in rows)
    return {"count": len(rows), "total_size": total_size}
