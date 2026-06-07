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
        if args and args[0] == "hackrf_sweep":
            return FakeResult(
                stdout="2026-05-29, 00:00:00, 2400000000, 2401000000, 1000000, 1, -55.0, -42.0\n"
            )
        return FakeResult()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_processing() -> None:
    from sdr import processing

    row = processing.waterfall_row([1, 0, -1, 0] * 128, fft_size=256)
    require(len(row) == 256, "waterfall row should match fft size")
    require(all(0 <= point <= 255 for point in row), "waterfall row values should be byte-scaled")
    peaks = processing.detect_peaks([0, 1, 5, 1, 0], threshold=3)
    require(peaks == [{"bin": 2, "power": 5.0}], f"unexpected peak result: {peaks!r}")


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
    require(info["serial_number"] == "0000000000000000", "serial parse failed")
    require(runner.calls[0][0] == "hackrf_info", "hackrf_info was not called")


def validate_handlers() -> None:
    from sdr.handlers import build_capture_path, get_frequency_presets, parse_hackrf_sweep

    with tempfile.TemporaryDirectory() as tmp:
        captures_dir = Path(tmp).resolve()
        path = build_capture_path(captures_dir, frequency=2437000000)
        require(path.parent == captures_dir, "capture path escaped capture root")
        require(path.name.endswith(".bin"), "capture filename should use .bin")
    require("wifi_2g" in get_frequency_presets(), "wifi preset group missing")
    rows = parse_hackrf_sweep("2026-05-29, 00:00:00, 2400000000, 2401000000, 1000000, 1, -55.0, -42.0")
    require(rows[0]["start_hz"] == 2400000000, "sweep start parse failed")
    require(rows[0]["powers_db"] == [-55.0, -42.0], "sweep powers parse failed")


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
        require(client.get("/api/hackrf/captures").status_code == 200, "captures endpoint failed")
        require(client.get("/api/hackrf/presets").status_code == 200, "presets endpoint failed")
        payload = {"start": 2400000000, "stop": 2401000000, "bin_width": 1000000, "dwell_ms": 10}
        response = client.post("/api/hackrf/sweep", data=json.dumps(payload), content_type="application/json")
        require(response.status_code == 200, "sweep endpoint failed")


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
    for token in ["Dashboard", "Waterfall", "Sweep", "Capture", "Settings", "js/api.js", "css/style.css"]:
        require(token in html, f"missing SDR UI token {token!r}")
    require('href="./api/hackrf/captures.csv"' in html, "SDR export link must be relative for /sdr proxying")
    require('src="./socket.io/socket.io.js"' in html, "Socket.IO client script must be relative for /sdr proxying")


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
    sdr_api = (ROOT / "static/sdr/js/api.js").read_text(encoding="utf-8")
    sdr_app = (ROOT / "static/sdr/js/app.js").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    require("navSdr" in web_html, "main WebUI SDR nav link missing")
    require("resolveSdrUrl" in web_js, "main WebUI SDR URL helper missing")
    require("return `http://${host}:8081/`;" in web_js, "SDR link must use direct port 8081")
    require("ExecStart=/usr/bin/python3 /root/KTOx/services/sdr_server.py" in service, "systemd ExecStart mismatch")
    require("/etc/systemd/system/ktox-sdr.service" in installer, "SDR installer must install the systemd unit")
    require("systemctl daemon-reload" in installer, "SDR installer must reload systemd")
    require("systemctl enable" in installer, "SDR installer must offer service enablement")
    require("hackrf" in installer and "libhackrf0" in installer, "SDR installer must install HackRF packages")
    for required in ("services/sdr_server.py", "static/sdr/index.html", "tools/validate_sdr_suite.py"):
        require(f'require_file "{required}"' in installer, f"SDR installer must verify {required} exists before installing service")
    require("services/sdr_server.py" in diagnostic and "systemctl cat" in diagnostic and "127.0.0.1:8081" in diagnostic, "SDR diagnostic must inspect files, unit, and local port")
    require("sys.path.insert(0, str(ROOT_DIR))" in server, "sdr_server.py must add repo root to sys.path before package imports")
    require('@app.get("/sdr")' in server and 'redirect("/sdr/")' in server, "SDR server should redirect /sdr to /sdr/")
    require('@app.get("/sdr/")' in server, "SDR server should provide /sdr/ alias")
    require("basePath()" in sdr_api and "withBase" in sdr_api, "SDR API client must be prefix-aware")
    require("socketPath" in sdr_app and "SdrApiBasePath" in sdr_app, "SDR Socket.IO client must be prefix-aware")
    require("scripts/install_sdr.sh" in readme and "scripts/diagnose_sdr.sh" in readme and "ktox-sdr" in readme, "README must document SDR service installation and diagnostics")
    for folder in ("sdr", "services", "static", "tools"):
        require(f'"$FIRMWARE_DIR/{folder}"' in main_installer, f"main installer must copy {folder}/")
    for required in ("services/sdr_server.py", "sdr/device.py", "static/sdr/index.html", "tools/validate_sdr_suite.py", "scripts/install_sdr.sh"):
        require(required in ota, f"OTA updater must verify {required}")
    require("ls-tree" in ota and "remote missing" in ota and "local missing" in ota, "OTA updater must diagnose remote/local SDR file gaps")
    for dep in ["numpy", "flask-socketio", "python-socketio"]:
        require(dep in requirements, f"missing requirement {dep}")


def main() -> int:
    checks = [
        validate_processing,
        validate_database,
        validate_device,
        validate_handlers,
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
