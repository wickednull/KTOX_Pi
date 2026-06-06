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
        "wifi_2g": {
            "label": "WiFi 2.4 GHz",
            "frequencies": [
                {"label": f"CH {channel}", "hz": 2407000000 + channel * 5000000}
                for channel in range(1, 14)
            ],
        },
        "bluetooth": {
            "label": "Bluetooth",
            "frequencies": [{"label": "BT center", "hz": 2441000000}],
        },
        "fm": {
            "label": "FM Radio",
            "frequencies": [{"label": "88-108 MHz", "start": 88000000, "stop": 108000000}],
        },
        "gsm": {
            "label": "GSM",
            "frequencies": [
                {"label": "GSM 850", "start": 824000000, "stop": 894000000},
                {"label": "GSM 900", "start": 880000000, "stop": 960000000},
                {"label": "DCS 1800", "start": 1710000000, "stop": 1880000000},
                {"label": "PCS 1900", "start": 1850000000, "stop": 1990000000},
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
