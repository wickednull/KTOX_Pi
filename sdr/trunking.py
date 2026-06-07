"""Trunked radio profile and safety state for the KTOX SDR Suite."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


TERMS_VERSION = "2026-06-07-unencrypted-only"
ALLOWED_PROTOCOLS = {"p25", "dmr", "nxdn", "analog"}
DEFAULT_DECODER = {
    "p25": "op25",
    "dmr": "dsd-fme",
    "nxdn": "dsd-fme",
    "analog": "internal",
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


def _int_list(value: Any) -> list[int | str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        value = [value]
    rows: list[int | str] = []
    for item in value:
        if item in (None, ""):
            continue
        try:
            rows.append(int(item))
        except (TypeError, ValueError):
            rows.append(str(item).strip())
    return rows


class LicensedOperationStore:
    """Persists the operator acknowledgement required before trunked decode starts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get(self) -> dict[str, Any]:
        data = _read_json(self.path, {})
        if not isinstance(data, dict):
            data = {}
        accepted = bool(data.get("accepted")) and data.get("terms_version") == TERMS_VERSION
        return {
            "accepted": accepted,
            "operator": str(data.get("operator") or ""),
            "organization": str(data.get("organization") or ""),
            "reference": str(data.get("reference") or ""),
            "accepted_at": float(data.get("accepted_at") or 0),
            "terms_version": str(data.get("terms_version") or TERMS_VERSION),
        }

    def accepted(self) -> bool:
        return self.get()["accepted"] is True

    def accept(self, payload: dict[str, Any]) -> dict[str, Any]:
        operator = str(payload.get("operator") or "").strip()
        if not operator:
            raise ValueError("operator is required")
        row = {
            "accepted": True,
            "operator": operator,
            "organization": str(payload.get("organization") or "").strip(),
            "reference": str(payload.get("reference") or "").strip(),
            "accepted_at": time.time(),
            "terms_version": TERMS_VERSION,
        }
        _write_json(self.path, row)
        return row


class TrunkingProfileStore:
    """Stores local trunked/conventional decoder profiles."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, [])
        return data if isinstance(data, list) else []

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._read(), key=lambda row: (str(row.get("name") or ""), str(row.get("id") or "")))

    def get(self, profile_id: str) -> dict[str, Any] | None:
        for row in self._read():
            if row.get("id") == profile_id:
                return row
        return None

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("profile name is required")
        protocol = str(payload.get("protocol") or "p25").lower().strip()
        if protocol not in ALLOWED_PROTOCOLS:
            raise ValueError("unsupported trunking protocol")
        control_channel = int(payload.get("control_channel") or payload.get("frequency") or 0)
        if control_channel <= 0:
            raise ValueError("control_channel is required")
        decoder = str(payload.get("decoder") or DEFAULT_DECODER[protocol]).lower().strip()
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "name": name,
            "protocol": protocol,
            "control_channel": control_channel,
            "voice_channels": _int_list(payload.get("voice_channels")),
            "talkgroups_allow": _int_list(payload.get("talkgroups_allow")),
            "talkgroups_block": _int_list(payload.get("talkgroups_block")),
            "decoder": decoder,
            "notes": str(payload.get("notes") or ""),
            "created_at": float(payload.get("created_at") or time.time()),
        }
        rows = [item for item in self._read() if item.get("id") != row["id"]]
        rows.append(row)
        _write_json(self.path, rows)
        return row

    def delete(self, profile_id: str) -> bool:
        rows = self._read()
        kept = [item for item in rows if item.get("id") != profile_id]
        if len(kept) == len(rows):
            return False
        _write_json(self.path, kept)
        return True


class TrunkingEventLog:
    """Stores decoder events while blocking playback metadata for encrypted traffic."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, [])
        return data if isinstance(data, list) else []

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = sorted(self._read(), key=lambda row: float(row.get("timestamp") or 0), reverse=True)
        return rows[: max(1, int(limit))]

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        encrypted = bool(payload.get("encrypted")) or str(payload.get("status") or "").lower() == "encrypted"
        row = {
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "timestamp": float(payload.get("timestamp") or time.time()),
            "protocol": str(payload.get("protocol") or "").lower(),
            "frequency": int(payload.get("frequency") or 0),
            "talkgroup": str(payload.get("talkgroup") or ""),
            "source": str(payload.get("source") or "decoder"),
            "encrypted": encrypted,
            "status": "encrypted" if encrypted else str(payload.get("status") or "decoded"),
            "message": str(payload.get("message") or ""),
        }
        if encrypted:
            row["message"] = row["message"] or "Encrypted voice call logged; playback blocked."
        else:
            for key in ("audio_url", "recording_path", "duration_sec", "decoder"):
                if key in payload:
                    row[key] = payload[key]
        rows = self._read()
        rows.append(row)
        _write_json(self.path, rows[-1000:])
        return row


class TrunkingRuntime:
    """Tracks the requested trunked decoder session state."""

    def __init__(
        self,
        agreement: LicensedOperationStore,
        profiles: TrunkingProfileStore,
        events: TrunkingEventLog,
    ):
        self.agreement = agreement
        self.profiles = profiles
        self.events = events
        self.running = False
        self.profile: dict[str, Any] | None = None
        self.started_at = 0.0

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "running": self.running,
            "profile": self.profile,
            "started_at": self.started_at,
            "decoder_state": "waiting-for-engine" if self.running else "stopped",
            "agreement": self.agreement.get(),
        }

    def start(self, profile_id: str) -> dict[str, Any]:
        if not self.agreement.accepted():
            raise PermissionError("licensed operation agreement is required before trunking starts")
        profile = self.profiles.get(profile_id)
        if not profile:
            raise ValueError("trunking profile not found")
        self.running = True
        self.profile = profile
        self.started_at = time.time()
        self.events.add({
            "protocol": profile.get("protocol"),
            "frequency": profile.get("control_channel"),
            "status": "started",
            "source": "ktox",
            "message": f"Started {profile.get('decoder')} control session for {profile.get('name')}",
        })
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self.running and self.profile:
            self.events.add({
                "protocol": self.profile.get("protocol"),
                "frequency": self.profile.get("control_channel"),
                "status": "stopped",
                "source": "ktox",
                "message": f"Stopped control session for {self.profile.get('name')}",
            })
        self.running = False
        self.profile = None
        self.started_at = 0.0
        return self.status()
