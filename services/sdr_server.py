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
    from sdr.decoders import UtilityDecoderPlanner, UtilityDecoderStatus, UtilityEventLog
    from sdr.demod import demodulate_audio
    from sdr.diagnostics import build_sdr_diagnostics
    from sdr.device import HackRFManager
    from sdr.handlers import (
        build_capture_path,
        capture_metadata,
        capture_stats,
        get_frequency_presets,
        parse_hackrf_sweep,
    )
    from sdr.processing import waterfall_row
    from sdr.receiver import ReceiverConfig, ReceiverSession
    from sdr.signals import ActivityStore, AlertRuleStore, BookmarkStore, scan_hits_from_rows
    from sdr.trunking import DecoderToolchain, LicensedOperationStore, TalkgroupAliasStore, TrunkingEventLog, TrunkingProfileStore, TrunkingRuntime
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
        "weather": {"label": "NOAA Weather", "mode": "nfm", "bandwidth": 12500, "sample_rate": 2000000, "step": 25000, "frequencies": [{"label": "WX 1", "hz": 162550000}, {"label": "WX 2", "hz": 162400000}]},
        "airband": {"label": "Airband", "mode": "am", "bandwidth": 25000, "sample_rate": 2000000, "step": 25000, "frequencies": [{"label": "Emergency 121.500", "hz": 121500000}, {"label": "Civil Airband", "start": 118000000, "stop": 137000000}]},
        "public_safety": {"label": "Public Safety", "mode": "nfm", "bandwidth": 12500, "sample_rate": 2000000, "step": 12500, "frequencies": [{"label": "VHF Public Safety", "start": 150000000, "stop": 174000000}, {"label": "800 MHz Public Safety", "start": 851000000, "stop": 869000000}]},
        "ham_2m": {"label": "Ham Radio 2m", "mode": "nfm", "bandwidth": 12500, "sample_rate": 2000000, "step": 5000, "frequencies": [{"label": "2m Calling", "hz": 146520000}, {"label": "APRS", "hz": 144390000}]},
        "adsb": {"label": "ADS-B", "mode": "raw", "bandwidth": 2000000, "sample_rate": 2000000, "step": 1000000, "frequencies": [{"label": "1090ES", "hz": 1090000000}]},
        "fm": {"label": "FM Broadcast", "mode": "wfm", "bandwidth": 180000, "sample_rate": 2400000, "step": 200000, "frequencies": [{"label": "88-108 MHz", "start": 88000000, "stop": 108000000}, {"label": "98.1", "hz": 98100000}]},
        "wifi_2g": {"label": "WiFi 2.4 GHz", "mode": "raw", "bandwidth": 20000000, "sample_rate": 20000000, "step": 5000000, "frequencies": [{"label": "CH 6", "hz": 2437000000}]},
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
        if path in {
            "/api/hackrf/info",
            "/sdr/api/hackrf/info",
            "/api/hackrf/connect",
            "/sdr/api/hackrf/connect",
            "/api/hackrf/readiness",
            "/sdr/api/hackrf/readiness",
            "/api/hackrf/test",
            "/sdr/api/hackrf/test",
            "/api/receiver/status",
            "/sdr/api/receiver/status",
        }:
            self.send_json(
                {
                    "ok": False,
                    "available": False,
                    "connected": False,
                    "running": False,
                    "config": {},
                    "error": f"SDR backend dependencies are not loaded: {SDR_IMPORT_ERROR}",
                    "tools": {},
                    "usb": {"available": False, "devices": [], "hackrf": []},
                }
            )
            return
        if path in {
            "/api/trunking/agreement",
            "/sdr/api/trunking/agreement",
            "/api/trunking/profiles",
            "/sdr/api/trunking/profiles",
            "/api/trunking/status",
            "/sdr/api/trunking/status",
            "/api/trunking/events",
            "/sdr/api/trunking/events",
            "/api/decoders/plan",
            "/sdr/api/decoders/plan",
            "/api/decoders/events",
            "/sdr/api/decoders/events",
        }:
            self.send_json(
                {
                    "ok": False,
                    "running": False,
                    "agreement": {"accepted": False},
                    "profiles": [],
                    "events": [],
                    "error": f"SDR backend dependencies are not loaded: {SDR_IMPORT_ERROR}",
                },
                status=503,
            )
            return
        if path in {"/api/serial/ports", "/sdr/api/serial/ports"}:
            self.send_json({"available": False, "pyserial": False, "ports": [], "error": f"SDR backend dependencies are not loaded: {SDR_IMPORT_ERROR}"})
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
        if path in {
            "/api/hackrf/connect",
            "/sdr/api/hackrf/connect",
            "/api/hackrf/readiness",
            "/sdr/api/hackrf/readiness",
            "/api/hackrf/test",
            "/sdr/api/hackrf/test",
            "/api/serial/probe",
            "/sdr/api/serial/probe",
            "/api/receiver/start",
            "/api/receiver/stop",
            "/api/receiver/frame",
            "/api/receiver/audio",
            "/api/receiver/scan",
            "/api/receiver/bookmarks",
            "/api/receiver/bookmarks/import",
            "/sdr/api/receiver/start",
            "/sdr/api/receiver/stop",
            "/sdr/api/receiver/frame",
            "/sdr/api/receiver/audio",
            "/sdr/api/receiver/scan",
            "/sdr/api/receiver/bookmarks",
            "/sdr/api/receiver/bookmarks/import",
            "/api/trunking/agreement",
            "/sdr/api/trunking/agreement",
            "/api/trunking/profiles",
            "/sdr/api/trunking/profiles",
            "/api/trunking/start",
            "/sdr/api/trunking/start",
            "/api/trunking/stop",
            "/sdr/api/trunking/stop",
            "/api/trunking/events",
            "/sdr/api/trunking/events",
        }:
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
            "/api/hackrf/waterfall-row",
            "/api/hackrf/demodulate",
            "/sdr/api/hackrf/sweep",
            "/sdr/api/hackrf/frequency-sweep",
            "/sdr/api/hackrf/capture",
            "/sdr/api/hackrf/waterfall-row",
            "/sdr/api/hackrf/demodulate",
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
    receiver = ReceiverSession(hackrf)
    activity = ActivityStore(CAPTURES_DIR / "receiver_activity.json")
    alerts = AlertRuleStore(CAPTURES_DIR / "receiver_alert_rules.json", CAPTURES_DIR / "receiver_alert_events.json")
    bookmarks = BookmarkStore(CAPTURES_DIR / "bookmarks.json")
    trunk_agreement = LicensedOperationStore(CAPTURES_DIR / "licensed_operation.json")
    trunk_profiles = TrunkingProfileStore(CAPTURES_DIR / "trunking_profiles.json")
    trunk_events = TrunkingEventLog(CAPTURES_DIR / "trunking_events.json")
    trunk_aliases = TalkgroupAliasStore(CAPTURES_DIR / "trunking_aliases.json")
    utility_decoders = UtilityDecoderStatus()
    utility_planner = UtilityDecoderPlanner()
    utility_events = UtilityEventLog(CAPTURES_DIR / "utility_decoder_events.json")
    trunking = TrunkingRuntime(
        trunk_agreement,
        trunk_profiles,
        trunk_events,
        toolchain=DecoderToolchain(CAPTURES_DIR / "decoders"),
    )
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

    @app.post("/api/hackrf/test")
    @app.post("/sdr/api/hackrf/test")
    def hackrf_test():
        try:
            data = request.get_json(silent=True) or {}
            frequency = _int_payload(data, "frequency", 2437000000, 1000000, 6000000000)
            sample_rate = _int_payload(data, "sample_rate", 20000000, 1000000, 20000000)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(hackrf.hardware_test(frequency=frequency, sample_rate=sample_rate))

    @app.post("/api/hackrf/readiness")
    @app.post("/sdr/api/hackrf/readiness")
    def hackrf_readiness():
        try:
            data = request.get_json(silent=True) or {}
            frequency = _int_payload(data, "frequency", 2437000000, 1000000, 6000000000)
            sample_rate = _int_payload(data, "sample_rate", 2000000, 1000000, 20000000)
            sample_count = _int_payload(data, "sample_count", 4096, 64, 1048576)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = hackrf.readiness_check(frequency=frequency, sample_rate=sample_rate, sample_count=sample_count)
        return jsonify(result)

    @app.get("/api/serial/ports")
    @app.get("/sdr/api/serial/ports")
    def serial_ports():
        return jsonify(hackrf.serial_ports())

    @app.post("/api/serial/probe")
    @app.post("/sdr/api/serial/probe")
    def serial_probe():
        data = request.get_json(silent=True) or {}
        return jsonify(hackrf.serial_probe(str(data.get("port") or ""), int(data.get("baudrate") or 115200)))

    @app.get("/api/diagnostics")
    @app.get("/sdr/api/diagnostics")
    def diagnostics():
        trunking.collect_decoder_events()
        required_files = [
            ROOT_DIR / "services" / "sdr_server.py",
            ROOT_DIR / "sdr" / "device.py",
            ROOT_DIR / "sdr" / "receiver.py",
            ROOT_DIR / "sdr" / "trunking.py",
            ROOT_DIR / "sdr" / "diagnostics.py",
            ROOT_DIR / "static" / "sdr" / "index.html",
            ROOT_DIR / "tools" / "validate_sdr_suite.py",
        ]
        return jsonify(
            build_sdr_diagnostics(
                manager=hackrf,
                receiver_status=receiver.status(),
                trunking=trunking,
                captures_dir=CAPTURES_DIR,
                required_files=required_files,
                aliases=trunk_aliases,
                events=trunk_events,
            )
        )

    @app.post("/api/receiver/start")
    @app.post("/sdr/api/receiver/start")
    def receiver_start():
        try:
            config = ReceiverConfig.from_payload(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(receiver.start(config) | {"ok": True})

    @app.post("/api/receiver/stop")
    @app.post("/sdr/api/receiver/stop")
    def receiver_stop():
        return jsonify(receiver.stop() | {"ok": True})

    @app.get("/api/receiver/status")
    @app.get("/sdr/api/receiver/status")
    def receiver_status():
        return jsonify(receiver.status() | {"ok": True})

    @app.post("/api/receiver/frame")
    @app.post("/sdr/api/receiver/frame")
    def receiver_frame():
        try:
            payload = request.get_json(silent=True) or {}
            if payload:
                receiver.start(ReceiverConfig.from_payload(receiver.config.as_dict() | payload))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = receiver.frame()
        if result.get("ok"):
            try:
                event = activity.add({
                    "frequency": result.get("frequency") or receiver.config.frequency,
                    "mode": receiver.config.mode,
                    "peak_db": result.get("peak_db", -120.0),
                    "squelch_open": bool(result.get("squelch_open")),
                    "source": "receiver",
                })
                alerts.evaluate(event)
            except (TypeError, ValueError):
                pass
        return jsonify(result), 200 if result.get("ok") else 503

    @app.get("/api/receiver/activity")
    @app.get("/sdr/api/receiver/activity")
    def receiver_activity():
        min_peak_arg = request.args.get("min_peak")
        min_peak = float(min_peak_arg) if min_peak_arg not in (None, "") else None
        return jsonify({
            "ok": True,
            "events": activity.list(
                limit=int(request.args.get("limit") or 200),
                min_peak=min_peak,
                query=str(request.args.get("q") or ""),
            ),
            "summary": activity.summary(),
        })

    @app.get("/api/receiver/activity.csv")
    @app.get("/sdr/api/receiver/activity.csv")
    def receiver_activity_csv():
        return Response(activity.to_csv(), mimetype="text/csv")

    @app.get("/api/receiver/alerts")
    @app.get("/sdr/api/receiver/alerts")
    def receiver_alerts():
        return jsonify({
            "ok": True,
            "rules": alerts.rules(),
            "events": alerts.events(
                limit=int(request.args.get("limit") or 200),
                query=str(request.args.get("q") or ""),
            ),
            "summary": alerts.summary(),
        })

    @app.post("/api/receiver/alerts/rules")
    @app.post("/sdr/api/receiver/alerts/rules")
    def receiver_alert_rule_add():
        try:
            rule = alerts.add_rule(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "rule": rule})

    @app.delete("/api/receiver/alerts/rules/<rule_id>")
    @app.delete("/sdr/api/receiver/alerts/rules/<rule_id>")
    def receiver_alert_rule_delete(rule_id: str):
        return jsonify({"ok": alerts.delete_rule(rule_id)})

    @app.get("/api/receiver/alerts.csv")
    @app.get("/sdr/api/receiver/alerts.csv")
    def receiver_alerts_csv():
        return Response(alerts.events_csv(), mimetype="text/csv")

    @app.post("/api/receiver/audio")
    @app.post("/sdr/api/receiver/audio")
    def receiver_audio():
        try:
            payload = request.get_json(silent=True) or {}
            if payload:
                receiver.start(ReceiverConfig.from_payload(receiver.config.as_dict() | payload))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = receiver.audio()
        return jsonify(result), 200 if result.get("ok") else 503

    @app.get("/api/receiver/bookmarks")
    @app.get("/sdr/api/receiver/bookmarks")
    def receiver_bookmarks():
        return jsonify({
            "ok": True,
            "bookmarks": bookmarks.list(
                category=request.args.get("category") or None,
                query=request.args.get("q") or None,
            ),
            "categories": bookmarks.categories(),
        })

    @app.get("/api/receiver/bookmarks.json")
    @app.get("/sdr/api/receiver/bookmarks.json")
    def receiver_bookmarks_export():
        return Response(bookmarks.export_json(), mimetype="application/json")

    @app.post("/api/receiver/bookmarks")
    @app.post("/sdr/api/receiver/bookmarks")
    def receiver_bookmark_add():
        try:
            row = bookmarks.add(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "bookmark": row})

    @app.post("/api/receiver/bookmarks/import")
    @app.post("/sdr/api/receiver/bookmarks/import")
    def receiver_bookmarks_import():
        try:
            result = bookmarks.import_json(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(result)

    @app.delete("/api/receiver/bookmarks/<bookmark_id>")
    @app.delete("/sdr/api/receiver/bookmarks/<bookmark_id>")
    def receiver_bookmark_delete(bookmark_id: str):
        return jsonify({"ok": bookmarks.delete(bookmark_id)})

    @app.post("/api/receiver/scan")
    @app.post("/sdr/api/receiver/scan")
    def receiver_scan():
        try:
            data = request.get_json(silent=True) or {}
            start = _int_payload(data, "start", 88000000, 1000000, 6000000000)
            stop = _int_payload(data, "stop", 108000000, start + 1, 6000000000)
            bin_width = _int_payload(data, "bin_width", 1000000, 1000, 20000000)
            threshold = float(data.get("threshold_db", -50))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = hackrf.run_sweep(start, stop, bin_width=bin_width)
        rows = parse_hackrf_sweep(result.get("stdout", ""))
        hits = scan_hits_from_rows(rows, threshold_db=threshold)
        saved = []
        if data.get("save_hits"):
            for hit in hits[:25]:
                saved.append(
                    bookmarks.add(
                        {
                            "label": f"Scan hit {hit['frequency']} Hz",
                            "frequency": hit["frequency"],
                            "mode": data.get("mode") or receiver.config.mode,
                            "sample_rate": data.get("sample_rate") or receiver.config.sample_rate,
                            "bandwidth": receiver.config.bandwidth,
                            "category": "scan",
                            "source": "scan",
                            "notes": f"{hit['power_db']} dB",
                        }
                    )
                )
        return jsonify({"ok": result.get("ok", False), "rows": rows, "hits": hits, "saved": saved, "error": result.get("error", "")})

    @app.get("/api/trunking/agreement")
    @app.get("/sdr/api/trunking/agreement")
    def trunking_agreement():
        return jsonify({"ok": True, "agreement": trunk_agreement.get()})

    @app.post("/api/trunking/agreement")
    @app.post("/sdr/api/trunking/agreement")
    def trunking_accept_agreement():
        try:
            row = trunk_agreement.accept(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "agreement": row})

    @app.get("/api/trunking/profiles")
    @app.get("/sdr/api/trunking/profiles")
    def trunking_profiles_list():
        return jsonify({"ok": True, "profiles": trunk_profiles.list()})

    @app.get("/api/trunking/profiles.json")
    @app.get("/sdr/api/trunking/profiles.json")
    def trunking_profiles_export():
        return Response(trunk_profiles.export_json(), mimetype="application/json")

    @app.post("/api/trunking/profiles")
    @app.post("/sdr/api/trunking/profiles")
    def trunking_profile_add():
        try:
            row = trunk_profiles.add(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "profile": row})

    @app.post("/api/trunking/profiles/import")
    @app.post("/sdr/api/trunking/profiles/import")
    def trunking_profiles_import():
        try:
            result = trunk_profiles.import_json(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(result)

    @app.delete("/api/trunking/profiles/<profile_id>")
    @app.delete("/sdr/api/trunking/profiles/<profile_id>")
    def trunking_profile_delete(profile_id: str):
        return jsonify({"ok": trunk_profiles.delete(profile_id)})

    @app.post("/api/trunking/start")
    @app.post("/sdr/api/trunking/start")
    def trunking_start():
        data = request.get_json(silent=True) or {}
        try:
            status = trunking.start(str(data.get("profile_id") or ""))
        except PermissionError as exc:
            return jsonify({"ok": False, "error": str(exc), "agreement": trunk_agreement.get()}), 403
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(status)

    @app.post("/api/trunking/stop")
    @app.post("/sdr/api/trunking/stop")
    def trunking_stop():
        return jsonify(trunking.stop())

    @app.get("/api/trunking/status")
    @app.get("/sdr/api/trunking/status")
    def trunking_status():
        trunking.collect_decoder_events()
        return jsonify(trunking.status())

    @app.get("/api/trunking/events")
    @app.get("/sdr/api/trunking/events")
    def trunking_events_list():
        trunking.collect_decoder_events()
        limit = int(request.args.get("limit") or 200)
        encrypted_arg = request.args.get("encrypted")
        encrypted = None
        if encrypted_arg is not None and encrypted_arg != "":
            encrypted = encrypted_arg.lower() in {"1", "true", "yes", "on"}
        rows = trunk_events.list(
            limit=limit,
            talkgroup=str(request.args.get("talkgroup") or ""),
            source=str(request.args.get("source") or ""),
            encrypted=encrypted,
            query=str(request.args.get("q") or ""),
        )
        return jsonify({"ok": True, "events": trunk_aliases.apply(rows)})

    @app.get("/api/trunking/summary")
    @app.get("/sdr/api/trunking/summary")
    def trunking_summary():
        trunking.collect_decoder_events()
        return jsonify({"ok": True, "summary": trunk_events.summary()})

    @app.get("/api/trunking/aliases")
    @app.get("/sdr/api/trunking/aliases")
    def trunking_aliases_list():
        return jsonify({"ok": True, "aliases": trunk_aliases.list()})

    @app.get("/api/trunking/aliases.json")
    @app.get("/sdr/api/trunking/aliases.json")
    def trunking_aliases_export():
        return Response(trunk_aliases.export_json(), mimetype="application/json")

    @app.post("/api/trunking/aliases")
    @app.post("/sdr/api/trunking/aliases")
    def trunking_alias_upsert():
        try:
            row = trunk_aliases.upsert(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "alias": row})

    @app.post("/api/trunking/aliases/import")
    @app.post("/sdr/api/trunking/aliases/import")
    def trunking_aliases_import():
        try:
            result = trunk_aliases.import_json(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(result)

    @app.get("/api/trunking/events.csv")
    @app.get("/sdr/api/trunking/events.csv")
    def trunking_events_csv():
        trunking.collect_decoder_events()
        return Response(trunk_events.to_csv(), mimetype="text/csv")

    @app.get("/api/decoders/status")
    @app.get("/sdr/api/decoders/status")
    def utility_decoder_status():
        return jsonify({"ok": True, "decoders": utility_decoders.status(), "summary": utility_events.summary()})

    @app.post("/api/decoders/plan")
    @app.post("/sdr/api/decoders/plan")
    def utility_decoder_plan():
        try:
            plan = utility_planner.plan(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(plan)

    @app.get("/api/decoders/events")
    @app.get("/sdr/api/decoders/events")
    def utility_decoder_events():
        rows = utility_events.list(
            limit=int(request.args.get("limit") or 200),
            decoder=str(request.args.get("decoder") or ""),
            query=str(request.args.get("q") or ""),
        )
        return jsonify({"ok": True, "events": rows, "summary": utility_events.summary()})

    @app.get("/api/decoders/events.csv")
    @app.get("/sdr/api/decoders/events.csv")
    def utility_decoder_events_csv():
        return Response(utility_events.to_csv(), mimetype="text/csv")

    @app.post("/api/decoders/events")
    @app.post("/sdr/api/decoders/events")
    def utility_decoder_event_add():
        try:
            row = utility_events.add(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "event": row})

    @app.post("/api/trunking/events")
    @app.post("/sdr/api/trunking/events")
    def trunking_event_add():
        try:
            row = trunk_events.add(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "event": row})

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

        return jsonify(job() | {"filename": capture_path.name})

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

    @app.post("/api/hackrf/waterfall-row")
    @app.post("/sdr/api/hackrf/waterfall-row")
    def waterfall_row_once():
        try:
            data = request.get_json(silent=True) or {}
            fft_size = _int_payload(data, "fft_size", 256, 64, 4096)
            frequency = _int_payload(data, "frequency", 2437000000, 1000000, 6000000000)
            sample_rate = _int_payload(data, "sample_rate", 20000000, 1000000, 20000000)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = hackrf.read_iq_samples(frequency, sample_rate=sample_rate, sample_count=fft_size)
        if not result.get("ok"):
            return jsonify(result), 503
        return jsonify({"ok": True, "row": waterfall_row(result.get("samples", []), fft_size=fft_size), "ts": time.time()})

    @app.post("/api/hackrf/demodulate")
    @app.post("/sdr/api/hackrf/demodulate")
    def demodulate_once():
        try:
            data = request.get_json(silent=True) or {}
            frequency = _int_payload(data, "frequency", 162550000, 1000000, 6000000000)
            sample_rate = _int_payload(data, "sample_rate", 2000000, 1000000, 20000000)
            sample_count = _int_payload(data, "sample_count", 131072, 4096, 1048576)
            lna_gain = _int_payload(data, "lna_gain", 16, 0, 40)
            vga_gain = _int_payload(data, "vga_gain", 20, 0, 62)
            audio_rate = _int_payload(data, "audio_rate", 48000, 8000, 96000)
            mode = str(data.get("mode") or "nfm").lower()
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if mode not in {"nfm", "wfm", "fm", "am", "usb", "lsb", "cw", "raw"}:
            return jsonify({"ok": False, "error": "unsupported demodulation mode"}), 400
        result = hackrf.read_iq_samples(
            frequency,
            sample_rate=sample_rate,
            sample_count=sample_count,
            lna_gain=lna_gain,
            vga_gain=vga_gain,
        )
        if not result.get("ok"):
            return jsonify(result), 503
        audio = demodulate_audio(result.get("samples", []), sample_rate=sample_rate, mode=mode, audio_rate=audio_rate)
        return jsonify({"ok": True, "frequency": frequency, "sample_rate": sample_rate, **audio})

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
