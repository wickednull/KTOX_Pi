#!/usr/bin/env python3
"""Standalone KTOX SDR Suite server."""

from __future__ import annotations

import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from flask import Flask, Response, jsonify, redirect, request, send_file, send_from_directory
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
except Exception as exc:
    Flask = Any
    SocketIO = Any
    SDR_IMPORT_ERROR = exc
else:
    SDR_IMPORT_ERROR = None


STATIC_DIR = ROOT_DIR / "static" / "sdr"
CAPTURES_DIR = ROOT_DIR / "captures"
DB_PATH = CAPTURES_DIR / "index.db"


def host_port() -> tuple[str, int]:
    return os.environ.get("KTOX_SDR_HOST", "0.0.0.0"), int(os.environ.get("KTOX_SDR_PORT", "8081"))


def fallback_presets() -> dict[str, dict[str, Any]]:
    return {
        "ism": {"label": "ISM / Wi-Fi", "frequencies": [2400000000, 2437000000, 2462000000]},
        "adsb": {"label": "ADS-B", "frequencies": [1090000000]},
        "fm": {"label": "FM Broadcast", "frequencies": [88100000, 98100000, 107900000]},
        "weather": {"label": "NOAA Weather", "frequencies": [162400000, 162550000]},
    }


class StaticSdrHandler(SimpleHTTPRequestHandler):
    """Keep the SDR page available even when optional backend dependencies are missing."""

    def translate_path(self, path: str) -> str:
        parsed_path = urlparse(path).path
        if parsed_path in {"", "/", "/sdr", "/sdr/"}:
            return str(STATIC_DIR / "index.html")
        if parsed_path.startswith("/sdr/"):
            parsed_path = parsed_path[4:]
        relative = unquote(parsed_path).lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return str(STATIC_DIR / "index.html")
        return str(target)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[SDR] {self.address_string()} - {format % args}", flush=True)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/socket.io/socket.io.js" or path == "/sdr/socket.io/socket.io.js":
            body = b"window.io=window.io||function(){return{__ktoxStub:true,on:function(){},emit:function(){}}};\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/api/hackrf/info", "/sdr/api/hackrf/info", "/api/hackrf/connect", "/sdr/api/hackrf/connect"}:
            self.send_json(
                {
                    "available": False,
                    "connected": False,
                    "error": f"SDR backend dependencies are not loaded: {SDR_IMPORT_ERROR}",
                    "tools": {},
                    "usb": {"available": False, "devices": [], "hackrf": []},
                }
            )
            return
        if path in {"/api/hackrf/presets", "/sdr/api/hackrf/presets"}:
            self.send_json(fallback_presets())
            return
        if path in {"/api/hackrf/captures", "/sdr/api/hackrf/captures"}:
            self.send_json({"captures": [], "stats": {"total_size": 0}})
            return
        if path in {"/api/hackrf/captures.csv", "/sdr/api/hackrf/captures.csv"}:
            body = b"id,filename,frequency,sample_rate,timestamp,size,notes\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        mimetype, _ = mimetypes.guess_type(self.translate_path(path))
        if mimetype:
            self.extensions_map[Path(path).suffix] = mimetype
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path in {"/api/hackrf/connect", "/sdr/api/hackrf/connect"}:
            self.send_json(
                {
                    "available": False,
                    "connected": False,
                    "error": f"SDR backend dependencies are not loaded: {SDR_IMPORT_ERROR}",
                    "tools": {},
                    "usb": {"available": False, "devices": [], "hackrf": []},
                }
            )
            return
        if path in {
            "/api/hackrf/sweep",
            "/api/hackrf/frequency-sweep",
            "/api/hackrf/capture",
            "/sdr/api/hackrf/sweep",
            "/sdr/api/hackrf/frequency-sweep",
            "/sdr/api/hackrf/capture",
        }:
            self.send_json(
                {
                    "ok": False,
                    "error": f"SDR backend dependencies are not loaded: {SDR_IMPORT_ERROR}",
                },
                status=503,
            )
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        self.send_json({"ok": False, "error": "capture backend is not available"}, status=503)


