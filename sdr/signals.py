"""Signal scan and bookmark helpers for the KTOX SDR Suite."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterable


class BookmarkStore:
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

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._read(), key=lambda row: (str(row.get("label") or ""), int(row.get("frequency") or 0)))

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        frequency = int(payload.get("frequency") or 0)
        if frequency <= 0:
            raise ValueError("frequency is required")
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "label": str(payload.get("label") or f"{frequency} Hz"),
            "frequency": frequency,
            "mode": str(payload.get("mode") or "nfm").lower(),
            "sample_rate": int(payload.get("sample_rate") or 2000000),
            "bandwidth": int(payload.get("bandwidth") or 12500),
            "source": str(payload.get("source") or "manual"),
            "notes": str(payload.get("notes") or ""),
            "created_at": float(payload.get("created_at") or time.time()),
        }
        rows = [item for item in self._read() if item.get("id") != row["id"]]
        rows.append(row)
        self._write(rows)
        return row

    def delete(self, bookmark_id: str) -> bool:
        rows = self._read()
        kept = [item for item in rows if item.get("id") != bookmark_id]
        if len(kept) == len(rows):
            return False
        self._write(kept)
        return True


def scan_hits_from_rows(rows: Iterable[dict[str, Any]], threshold_db: float = -50.0) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in rows:
        start = int(row.get("start_hz") or 0)
        width = int(row.get("bin_width") or 0)
        powers = row.get("powers_db") or []
        for idx, power in enumerate(powers):
            level = float(power)
            if level < float(threshold_db):
                continue
            frequency = start + int((idx + 0.5) * width)
            hits.append(
                {
                    "frequency": frequency,
                    "power_db": level,
                    "bin": idx,
                    "start_hz": start,
                    "stop_hz": int(row.get("stop_hz") or 0),
                    "bin_width": width,
                    "timestamp": f"{row.get('date', '')} {row.get('time', '')}".strip(),
                }
            )
    hits.sort(key=lambda item: item["power_db"], reverse=True)
    return hits
