"""SDR Suite diagnostics builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _file_status(paths: list[str | Path]) -> dict[str, Any]:
    present = []
    missing = []
    for item in paths:
        path = Path(item)
        row = {"path": str(path), "exists": path.exists()}
        if path.exists():
            present.append(row)
        else:
            missing.append(row)
    return {"present": present, "missing": missing}


def build_sdr_diagnostics(
    *,
    manager: Any,
    receiver_status: dict[str, Any],
    trunking: Any,
    captures_dir: str | Path,
    required_files: list[str | Path],
    aliases: Any,
    events: Any,
) -> dict[str, Any]:
    hackrf = manager.connect()
    trunk_status = trunking.status()
    required = _file_status(required_files)
    captures = Path(captures_dir)
    decoder_tools = trunk_status.get("decoder_tools") or {}
    summary = events.summary()
    alias_count = len(aliases.list())

    next_steps: list[str] = []
    if not hackrf.get("connected"):
        next_steps.append(hackrf.get("error") or "Connect HackRF over USB and verify hackrf_info can open it.")
    if required["missing"]:
        next_steps.append("Run OTA update again or pull the current repo; required SDR files are missing.")
    if not decoder_tools.get("op25", {}).get("available"):
        next_steps.append("Install OP25 and make multi_rx.py or rx.py available in PATH for P25 trunking.")
    if not decoder_tools.get("dsd_fme", {}).get("available"):
        next_steps.append("Install DSD-FME and make dsd-fme available in PATH for DMR/NXDN.")
    if not next_steps:
        next_steps.append("SDR Suite prerequisites are present. Start with Receiver, then Trunking profiles.")

    return {
        "ok": bool(hackrf.get("connected")) and not required["missing"],
        "hackrf": hackrf,
        "receiver": receiver_status,
        "trunking": trunk_status,
        "decoder_tools": decoder_tools,
        "event_summary": summary,
        "aliases": {"count": alias_count, "items": aliases.list()},
        "captures": {"path": str(captures), "exists": captures.exists()},
        "required_files": required,
        "next_steps": next_steps,
    }
