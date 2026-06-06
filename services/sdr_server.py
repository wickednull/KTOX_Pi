#!/usr/bin/env python3
"""Standalone KTOX SDR Suite server."""

from __future__ import annotations

import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from flask_socketio import SocketIO, emit

from sdr.database import CaptureDatabase
from sdr.device import HackRFManager
from sdr.handlers import (
    build_capture_path,
    capture_metadata,
    capture_stats,
    get_frequency_presets,
    parse_hackrf_sweep,
)
from sdr.processing import waterfall_row


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "static" / "sdr"
CAPTURES_DIR = ROOT_DIR / "captures"
DB_PATH = CAPTURES_DIR / "index.db"


def _int_payload(data: dict, key: str, default: int, min_value: int, max_value: int) -> int:
    value = int(data.get(key, default))
    if value < min_value or value > max_value:
        raise ValueError(f"{key} out of range")
    return value


def create_app(
    testing: bool = False,
    manager: HackRFManager | None = None,
    database: CaptureDatabase | None = None,
) -> tuple[Flask, SocketIO]:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
    app.config["SECRET_KEY"] = os.environ.get("KTOX_SDR_SECRET", secrets.token_hex(16))
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    executor = ThreadPoolExecutor(max_workers=2)
    hackrf = manager or HackRFManager()
    db = database or CaptureDatabase(DB_PATH)
    waterfall_flags: dict[str, threading.Event] = {}

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/hackrf/info")
    def hackrf_info():
        return jsonify(hackrf.get_info() | {"tools": hackrf.tools_available()})

    @app.get("/api/hackrf/presets")
    def presets():
        return jsonify(get_frequency_presets())

    @app.get("/api/hackrf/captures")
    def captures():
        rows = db.list_captures()
        return jsonify({"captures": rows, "stats": capture_stats(rows)})

    @app.get("/api/hackrf/captures.csv")
    def captures_csv():
        rows = db.list_captures()
        lines = ["id,filename,frequency,sample_rate,timestamp,size,notes"]
        for row in rows:
            notes = str(row.get("notes") or "").replace('"', '""')
            lines.append(
                f'{row["id"]},"{row["filename"]}",{row["frequency"]},{row["sample_rate"]},{row["timestamp"]},{row["size"]},"{notes}"'
            )
        return Response("\n".join(lines) + "\n", mimetype="text/csv")

    @app.get("/api/hackrf/captures/<int:capture_id>/download")
    def capture_download(capture_id: int):
        row = db.get_capture(capture_id)
        if not row:
            return jsonify({"ok": False, "error": "capture not found"}), 404
        target = (CAPTURES_DIR / row["filename"]).resolve()
        if target.parent != CAPTURES_DIR.resolve() or not target.exists():
            return jsonify({"ok": False, "error": "capture file missing"}), 404
        return send_file(target, as_attachment=True, download_name=target.name)

    @app.delete("/api/hackrf/captures/<int:capture_id>")
    def capture_delete(capture_id: int):
        row = db.get_capture(capture_id)
        if not row:
            return jsonify({"ok": False, "error": "capture not found"}), 404
        target = (CAPTURES_DIR / row["filename"]).resolve()
        if target.parent == CAPTURES_DIR.resolve() and target.exists():
            target.unlink()
        return jsonify({"ok": db.delete_capture(capture_id)})

    @app.post("/api/hackrf/capture")
    def capture():
        try:
            data = request.get_json(silent=True) or {}
            frequency = _int_payload(data, "frequency", 2437000000, 1000000, 6000000000)
            sample_rate = _int_payload(data, "sample_rate", 20000000, 1000000, 20000000)
            duration = _int_payload(data, "duration_sec", 5, 1, 120)
            lna_gain = _int_payload(data, "lna_gain", 16, 0, 40)
            vga_gain = _int_payload(data, "vga_gain", 20, 0, 62)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        capture_path = build_capture_path(CAPTURES_DIR, frequency=frequency)

        def job() -> dict:
            result = hackrf.capture_iq(capture_path, frequency, sample_rate, duration, lna_gain, vga_gain)
            if result.get("ok"):
                meta = capture_metadata(capture_path, frequency, sample_rate)
                db.insert_capture(**meta)
            return result

        if testing:
            return jsonify(job())
        executor.submit(job)
        return jsonify({"ok": True, "queued": True, "filename": capture_path.name})

    @app.route("/api/hackrf/frequency-sweep", methods=["GET", "POST"])
    @app.post("/api/hackrf/sweep")
    def sweep():
        try:
            data = request.args.to_dict() if request.method == "GET" else (request.get_json(silent=True) or {})
            start = _int_payload(data, "start", 2400000000, 1000000, 6000000000)
            stop = _int_payload(data, "stop", 2500000000, start + 1, 6000000000)
            bin_width = _int_payload(data, "bin_width", 1000000, 1000, 20000000)
            dwell_ms = _int_payload(data, "dwell_ms", 100, 1, 5000)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = hackrf.run_sweep(start, stop, bin_width=bin_width, dwell_ms=dwell_ms)
        rows = parse_hackrf_sweep(result.get("stdout", ""))
        return jsonify({"ok": result.get("ok", False), "rows": rows, "error": result.get("error", "")})

    @socketio.on("start_waterfall")
    def start_waterfall(data: dict[str, Any] | None = None):
        sid = request.sid
        stop_event = threading.Event()
        old = waterfall_flags.get(sid)
        if old:
            old.set()
        waterfall_flags[sid] = stop_event
        settings = data or {}
        fft_size = int(settings.get("fft_size", 256))
        frequency = int(settings.get("frequency", 2437000000))
        sample_rate = int(settings.get("sample_rate", 20000000))

        def stream() -> None:
            phase = 0
            tools = hackrf.tools_available()
            proc = None
            try:
                if tools.get("hackrf_transfer"):
                    proc = hackrf.start_rx_stream(
                        [
                            "hackrf_transfer",
                            "-r",
                            "-",
                            "-f",
                            str(frequency),
                            "-s",
                            str(sample_rate),
                        ]
                    )
                while not stop_event.is_set():
                    if proc and proc.stdout:
                        raw = proc.stdout.read(fft_size * 2)
                        if not raw:
                            break
                        samples = [(byte - 256 if byte > 127 else byte) / 128.0 for byte in raw]
                    else:
                        samples = [(((idx + phase) % 64) / 32.0 - 1.0) for idx in range(fft_size * 2)]
                        phase = (phase + 3) % 64
                        time.sleep(0.15)
                    socketio.emit("waterfall_row", {"row": waterfall_row(samples, fft_size=fft_size), "ts": time.time()}, to=sid)
            finally:
                if proc:
                    hackrf.stop_active_process()

        socketio.start_background_task(stream)
        emit("waterfall_status", {"running": True})

    @socketio.on("stop_waterfall")
    def stop_waterfall():
        event = waterfall_flags.pop(request.sid, None)
        if event:
            event.set()
        emit("waterfall_status", {"running": False})

    @socketio.on("disconnect")
    def disconnect():
        event = waterfall_flags.pop(request.sid, None)
        if event:
            event.set()

    return app, socketio


def main() -> None:
    app, socketio = create_app()
    socketio.run(app, host="0.0.0.0", port=8081, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