def run_static_sdr_server() -> None:
    host, port = host_port()
    print(f"[SDR] Starting static SDR Suite fallback on http://{host}:{port}/", flush=True)
    print(f"[SDR] Backend disabled because imports failed: {SDR_IMPORT_ERROR}", flush=True)
    ThreadingHTTPServer((host, port), StaticSdrHandler).serve_forever()


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
    @app.get("/sdr/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/socket.io/socket.io.js")
    @app.get("/sdr/socket.io/socket.io.js")
    def socketio_fallback_script():
        return Response(
            "window.io=window.io||function(){return{__ktoxStub:true,on:function(){},emit:function(){}}};\n",
            mimetype="application/javascript",
        )

    @app.get("/sdr")
    def sdr_index_redirect():
        return redirect("/sdr/")

    @app.get("/api/hackrf/info")
    @app.get("/sdr/api/hackrf/info")
    def hackrf_info():
        return jsonify(hackrf.get_info() | {"tools": hackrf.tools_available()})

    @app.post("/api/hackrf/connect")
    @app.post("/sdr/api/hackrf/connect")
    def hackrf_connect():
        return jsonify(hackrf.connect())

    @app.get("/api/hackrf/presets")
    @app.get("/sdr/api/hackrf/presets")
    def presets():
        return jsonify(get_frequency_presets())

    @app.get("/api/hackrf/captures")
    @app.get("/sdr/api/hackrf/captures")
    def captures():
        rows = db.list_captures()
        return jsonify({"captures": rows, "stats": capture_stats(rows)})

    @app.get("/api/hackrf/captures.csv")
    @app.get("/sdr/api/hackrf/captures.csv")
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
    @app.get("/sdr/api/hackrf/captures/<int:capture_id>/download")
    def capture_download(capture_id: int):
        row = db.get_capture(capture_id)
        if not row:
            return jsonify({"ok": False, "error": "capture not found"}), 404
        target = (CAPTURES_DIR / row["filename"]).resolve()
        if target.parent != CAPTURES_DIR.resolve() or not target.exists():
            return jsonify({"ok": False, "error": "capture file missing"}), 404
        return send_file(target, as_attachment=True, download_name=target.name)

    @app.delete("/api/hackrf/captures/<int:capture_id>")
    @app.delete("/sdr/api/hackrf/captures/<int:capture_id>")
    def capture_delete(capture_id: int):
        row = db.get_capture(capture_id)
        if not row:
            return jsonify({"ok": False, "error": "capture not found"}), 404
        target = (CAPTURES_DIR / row["filename"]).resolve()
        if target.parent == CAPTURES_DIR.resolve() and target.exists():
            target.unlink()
        return jsonify({"ok": db.delete_capture(capture_id)})

    @app.post("/api/hackrf/capture")
    @app.post("/sdr/api/hackrf/capture")
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
    @app.route("/sdr/api/hackrf/frequency-sweep", methods=["GET", "POST"])
    @app.post("/api/hackrf/sweep")
    @app.post("/sdr/api/hackrf/sweep")
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


def run_socketio(app: Flask, socketio: SocketIO) -> None:
    host, port = host_port()
    try:
        socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
    except TypeError as exc:
        if "allow_unsafe_werkzeug" not in str(exc):
            raise
        socketio.run(app, host=host, port=port)
    except Exception as exc:
        print(f"[SDR] SocketIO server failed, falling back to Flask: {exc}", flush=True)
        app.run(host=host, port=port)


def main() -> None:
    if SDR_IMPORT_ERROR is not None:
        run_static_sdr_server()
        return
    app, socketio = create_app()
    run_socketio(app, socketio)


if __name__ == "__main__":
    main()
