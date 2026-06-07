"""Trunked radio profile and safety state for the KTOX SDR Suite."""

from __future__ import annotations

import json
import shutil
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
DSD_PROTOCOL_FLAGS = {
    "dmr": "-fd",
    "nxdn": "-fn",
    "p25": "-f1",
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


def _mhz_list(values: list[int | str]) -> str:
    out = []
    for value in values:
        try:
            out.append(f"{int(value) / 1000000:.6f}".rstrip("0").rstrip("."))
        except (TypeError, ValueError):
            continue
    return ",".join(out)


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


class DecoderToolchain:
    """Builds external decoder command plans without attempting encrypted decode."""

    def __init__(self, work_dir: str | Path, locator: Any | None = None):
        self.work_dir = Path(work_dir)
        self.locator = locator or SystemToolLocator()

    def _which(self, name: str) -> str | None:
        found = self.locator.which(name)
        return str(found) if found else None

    def status(self) -> dict[str, Any]:
        op25 = self._which("multi_rx.py") or self._which("rx.py")
        dsd_fme = self._which("dsd-fme")
        return {
            "op25": {"available": bool(op25), "path": op25 or "", "preferred": "multi_rx.py"},
            "dsd_fme": {"available": bool(dsd_fme), "path": dsd_fme or "", "preferred": "dsd-fme"},
        }

    def plan(self, profile: dict[str, Any]) -> dict[str, Any]:
        protocol = str(profile.get("protocol") or "").lower()
        decoder = str(profile.get("decoder") or DEFAULT_DECODER.get(protocol, "")).lower()
        if decoder == "op25" or protocol == "p25":
            return self._op25_plan(profile)
        if decoder == "dsd-fme" or protocol in {"dmr", "nxdn"}:
            return self._dsd_fme_plan(profile)
        return {
            "engine": decoder or "internal",
            "available": True,
            "args": [],
            "message": "No external decoder engine is required for this profile.",
        }

    def _op25_plan(self, profile: dict[str, Any]) -> dict[str, Any]:
        binary = self._which("multi_rx.py") or self._which("rx.py")
        profile_id = str(profile.get("id") or uuid.uuid4().hex)
        config_path = self.work_dir / f"op25-{profile_id}.json"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        sysname = str(profile.get("name") or "ktox-p25")
        control_channels = [int(profile.get("control_channel") or 0)] + [int(item) for item in profile.get("voice_channels") or [] if int(item) > 0]
        config = {
            "channels": [
                {
                    "name": sysname,
                    "device": "sdr0",
                    "trunking_sysname": sysname,
                    "demod_type": "cqpsk",
                    "cqpsk_tracking": True,
                    "destination": "udp://127.0.0.1:23456",
                    "excess_bw": 0.2,
                    "filter_type": "rc",
                    "if_rate": 24000,
                    "plot": "",
                    "symbol_rate": 4800,
                    "enable_analog": "off",
                    "blacklist": "",
                    "whitelist": "",
                }
            ],
            "devices": [
                {
                    "args": str(profile.get("device_args") or "hackrf=0"),
                    "gains": str(profile.get("gains") or "LNA:32"),
                    "gain_mode": False,
                    "name": "sdr0",
                    "offset": 0,
                    "ppm": float(profile.get("ppm") or 0.0),
                    "rate": int(profile.get("sample_rate") or 2400000),
                    "usable_bw_pct": 0.85,
                    "tunable": True,
                }
            ],
            "trunking": {
                "module": "tk_p25.py",
                "chans": [
                    {
                        "nac": "0x0",
                        "sysname": sysname,
                        "control_channel_list": _mhz_list(control_channels),
                        "tgid_tags_file": "",
                        "whitelist": "",
                        "blacklist": "",
                        "tdma_cc": True,
                        "crypt_behavior": 2,
                    }
                ],
            },
            "audio": {
                "module": "sockaudio.py",
                "instances": [{"instance_name": "", "device_name": "pulse", "udp_port": 23426, "audio_gain": 1.0, "number_channels": 1}],
            },
            "terminal": {
                "module": "terminal.py",
                "terminal_type": "http:127.0.0.1:8082",
                "http_plot_interval": 1.0,
                "tuning_step_large": 1200,
                "tuning_step_small": 100,
            },
        }
        _write_json(config_path, config)
        args = [binary or "multi_rx.py", "-c", str(config_path), "--nocrypt"]
        return {
            "engine": "op25",
            "available": bool(binary),
            "binary": binary or "",
            "config_path": str(config_path),
            "args": args,
            "message": "OP25 plan generated with encrypted audio silenced.",
        }

    def _dsd_fme_plan(self, profile: dict[str, Any]) -> dict[str, Any]:
        binary = self._which("dsd-fme")
        protocol = str(profile.get("protocol") or "").lower()
        mode = DSD_PROTOCOL_FLAGS.get(protocol, "-fa")
        args = [binary or "dsd-fme", mode, "-i", "-"]
        return {
            "engine": "dsd-fme",
            "available": bool(binary),
            "binary": binary or "",
            "args": args,
            "message": "DSD-FME plan generated for baseband audio from KTOX receiver pipeline.",
        }


class TrunkingRuntime:
    """Tracks the requested trunked decoder session state."""

    def __init__(
        self,
        agreement: LicensedOperationStore,
        profiles: TrunkingProfileStore,
        events: TrunkingEventLog,
        toolchain: DecoderToolchain | None = None,
    ):
        self.agreement = agreement
        self.profiles = profiles
        self.events = events
        self.toolchain = toolchain or DecoderToolchain(Path("captures") / "decoders")
        self.running = False
        self.profile: dict[str, Any] | None = None
        self.started_at = 0.0
        self.decoder_plan: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        if self.running and self.decoder_plan:
            decoder_state = "planned" if self.decoder_plan.get("available") else "decoder-tool-missing"
        else:
            decoder_state = "stopped"
        return {
            "ok": True,
            "running": self.running,
            "profile": self.profile,
            "started_at": self.started_at,
            "decoder_state": decoder_state,
            "decoder_plan": self.decoder_plan,
            "decoder_tools": self.toolchain.status(),
            "agreement": self.agreement.get(),
        }

    def start(self, profile_id: str) -> dict[str, Any]:
        if not self.agreement.accepted():
            raise PermissionError("licensed operation agreement is required before trunking starts")
        profile = self.profiles.get(profile_id)
        if not profile:
            raise ValueError("trunking profile not found")
        self.decoder_plan = self.toolchain.plan(profile)
        self.running = True
        self.profile = profile
        self.started_at = time.time()
        self.events.add({
            "protocol": profile.get("protocol"),
            "frequency": profile.get("control_channel"),
            "status": "started",
            "source": "ktox",
            "message": f"Planned {profile.get('decoder')} control session for {profile.get('name')}",
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
        self.decoder_plan = None
        return self.status()
