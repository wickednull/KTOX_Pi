"""Capture, sweep, and preset helpers for the KTOX SDR Suite."""

from __future__ import annotations

import time
from pathlib import Path
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
