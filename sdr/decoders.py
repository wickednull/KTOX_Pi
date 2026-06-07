"""Utility decoder helpers for pager, RDS, and transcription workflows."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from csv import DictWriter
from io import StringIO
from pathlib import Path
from typing import Any


UTILITY_DECODERS = {
    "pocsag": {
        "label": "POCSAG Pager",
        "tool": "multimon-ng",
        "alternates": ["multimon-ng"],
        "modes": ["nfm"],
        "notes": "Demodulate pager audio, then decode with multimon-ng.",
    },
    "rds": {
        "label": "FM RDS",
        "tool": "redsea",
        "alternates": ["redsea"],
        "modes": ["wfm"],
        "notes": "Decode FM broadcast RDS groups from demodulated audio.",
    },
    "transcription": {
        "label": "Voice Transcription",
        "tool": "whisper",
        "alternates": ["whisper", "whisper-cpp", "main"],
        "modes": ["nfm", "wfm", "am"],
        "notes": "Transcribe clear voice audio only. Encrypted audio is never sent to transcription.",
    },
}


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class SystemToolLocator:
    def which(self, name: str) -> str | None:
        return shutil.which(name)


class UtilityDecoderStatus:
    def __init__(self, locator: Any | None = None):
        self.locator = locator or SystemToolLocator()

    def _first_available(self, names: list[str]) -> tuple[str | None, str | None]:
        for name in names:
            path = self.locator.which(name)
            if path:
                return name, path
        return None, None

    def status(self) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for key, meta in UTILITY_DECODERS.items():
            tool, path = self._first_available(list(meta["alternates"]))
            rows[key] = {
                "decoder": key,
                "label": meta["label"],
                "available": bool(path),
                "tool": tool or meta["tool"],
                "path": path or "",
                "modes": list(meta["modes"]),
                "notes": meta["notes"],
            }
        return rows


class UtilityDecoderPlanner:
    def __init__(self, locator: Any | None = None):
        self.status_probe = UtilityDecoderStatus(locator=locator)

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        decoder = str(payload.get("decoder") or "").strip().lower()
        if decoder not in UTILITY_DECODERS:
            raise ValueError("unsupported utility decoder")
        frequency = int(payload.get("frequency") or 0)
        if frequency <= 0:
            raise ValueError("frequency is required")
        mode = str(payload.get("mode") or UTILITY_DECODERS[decoder]["modes"][0]).lower()
        sample_rate = int(payload.get("sample_rate") or 2000000)
        audio_rate = int(payload.get("audio_rate") or 48000)
        status = self.status_probe.status()[decoder]
        if not status["available"]:
            return {
                "ok": False,
                "state": "decoder-tool-missing",
                "decoder": decoder,
                "frequency": frequency,
                "mode": mode,
                "tool": status["tool"],
                "message": f"Install {status['tool']} to enable {status['label']}.",
            }
        args = self._args(decoder, status["path"], audio_rate)
        return {
            "ok": True,
            "state": "planned",
            "decoder": decoder,
            "label": status["label"],
            "frequency": frequency,
            "mode": mode,
            "sample_rate": sample_rate,
            "audio_rate": audio_rate,
            "tool": status["tool"],
            "args": args,
            "pipeline": "KTOX receiver audio -> utility decoder stdin",
            "safety": "Use only for authorized unencrypted signals.",
        }

    @staticmethod
    def _args(decoder: str, path: str, audio_rate: int) -> list[str]:
        if decoder == "pocsag":
            return [path, "-a", "POCSAG512", "-a", "POCSAG1200", "-a", "POCSAG2400", "-f", "alpha", "-t", "raw", "-"]
        if decoder == "rds":
            return [path, "-r", str(audio_rate), "-"]
        if decoder == "transcription":
            return [path, "--language", "en", "--output-json", "-"]
        raise ValueError("unsupported utility decoder")


class UtilityEventLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, [])
        return data if isinstance(data, list) else []

    def list(self, limit: int = 200, decoder: str = "", query: str = "") -> list[dict[str, Any]]:
        rows = sorted(self._read(), key=lambda row: float(row.get("timestamp") or 0), reverse=True)
        if decoder:
            rows = [row for row in rows if str(row.get("decoder") or "") == decoder]
        if query:
            needle = query.lower()
            rows = [row for row in rows if needle in json.dumps(row, sort_keys=True).lower()]
        return rows[: max(1, int(limit))]

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        decoder = str(payload.get("decoder") or "").lower().strip()
        if decoder not in UTILITY_DECODERS:
            raise ValueError("unsupported utility decoder")
        encrypted = bool(payload.get("encrypted"))
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "timestamp": float(payload.get("timestamp") or time.time()),
            "decoder": decoder,
            "frequency": int(payload.get("frequency") or 0),
            "status": "encrypted" if encrypted else str(payload.get("status") or "decoded"),
            "encrypted": encrypted,
            "message": str(payload.get("message") or payload.get("radiotext") or payload.get("text") or ""),
        }
        for key in ("capcode", "station", "program_id", "radiotext", "text", "source"):
            if payload.get(key) not in (None, ""):
                row[key] = str(payload.get(key))
        if encrypted:
            for blocked in ("audio_url", "recording_path", "decoded_audio", "text"):
                row.pop(blocked, None)
        rows = [item for item in self._read() if item.get("id") != row["id"]]
        rows.append(row)
        _write_json(self.path, rows)
        return row

    def summary(self) -> dict[str, Any]:
        rows = self._read()
        by_decoder = {key: {"decoder": key, "events": 0, "encrypted": 0} for key in UTILITY_DECODERS}
        encrypted = 0
        for row in rows:
            decoder = str(row.get("decoder") or "")
            if decoder not in by_decoder:
                continue
            by_decoder[decoder]["events"] += 1
            if row.get("encrypted"):
                encrypted += 1
                by_decoder[decoder]["encrypted"] += 1
        return {
            "total_events": len(rows),
            "encrypted_events": encrypted,
            "decoders": list(by_decoder.values()),
        }

    def to_csv(self) -> str:
        fields = ["timestamp", "decoder", "frequency", "status", "encrypted", "message", "capcode", "station", "program_id", "source"]
        output = StringIO()
        writer = DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in self.list(limit=10000):
            writer.writerow(row)
        return output.getvalue()
