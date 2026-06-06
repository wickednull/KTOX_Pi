"""SQLite capture index for the KTOX SDR Suite."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


class CaptureDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    frequency INTEGER NOT NULL,
                    sample_rate INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    size INTEGER NOT NULL,
                    notes TEXT DEFAULT ''
                )
                """
            )

    def insert_capture(
        self,
        filename: str,
        frequency: int,
        sample_rate: int,
        size: int,
        timestamp: float | None = None,
        notes: str = "",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO captures (filename, frequency, sample_rate, timestamp, size, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (filename, int(frequency), int(sample_rate), float(timestamp or time.time()), int(size), notes),
            )
            return int(cur.lastrowid)

    def list_captures(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM captures ORDER BY timestamp DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_capture(self, capture_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM captures WHERE id = ?", (int(capture_id),)).fetchone()
        return dict(row) if row else None

    def delete_capture(self, capture_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM captures WHERE id = ?", (int(capture_id),))
            return cur.rowcount > 0
