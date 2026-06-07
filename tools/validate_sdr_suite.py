#!/usr/bin/env python3
"""No-hardware validation for the KTOX SDR Suite."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, args, timeout=None, capture_output=True, text=True, check=False):
        self.calls.append(list(args))
        if args and args[0] == "hackrf_info":
            return FakeResult(
                stdout=(
                    "Found HackRF\n"
                    "Serial number: 0000000000000000\n"
                    "Board ID Number: 2 (HackRF One)\n"
                    "Firmware Version: 2024.02.1\n"
                    "Part ID Number: 0xa000cb3c 0x0065475f\n"
                )
            )
        if args and args[0] == "lsusb":
            return FakeResult(stdout="Bus 001 Device 004: ID 1d50:6089 OpenMoko, Inc. HackRF One\n")
        if args and args[0] == "hackrf_sweep":
            return FakeResult(
                stdout="2026-05-29, 00:00:00, 2400000000, 2401000000, 1000000, 1, -55.0, -42.0\n"
            )
        if args and args[0] == "hackrf_transfer":
            return FakeResult(stdout="\x00\x40\x80\xc0" * 4096)
        return FakeResult()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_processing() -> None:
    from sdr import processing
    from sdr.demod import demodulate_audio

    row = processing.waterfall_row([1, 0, -1, 0] * 128, fft_size=256)
    require(len(row) == 256, "waterfall row should match fft size")
    require(all(0 <= point <= 255 for point in row), "waterfall row values should be byte-scaled")
    peaks = processing.detect_peaks([0, 1, 5, 1, 0], threshold=3)
    require(peaks == [{"bin": 2, "power": 5.0}], f"unexpected peak result: {peaks!r}")
    audio = demodulate_audio([0, 1, 1, 0] * 2048, sample_rate=2000000, mode="nfm")
    require(audio["audio"], "demodulator should produce audio samples")
    require(audio["audio_rate"] == 48000, "demodulator audio rate mismatch")


def validate_database() -> None:
    from sdr.database import CaptureDatabase

    with tempfile.TemporaryDirectory() as tmp:
        db = CaptureDatabase(Path(tmp) / "index.db")
        capture_id = db.insert_capture(
            filename="test.bin",
            frequency=2437000000,
            sample_rate=20000000,
            size=1024,
        )
        captures = db.list_captures()
        require(captures[0]["id"] == capture_id, "capture id was not returned from list")
        require(captures[0]["filename"] == "test.bin", "capture filename mismatch")
        require(captures[0]["frequency"] == 2437000000, "capture frequency mismatch")
        require(db.get_capture(capture_id)["size"] == 1024, "capture lookup failed")
        require(db.delete_capture(capture_id) is True, "capture delete failed")


def validate_device() -> None:
    from sdr.device import HackRFManager

    runner = FakeRunner()
    manager = HackRFManager(runner=runner)
    info = manager.get_info()
    require(info["available"] is True, "fake HackRF should be available")
    require(info["connected"] is True, "fake HackRF should be connected")
    require(info["serial_number"] == "0000000000000000", "serial parse failed")
    connected = manager.connect()
    require(connected["connected"] is True, "connect should report HackRF connected")
    require(connected["usb"]["hackrf"], "connect should include USB HackRF match")
    sweep = manager.run_sweep(2400000000, 2500000000)
    require(sweep["ok"] is True, "fake sweep should work")
    require(["hackrf_sweep", "-f", "2400:2500", "-w", "1000000", "-1"] in runner.calls, "hackrf_sweep should receive MHz range")
    row = manager.read_iq_samples(2437000000, sample_count=256)
    require(row["ok"] is True and len(row["samples"]) == 512, "read_iq_samples should return IQ bytes")
    require(runner.calls[0][0] == "hackrf_info", "hackrf_info was not called")


def validate_receiver() -> None:
    from sdr.device import HackRFManager
    from sdr.receiver import ReceiverConfig, ReceiverSession

    manager = HackRFManager(runner=FakeRunner())
    config = ReceiverConfig.from_payload({
        "frequency": 162550000,
        "sample_rate": 2000000,
        "mode": "nfm",
        "fft_size": 256,
        "audio_rate": 48000,
        "sample_count": 4096,
        "lna_gain": 16,
        "vga_gain": 20,
        "squelch": -80,
        "bandwidth": 12500,
    })
    require(config.frequency == 162550000, "receiver config frequency mismatch")
    require(config.mode == "nfm", "receiver mode should normalize to lowercase")

    session = ReceiverSession(manager)
    status = session.start(config)
    require(status["running"] is True, "receiver should start")
    require(status["config"]["frequency"] == 162550000, "receiver status should include config")
    frame = session.frame()
    require(frame["ok"] is True, "receiver frame should succeed")
    require(len(frame["spectrum"]) == 256, "receiver spectrum size mismatch")
    require(len(frame["waterfall"]) == 256, "receiver waterfall size mismatch")
    audio = session.audio()
    require(audio["ok"] is True, "receiver audio should succeed")
    require(audio["audio"], "receiver audio should include samples")
    stopped = session.stop()
    require(stopped["running"] is False, "receiver should stop")


def validate_handlers() -> None:
    from sdr.handlers import build_capture_path, get_frequency_presets, parse_hackrf_sweep
    from sdr.signals import BookmarkStore, scan_hits_from_rows

    with tempfile.TemporaryDirectory() as tmp:
        captures_dir = Path(tmp).resolve()
        path = build_capture_path(captures_dir, frequency=2437000000)
        require(path.parent == captures_dir, "capture path escaped capture root")
        require(path.name.endswith(".bin"), "capture filename should use .bin")
        store = BookmarkStore(captures_dir / "bookmarks.json")
        created = store.add({"label": "NOAA test", "frequency": 162550000, "mode": "nfm"})
        require(created["id"], "bookmark should get an id")
        require(store.list()[0]["label"] == "NOAA test", "bookmark list should include created bookmark")
        require(store.delete(created["id"]) is True, "bookmark delete should return true")
    require("wifi_2g" in get_frequency_presets(), "wifi preset group missing")
    rows = parse_hackrf_sweep("2026-05-29, 00:00:00, 2400000000, 2401000000, 1000000, 1, -55.0, -42.0")
    require(rows[0]["start_hz"] == 2400000000, "sweep start parse failed")
    require(rows[0]["powers_db"] == [-55.0, -42.0], "sweep powers parse failed")
    hits = scan_hits_from_rows(rows, threshold_db=-60)
    require(any(hit["frequency"] == 2400500000 for hit in hits), "scan hit frequency should use bin center")


def validate_trunking() -> None:
    from sdr.trunking import LicensedOperationStore, TrunkingEventLog, TrunkingProfileStore, TrunkingRuntime

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        agreement = LicensedOperationStore(base / "licensed_operation.json")
        profiles = TrunkingProfileStore(base / "trunking_profiles.json")
        events = TrunkingEventLog(base / "trunking_events.json")
        runtime = TrunkingRuntime(agreement, profiles, events)

        profile = profiles.add({
            "name": "Local P25 test",
            "protocol": "p25",
            "control_channel": 851012500,
            "voice_channels": [851512500, 852012500],
            "talkgroups_allow": [1001, "dispatch"],
            "decoder": "op25",
        })
        require(profile["id"], "trunking profile should get an id")
        require(profile["decoder"] == "op25", "P25 profile should use OP25 decoder")
        require(profiles.list()[0]["control_channel"] == 851012500, "trunking profile should persist")

        try:
            runtime.start(profile["id"])
        except PermissionError:
            pass
        else:
            raise AssertionError("trunking runtime must require licensed operation acceptance")

        accepted = agreement.accept({
            "operator": "KTOX Test Operator",
            "organization": "Lab",
            "reference": "training-authorized-unencrypted",
        })
        require(accepted["accepted"] is True, "licensed operation acceptance should persist")
        status = runtime.start(profile["id"])
        require(status["running"] is True, "trunking runtime should start after acceptance")
        require(status["profile"]["id"] == profile["id"], "trunking status should include profile")
        stopped = runtime.stop()
        require(stopped["running"] is False, "trunking runtime should stop")

        encrypted = events.add({
            "protocol": "p25",
            "frequency": 851512500,
            "talkgroup": "1001",
            "encrypted": True,
            "audio_url": "/api/trunking/audio/test.wav",
            "recording_path": "/tmp/test.wav",
            "decoded_audio": [0, 1, 2],
        })
        require(encrypted["encrypted"] is True, "encrypted trunking event should remain marked encrypted")
        require(encrypted["status"] == "encrypted", "encrypted trunking event should use encrypted status")
        for blocked in ("audio_url", "recording_path", "decoded_audio"):
            require(blocked not in encrypted, f"encrypted trunking event must not expose {blocked}")


def validate_server() -> None:
    from services.sdr_server import create_app
    from sdr.database import CaptureDatabase
    from sdr.device import HackRFManager

    with tempfile.TemporaryDirectory() as tmp:
        db = CaptureDatabase(Path(tmp) / "index.db")
        manager = HackRFManager(runner=FakeRunner())
        app, _socketio = create_app(testing=True, manager=manager, database=db)
        client = app.test_client()
        require(client.get("/api/hackrf/info").status_code == 200, "info endpoint failed")
        connect = client.post("/api/hackrf/connect")
        require(connect.status_code == 200, "connect endpoint failed")
        require(connect.get_json()["connected"] is True, "connect endpoint should report connected fake HackRF")
        require(client.get("/api/hackrf/captures").status_code == 200, "captures endpoint failed")
        require(client.get("/api/hackrf/presets").status_code == 200, "presets endpoint failed")
        payload = {"start": 2400000000, "stop": 2401000000, "bin_width": 1000000, "dwell_ms": 10}
        response = client.post("/api/hackrf/sweep", data=json.dumps(payload), content_type="application/json")
        require(response.status_code == 200, "sweep endpoint failed")
        waterfall = client.post(
            "/api/hackrf/waterfall-row",
            data=json.dumps({"frequency": 2437000000, "sample_rate": 20000000, "fft_size": 256}),
            content_type="application/json",
        )
        require(waterfall.status_code == 200, "waterfall row endpoint failed")
        require(len(waterfall.get_json()["row"]) == 256, "waterfall row endpoint returned wrong row size")
        demod = client.post(
            "/api/hackrf/demodulate",
            data=json.dumps({"frequency": 162550000, "sample_rate": 2000000, "mode": "nfm", "sample_count": 4096}),
            content_type="application/json",
        )
        require(demod.status_code == 200, "demodulate endpoint failed")
        require(demod.get_json()["audio"], "demodulate endpoint should return audio")
        hardware = client.post(
            "/api/hackrf/test",
            data=json.dumps({"frequency": 2437000000, "sample_rate": 20000000}),
            content_type="application/json",
        )
        require(hardware.status_code == 200, "hardware test endpoint failed")
        require("rx" in hardware.get_json() and "sweep" in hardware.get_json(), "hardware test should include RX and sweep results")
        require(client.get("/api/serial/ports").status_code == 200, "serial ports endpoint failed")
        receiver_payload = {
            "frequency": 162550000,
            "sample_rate": 2000000,
            "mode": "nfm",
            "fft_size": 256,
            "sample_count": 4096,
            "lna_gain": 16,
            "vga_gain": 20,
            "squelch": -90,
            "bandwidth": 12500,
        }
        started = client.post("/api/receiver/start", data=json.dumps(receiver_payload), content_type="application/json")
        require(started.status_code == 200, "receiver start endpoint failed")
        require(started.get_json()["running"] is True, "receiver start should report running")
        require(client.get("/api/receiver/status").status_code == 200, "receiver status endpoint failed")
        frame = client.post("/api/receiver/frame", data=json.dumps({"fft_size": 256}), content_type="application/json")
        require(frame.status_code == 200, "receiver frame endpoint failed")
        require(frame.get_json()["spectrum"], "receiver frame should include spectrum")
        audio = client.post("/api/receiver/audio", data=json.dumps({"sample_count": 4096}), content_type="application/json")
        require(audio.status_code == 200, "receiver audio endpoint failed")
        require(audio.get_json()["audio"], "receiver audio should include samples")
        stopped = client.post("/api/receiver/stop")
        require(stopped.status_code == 200, "receiver stop endpoint failed")
        require(stopped.get_json()["running"] is False, "receiver stop should report stopped")
        scan = client.post(
            "/api/receiver/scan",
            data=json.dumps({"start": 2400000000, "stop": 2500000000, "threshold_db": -50, "save_hits": True}),
            content_type="application/json",
        )
        require(scan.status_code == 200, "receiver scan endpoint failed")
        require(scan.get_json()["hits"], "receiver scan should return hits")
        bookmarks = client.get("/api/receiver/bookmarks")
        require(bookmarks.status_code == 200, "receiver bookmarks endpoint failed")
        require(bookmarks.get_json()["bookmarks"], "scan with save_hits should create bookmarks")
        profile = {
            "name": "Server P25",
            "protocol": "p25",
            "control_channel": 851012500,
            "voice_channels": [851512500],
        }
        created_profile = client.post("/api/trunking/profiles", data=json.dumps(profile), content_type="application/json")
        require(created_profile.status_code == 200, "trunking profile create endpoint failed")
        profile_id = created_profile.get_json()["profile"]["id"]
        blocked_start = client.post("/api/trunking/start", data=json.dumps({"profile_id": profile_id}), content_type="application/json")
        require(blocked_start.status_code == 403, "trunking start must be blocked before licensed operation acceptance")
        agreement = client.post(
            "/api/trunking/agreement",
            data=json.dumps({"operator": "KTOX Test Operator", "organization": "Lab", "reference": "authorized"}),
            content_type="application/json",
        )
        require(agreement.status_code == 200, "trunking agreement endpoint failed")
        started_trunk = client.post("/api/trunking/start", data=json.dumps({"profile_id": profile_id}), content_type="application/json")
        require(started_trunk.status_code == 200, "trunking start endpoint failed after agreement")
        require(started_trunk.get_json()["running"] is True, "trunking start should report running")
        encrypted = client.post(
            "/api/trunking/events",
            data=json.dumps({"protocol": "p25", "encrypted": True, "audio_url": "/bad.wav", "recording_path": "/bad.wav"}),
            content_type="application/json",
        )
        require(encrypted.status_code == 200, "trunking event endpoint failed")
        require("audio_url" not in encrypted.get_json()["event"], "encrypted trunking API event must block playback URL")


def validate_static_assets() -> None:
    required = [
        "static/sdr/index.html",
        "static/sdr/js/api.js",
        "static/sdr/js/waterfall.js",
        "static/sdr/js/app.js",
        "static/sdr/css/style.css",
    ]
    for rel in required:
        require((ROOT / rel).exists(), f"missing {rel}")
    html = (ROOT / "static/sdr/index.html").read_text(encoding="utf-8")
    for token in ["Dashboard", "Receiver", "Listen", "NFM", "WFM", "AM", "USB", "LSB", "receiverSpectrum", "receiverWaterfall", "rxStep", "rxBandwidth", "rxSquelch", "receiverStatus", "Scan Range", "Bookmarks", "Connect HackRF", "Test RX/Sweep", "USB / Serial", "Waterfall", "Sweep", "Capture", "Settings", "js/api.js", "css/style.css"]:
        require(token in html, f"missing SDR UI token {token!r}")
    for token in ["Trunking", "Licensed Operation", "Encrypted traffic is logged", "trunkOperator", "trunkProfileName", "trunkControlChannel", "trunkStart", "trunkEvents"]:
        require(token in html, f"missing trunking UI token {token!r}")
    require('href="./api/hackrf/captures.csv"' in html, "SDR export link must be relative for /sdr proxying")
    require('src="./socket.io/socket.io.js"' in html, "Socket.IO client script must be relative for /sdr proxying")
    require((ROOT / "static/sdr/socket.io/socket.io.js").exists(), "missing static Socket.IO fallback script")


def validate_integration() -> None:
    web_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    web_js = (ROOT / "web/app.js").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    main_installer = (ROOT / "install.sh").read_text(encoding="utf-8", errors="replace")
    ota = (ROOT / "payloads/utilities/auto_update.py").read_text(encoding="utf-8", errors="replace")
    service = (ROOT / "scripts/ktox-sdr.service").read_text(encoding="utf-8")
    installer = (ROOT / "scripts/install_sdr.sh").read_text(encoding="utf-8")
    diagnostic = (ROOT / "scripts/diagnose_sdr.sh").read_text(encoding="utf-8")
    server = (ROOT / "services/sdr_server.py").read_text(encoding="utf-8")
    web_server = (ROOT / "web_server.py").read_text(encoding="utf-8", errors="replace")
    sdr_api = (ROOT / "static/sdr/js/api.js").read_text(encoding="utf-8")
    sdr_app = (ROOT / "static/sdr/js/app.js").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    require("navSdr" in web_html, "main WebUI SDR nav link missing")
    require("resolveSdrUrl" in web_js, "main WebUI SDR URL helper missing")
    require('href="http://localhost:8081"' not in web_html, "main WebUI SDR link must not hardcode localhost")
    require('href="/sdr-suite"' in web_html, "main WebUI SDR link must have server redirect fallback")
    require('app.js?v=' in web_html, "main WebUI app.js should be cache-busted for SDR link updates")
    require("return `http://${targetHost}:8081/`;" in web_js, "SDR link must use current WebUI host on direct port 8081")
    require("window.open(target, '_blank'" in web_js, "SDR click handler must explicitly open resolved port 8081 URL")
    require('parsed.path == "/sdr-suite"' in web_server and "Location" in web_server and ":8081/" in web_server, "WebUI server must redirect /sdr-suite to same host on port 8081")
    require("ExecStart=/usr/bin/python3 /root/KTOx/services/sdr_server.py" in service, "systemd ExecStart mismatch")
    require("/etc/systemd/system/ktox-sdr.service" in installer, "SDR installer must install the systemd unit")
    require("systemctl daemon-reload" in installer, "SDR installer must reload systemd")
    require("wait_for_http" in installer and "journalctl -u ktox-sdr" in installer, "SDR installer must verify HTTP startup and print logs on failure")
    require("systemctl enable" in installer, "SDR installer must offer service enablement")
    require("hackrf" in installer and "libhackrf0" in installer and "usbutils" in installer, "SDR installer must install HackRF and USB probe packages")
    for required in ("services/sdr_server.py", "sdr/trunking.py", "static/sdr/index.html", "tools/validate_sdr_suite.py"):
        require(f'require_file "{required}"' in installer, f"SDR installer must verify {required} exists before installing service")
    require("services/sdr_server.py" in diagnostic and "systemctl cat" in diagnostic and "127.0.0.1:8081" in diagnostic, "SDR diagnostic must inspect files, unit, and local port")
    require("sys.path.insert(0, str(ROOT_DIR))" in server, "sdr_server.py must add repo root to sys.path before package imports")
    require("def run_socketio" in server and "except TypeError" in server and "allow_unsafe_werkzeug" in server, "sdr_server.py must tolerate Flask-SocketIO run argument differences")
    require("run_static_sdr_server" in server and "ThreadingHTTPServer" in server, "sdr_server.py must serve the page even when backend imports fail")
    require("/api/hackrf/connect" in server and "hackrf.connect()" in server, "sdr_server.py must expose explicit HackRF connect endpoint")
    require("/api/receiver/start" in server and "ReceiverSession" in server, "sdr_server.py must expose receiver session APIs")
    require("/api/receiver/scan" in server and "scan_hits_from_rows" in server, "sdr_server.py must expose receiver scan API")
    require("/api/receiver/bookmarks" in server and "BookmarkStore" in server, "sdr_server.py must expose bookmark APIs")
    require("/api/trunking/agreement" in server and "LicensedOperationStore" in server, "sdr_server.py must expose trunking licensed-operation APIs")
    require("/api/trunking/start" in server and "TrunkingRuntime" in server, "sdr_server.py must expose trunking runtime APIs")
    require("/api/trunking/events" in server and "TrunkingEventLog" in server, "sdr_server.py must expose trunking event APIs")
    require("/api/hackrf/waterfall-row" in server and "read_iq_samples" in server, "sdr_server.py must expose HTTP waterfall row endpoint")
    require("/api/hackrf/demodulate" in server and "demodulate_audio" in server, "sdr_server.py must expose demodulation endpoint")
    require("/api/hackrf/test" in server and "hardware_test" in server, "sdr_server.py must expose HackRF hardware test endpoint")
    require("/api/serial/ports" in server and "/api/serial/probe" in server, "sdr_server.py must expose serial port endpoints")
    require('@app.get("/sdr")' in server and 'redirect("/sdr/")' in server, "SDR server should redirect /sdr to /sdr/")
    require('@app.get("/sdr/")' in server, "SDR server should provide /sdr/ alias")
    require("basePath()" in sdr_api and "withBase" in sdr_api, "SDR API client must be prefix-aware")
    require("socketPath" in sdr_app and "SdrApiBasePath" in sdr_app, "SDR Socket.IO client must be prefix-aware")
    require("waterfallRow" in sdr_api and "pollWaterfall" in sdr_app, "SDR UI must support HTTP waterfall polling")
    for token in ("receiverStart", "receiverStop", "receiverStatus", "receiverFrame", "receiverAudio"):
        require(token in sdr_api, f"SDR API client missing {token}")
    require("SdrSpectrum" in (ROOT / "static/sdr/js/waterfall.js").read_text(encoding="utf-8"), "SDR rendering helper must expose SdrSpectrum")
    require("demodulate" in sdr_api and "AudioContext" in sdr_app, "SDR UI must support browser demodulated audio playback")
    require("receiverStart" in sdr_app and "receiverFrameLoop" in sdr_app and "receiverAudioLoop" in sdr_app, "SDR app must run receiver session loops")
    require("serialPorts" in sdr_api and "serialProbe" in sdr_api and "testHackrf" in sdr_app, "SDR UI must expose hardware and serial tests")
    require("receiverScan" in sdr_api and "receiverBookmarks" in sdr_api and "runReceiverScan" in sdr_app, "SDR UI must expose scan and bookmark actions")
    for token in ("trunkingAgreement", "trunkingAcceptAgreement", "trunkingProfiles", "trunkingStart", "trunkingEvents"):
        require(token in sdr_api, f"SDR API client missing {token}")
    require("acceptTrunkAgreement" in sdr_app and "renderTrunkEvents" in sdr_app and "startTrunking" in sdr_app, "SDR UI must expose trunking workflow")
    require("scripts/install_sdr.sh" in readme and "scripts/diagnose_sdr.sh" in readme and "ktox-sdr" in readme, "README must document SDR service installation and diagnostics")
    for folder in ("sdr", "services", "static", "tools"):
        require(f'"$FIRMWARE_DIR/{folder}"' in main_installer, f"main installer must copy {folder}/")
    for required in ("services/sdr_server.py", "sdr/device.py", "sdr/demod.py", "sdr/receiver.py", "sdr/signals.py", "sdr/trunking.py", "static/sdr/index.html", "tools/validate_sdr_suite.py", "scripts/install_sdr.sh"):
        require(required in ota, f"OTA updater must verify {required}")
    require("ls-tree" in ota and "remote missing" in ota and "local missing" in ota, "OTA updater must diagnose remote/local SDR file gaps")
    for dep in ["numpy", "flask-socketio", "python-socketio"]:
        require(dep in requirements, f"missing requirement {dep}")


def main() -> int:
    checks = [
        validate_processing,
        validate_database,
        validate_device,
        validate_receiver,
        validate_handlers,
        validate_trunking,
        validate_server,
        validate_static_assets,
        validate_integration,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
