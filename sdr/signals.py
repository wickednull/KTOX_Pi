"""Signal scan and bookmark helpers for the KTOX SDR Suite."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Iterable
from csv import DictWriter
from io import StringIO


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

    def list(self, category: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
        rows = self._read()
        if category:
            wanted = category.strip().lower()
            rows = [row for row in rows if str(row.get("category") or "general").lower() == wanted]
        if query:
            needle = query.strip().lower()
            rows = [
                row for row in rows
                if needle in " ".join(
                    str(row.get(key) or "") for key in ("label", "category", "mode", "source", "notes")
                ).lower()
            ]
        return sorted(rows, key=lambda row: (str(row.get("category") or "general"), str(row.get("label") or ""), int(row.get("frequency") or 0)))

    def categories(self) -> list[str]:
        return sorted({str(row.get("category") or "general") for row in self._read()})

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        frequency = int(payload.get("frequency") or 0)
        if frequency <= 0:
            raise ValueError("frequency is required")
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "label": str(payload.get("label") or f"{frequency} Hz"),
            "frequency": frequency,
            "mode": str(payload.get("mode") or "nfm").lower(),
            "category": str(payload.get("category") or "general").strip().lower() or "general",
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

    def export_json(self) -> str:
        payload = {
            "schema": "ktox-sdr-bookmarks-v1",
            "bookmarks": self.list(),
            "categories": self.categories(),
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def import_json(self, payload: str | dict[str, Any]) -> dict[str, Any]:
        data = json.loads(payload) if isinstance(payload, str) else payload
        rows = data.get("bookmarks") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError("bookmarks list is required")
        imported = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            self.add(row)
            imported += 1
        return {"ok": True, "imported": imported}

    def delete(self, bookmark_id: str) -> bool:
        rows = self._read()
        kept = [item for item in rows if item.get("id") != bookmark_id]
        if len(kept) == len(rows):
            return False
        self._write(kept)
        return True


class ActivityStore:
    """Persists receiver activity so active frequencies survive browser sessions."""

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
        self.path.write_text(json.dumps(rows[-5000:], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        frequency = int(payload.get("frequency") or 0)
        if frequency <= 0:
            raise ValueError("frequency is required")
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "timestamp": float(payload.get("timestamp") or time.time()),
            "frequency": frequency,
            "mode": str(payload.get("mode") or "nfm").lower(),
            "peak_db": float(payload.get("peak_db") if payload.get("peak_db") is not None else -120.0),
            "squelch_open": bool(payload.get("squelch_open")),
            "source": str(payload.get("source") or "receiver"),
            "notes": str(payload.get("notes") or ""),
        }
        rows = self._read()
        rows.append(row)
        self._write(rows)
        return row

    def list(self, limit: int = 200, min_peak: float | None = None, query: str = "") -> list[dict[str, Any]]:
        rows = sorted(self._read(), key=lambda row: float(row.get("timestamp") or 0), reverse=True)
        if min_peak is not None:
            rows = [row for row in rows if float(row.get("peak_db") or -120.0) >= float(min_peak)]
        if query:
            needle = query.lower()
            rows = [row for row in rows if needle in json.dumps(row, sort_keys=True).lower()]
        return rows[: max(1, int(limit))]

    def summary(self) -> dict[str, Any]:
        rows = self._read()
        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            frequency = int(row.get("frequency") or 0)
            if frequency <= 0:
                continue
            item = grouped.setdefault(
                frequency,
                {
                    "frequency": frequency,
                    "mode": row.get("mode") or "nfm",
                    "events": 0,
                    "opens": 0,
                    "best_peak_db": -120.0,
                    "last_seen": 0.0,
                },
            )
            item["events"] += 1
            if row.get("squelch_open"):
                item["opens"] += 1
            item["best_peak_db"] = max(float(item["best_peak_db"]), float(row.get("peak_db") or -120.0))
            item["last_seen"] = max(float(item["last_seen"]), float(row.get("timestamp") or 0))
        top = sorted(grouped.values(), key=lambda row: (int(row["events"]), float(row["best_peak_db"])), reverse=True)
        return {
            "total_events": len(rows),
            "open_events": sum(1 for row in rows if row.get("squelch_open")),
            "top_frequencies": top[:25],
        }

    def to_csv(self) -> str:
        fields = ["timestamp", "frequency", "mode", "peak_db", "squelch_open", "source", "notes"]
        output = StringIO()
        writer = DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in self.list(limit=10000):
            writer.writerow(row)
        return output.getvalue()


class AlertRuleStore:
    """Stores receiver watch rules and alert events from activity frames."""

    def __init__(self, rules_path: str | Path, events_path: str | Path):
        self.rules_path = Path(rules_path)
        self.events_path = Path(events_path)

    def _read_rules(self) -> list[dict[str, Any]]:
        if not self.rules_path.exists():
            return []
        try:
            data = json.loads(self.rules_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _write_rules(self, rows: list[dict[str, Any]]) -> None:
        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        self.rules_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        try:
            data = json.loads(self.events_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _write_events(self, rows: list[dict[str, Any]]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text(json.dumps(rows[-5000:], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def rules(self) -> list[dict[str, Any]]:
        return sorted(self._read_rules(), key=lambda row: (str(row.get("label") or ""), int(row.get("frequency") or 0)))

    def add_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        frequency = int(payload.get("frequency") or 0)
        if frequency <= 0:
            raise ValueError("frequency is required")
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "label": str(payload.get("label") or f"Watch {frequency} Hz"),
            "frequency": frequency,
            "mode": str(payload.get("mode") or "").lower(),
            "tolerance_hz": int(payload.get("tolerance_hz") or 12500),
            "min_peak_db": float(payload.get("min_peak_db") if payload.get("min_peak_db") is not None else -60.0),
            "require_open": bool(payload.get("require_open", True)),
            "enabled": bool(payload.get("enabled", True)),
            "created_at": float(payload.get("created_at") or time.time()),
        }
        rows = [item for item in self._read_rules() if item.get("id") != row["id"]]
        rows.append(row)
        self._write_rules(rows)
        return row

    def delete_rule(self, rule_id: str) -> bool:
        rows = self._read_rules()
        kept = [item for item in rows if item.get("id") != rule_id]
        if len(kept) == len(rows):
            return False
        self._write_rules(kept)
        return True

    def events(self, limit: int = 200, query: str = "") -> list[dict[str, Any]]:
        rows = sorted(self._read_events(), key=lambda row: float(row.get("timestamp") or 0), reverse=True)
        if query:
            needle = query.lower()
            rows = [row for row in rows if needle in json.dumps(row, sort_keys=True).lower()]
        return rows[: max(1, int(limit))]

    def evaluate(self, activity: dict[str, Any]) -> list[dict[str, Any]]:
        frequency = int(activity.get("frequency") or 0)
        peak = float(activity.get("peak_db") if activity.get("peak_db") is not None else -120.0)
        squelch_open = bool(activity.get("squelch_open"))
        mode = str(activity.get("mode") or "").lower()
        matched: list[dict[str, Any]] = []
        for rule in self._read_rules():
            if not rule.get("enabled", True):
                continue
            if rule.get("mode") and mode and str(rule.get("mode")).lower() != mode:
                continue
            if abs(frequency - int(rule.get("frequency") or 0)) > int(rule.get("tolerance_hz") or 0):
                continue
            if peak < float(rule.get("min_peak_db") if rule.get("min_peak_db") is not None else -60.0):
                continue
            if bool(rule.get("require_open", True)) and not squelch_open:
                continue
            matched.append(
                {
                    "id": uuid.uuid4().hex,
                    "rule_id": rule["id"],
                    "label": rule.get("label") or "",
                    "timestamp": float(activity.get("timestamp") or time.time()),
                    "frequency": frequency,
                    "mode": mode or str(rule.get("mode") or ""),
                    "peak_db": peak,
                    "squelch_open": squelch_open,
                    "source": str(activity.get("source") or "receiver"),
                }
            )
        if matched:
            rows = self._read_events()
            rows.extend(matched)
            self._write_events(rows)
        return matched

    def summary(self) -> dict[str, Any]:
        events = self._read_events()
        return {
            "total_rules": len(self._read_rules()),
            "enabled_rules": sum(1 for row in self._read_rules() if row.get("enabled", True)),
            "total_alerts": len(events),
            "last_alert": max((float(row.get("timestamp") or 0) for row in events), default=0),
        }

    def events_csv(self) -> str:
        fields = ["rule_id", "label", "frequency", "peak_db", "timestamp", "mode", "squelch_open", "source"]
        output = StringIO()
        writer = DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in self.events(limit=10000):
            writer.writerow(row)
        return output.getvalue()


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
