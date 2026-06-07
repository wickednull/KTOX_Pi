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


class FakeDecoderTools:
    def __init__(self, available: dict[str, str] | None = None):
        self.available = available or {}

    def which(self, name: str) -> str | None:
        return self.available.get(name)


class FakeDecoderProcess:
    def __init__(self, args, lines=None):
        self.args = list(args)
        self.pid = 4242
        self.terminated = False
        self.lines = list(lines or [])

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.terminated = True
        return 0

    def kill(self):
        self.terminated = True


class FakeDecoderLauncher:
    def __init__(self):
        self.started = []

    def start(self, args, cwd=None, env=None):
        proc = FakeDecoderProcess(args, lines=[
            "op25 tg=1001 src=2002 freq=851.512500 encrypted algid=0x80",
            "dsd-fme DMR voice TG=3101 SRC=4455 FREQ=452.500000",
        ])
        self.started.append({"args": list(args), "cwd": cwd, "env": env, "process": proc})
        return proc


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
    require(audio["duration_sec"] > 0, "demodulator should report audio duration")


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
    readiness = manager.readiness_check(frequency=2437000000, sample_rate=2000000, sample_count=256)
    require(readiness["ok"] is True, "readiness check should pass with fake HackRF")
    require(readiness["rx"]["bytes"] > 0, "readiness check should prove RX bytes were read")
    require(readiness["signal"]["sample_count"] == 512, "readiness check should report interleaved IQ sample count")
    require(readiness["next_steps"][0] == "HackRF is connected and RX sample reads are working.", "readiness next steps should report working RX")
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
    require(audio["duration_sec"] > 0, "receiver audio should include duration metadata")
    stopped = session.stop()
    require(stopped["running"] is False, "receiver should stop")


def validate_handlers() -> None:
    from sdr.handlers import build_capture_path, get_frequency_presets, parse_hackrf_sweep
    from sdr.signals import ActivityStore, AlertRuleStore, BookmarkStore, scan_hits_from_rows

    with tempfile.TemporaryDirectory() as tmp:
        captures_dir = Path(tmp).resolve()
        path = build_capture_path(captures_dir, frequency=2437000000)
        require(path.parent == captures_dir, "capture path escaped capture root")
        require(path.name.endswith(".bin"), "capture filename should use .bin")
        store = BookmarkStore(captures_dir / "bookmarks.json")
        created = store.add({"label": "NOAA test", "frequency": 162550000, "mode": "nfm"})
        require(created["id"], "bookmark should get an id")
        require(created["category"] == "general", "bookmark should default to general category")
        require(store.list()[0]["label"] == "NOAA test", "bookmark list should include created bookmark")
        categorized = store.add({"label": "Airband test", "frequency": 121500000, "mode": "am", "category": "airband"})
        require(store.categories() == ["airband", "general"], "bookmark categories should be sorted")
        exported = store.export_json()
        require("bookmarks" in exported and "Airband test" in exported, "bookmark export should include JSON payload")
        imported = BookmarkStore(captures_dir / "imported_bookmarks.json")
        import_result = imported.import_json(exported)
        require(import_result["imported"] == 2, "bookmark import should report imported count")
        require(imported.list(category="airband")[0]["id"] == categorized["id"], "bookmark import should restore categories")
        require(imported.list(query="noaa")[0]["frequency"] == 162550000, "bookmark list should filter by query")
        require(store.delete(created["id"]) is True, "bookmark delete should return true")
        activity = ActivityStore(captures_dir / "activity.json")
        activity.add({"frequency": 162550000, "mode": "nfm", "peak_db": -42.5, "squelch_open": True, "source": "receiver"})
        activity.add({"frequency": 162550000, "mode": "nfm", "peak_db": -55.0, "squelch_open": False, "source": "receiver"})
        activity.add({"frequency": 121500000, "mode": "am", "peak_db": -38.0, "squelch_open": True, "source": "scan"})
        require(activity.summary()["total_events"] == 3, "activity summary should count events")
        require(activity.summary()["top_frequencies"][0]["frequency"] == 162550000, "activity summary should rank repeated frequencies first")
        require(activity.list(min_peak=-40)[0]["frequency"] == 121500000, "activity list should filter by minimum peak")
        require("frequency,mode,peak_db,squelch_open,source" in activity.to_csv(), "activity CSV should include stable headers")
        alerts = AlertRuleStore(captures_dir / "alert_rules.json", captures_dir / "alert_events.json")
        rule = alerts.add_rule({"label": "NOAA open", "frequency": 162550000, "tolerance_hz": 25000, "min_peak_db": -50})
        require(rule["enabled"] is True and rule["frequency"] == 162550000, "alert rule should persist enabled frequency watch")
        matched = alerts.evaluate({"frequency": 162551000, "peak_db": -42.5, "squelch_open": True, "mode": "nfm"})
        require(matched and matched[0]["rule_id"] == rule["id"], "alert rule should trigger inside tolerance and threshold")
        require(alerts.evaluate({"frequency": 162551000, "peak_db": -80.0, "squelch_open": True}) == [], "alert rule should not trigger below threshold")
        require(alerts.summary()["total_alerts"] == 1, "alert summary should count triggered events")
        require("rule_id,label,frequency,peak_db" in alerts.events_csv(), "alert event CSV should include stable headers")
    presets = get_frequency_presets()
    for group in ("weather", "airband", "marine", "rail", "ham_2m", "ham_70cm", "public_safety", "fm", "adsb", "ais", "ism_433", "ism_915", "wifi_2g"):
        require(group in presets, f"preset group missing {group}")
        require(presets[group]["frequencies"], f"preset group {group} should include frequencies")
        require("mode" in presets[group] and "bandwidth" in presets[group] and "sample_rate" in presets[group], f"preset group {group} should include receiver defaults")
    require(any(item.get("hz") == 162550000 for item in presets["weather"]["frequencies"]), "weather presets should include NOAA 162.550")
    require(any(item.get("start") == 118000000 and item.get("stop") == 137000000 for item in presets["airband"]["frequencies"]), "airband presets should include scan range")
    require(any(item.get("hz") == 1090000000 for item in presets["adsb"]["frequencies"]), "ADS-B presets should include 1090 MHz")
    rows = parse_hackrf_sweep("2026-05-29, 00:00:00, 2400000000, 2401000000, 1000000, 1, -55.0, -42.0")
    require(rows[0]["start_hz"] == 2400000000, "sweep start parse failed")
    require(rows[0]["powers_db"] == [-55.0, -42.0], "sweep powers parse failed")
    hits = scan_hits_from_rows(rows, threshold_db=-60)
    require(any(hit["frequency"] == 2400500000 for hit in hits), "scan hit frequency should use bin center")


def validate_trunking() -> None:
    from sdr.trunking import DecoderLogParser, DecoderProcessManager, DecoderToolchain, LicensedOperationStore, TalkgroupAliasStore, TrunkingEventLog, TrunkingProfileStore, TrunkingRuntime

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        agreement = LicensedOperationStore(base / "licensed_operation.json")
        profiles = TrunkingProfileStore(base / "trunking_profiles.json")
        aliases = TalkgroupAliasStore(base / "trunking_aliases.json")
        events = TrunkingEventLog(base / "trunking_events.json")
        toolchain = DecoderToolchain(base / "decoder", locator=FakeDecoderTools({"multi_rx.py": "/opt/op25/op25/gr-op25_repeater/apps/multi_rx.py", "dsd-fme": "/usr/local/bin/dsd-fme"}))
        launcher = FakeDecoderLauncher()
        process_manager = DecoderProcessManager(launcher=launcher)
        runtime = TrunkingRuntime(agreement, profiles, events, toolchain=toolchain, process_manager=process_manager)

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
        exported_profiles = profiles.export_json()
        require("Local P25 test" in exported_profiles and "profiles" in exported_profiles, "trunking profile export should include profiles")
        imported_profiles = TrunkingProfileStore(base / "imported_profiles.json")
        import_result = imported_profiles.import_json(exported_profiles)
        require(import_result["imported"] == 1, "trunking profile import should report imported count")
        require(imported_profiles.list()[0]["name"] == "Local P25 test", "trunking profile import should restore profile")
        plan = toolchain.plan(profile)
        require(plan["engine"] == "op25", "P25 command plan should use OP25")
        require("--nocrypt" in plan["args"], "OP25 command plan must silence encrypted audio")
        require(Path(plan["config_path"]).exists(), "OP25 command plan should write config JSON")
        op25_config = json.loads(Path(plan["config_path"]).read_text(encoding="utf-8"))
        require(op25_config["trunking"]["chans"][0]["crypt_behavior"] == 2, "OP25 config must use encrypted-call skip behavior")
        require(op25_config["devices"][0]["args"] == "hackrf=0", "OP25 config should default to HackRF source args")
        parsed_encrypted = DecoderLogParser.parse("op25 tg=1001 src=2002 freq=851.512500 encrypted algid=0x80")
        require(parsed_encrypted["encrypted"] is True, "decoder parser should mark encrypted calls")
        require(parsed_encrypted["talkgroup"] == "1001", "decoder parser should extract talkgroup")
        require(parsed_encrypted["source"] == "2002", "decoder parser should extract source")
        require(parsed_encrypted["frequency"] == 851512500, "decoder parser should convert MHz frequency to Hz")
        parsed_clear = DecoderLogParser.parse("dsd-fme DMR voice TG=3101 SRC=4455 FREQ=452.500000")
        require(parsed_clear["protocol"] == "dmr", "decoder parser should detect DMR")
        require(parsed_clear["encrypted"] is False, "decoder parser should not mark clear voice encrypted")

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
        require(status["decoder_state"] == "planned", "trunking runtime should attach decoder plan when tool exists")
        require(status["decoder_plan"]["engine"] == "op25", "trunking status should expose decoder plan")
        require(status["process"]["running"] is True and status["process"]["pid"] == 4242, "trunking runtime should start decoder process")
        require(launcher.started[0]["args"][0] == "/opt/op25/op25/gr-op25_repeater/apps/multi_rx.py", "decoder launcher should receive planned command")
        collected = runtime.collect_decoder_events()
        require(len(collected) == 2, "runtime should collect decoder telemetry events")
        require(collected[0]["encrypted"] is True and "audio_url" not in collected[0], "encrypted telemetry event must not expose audio")
        require(collected[1]["protocol"] == "dmr" and collected[1]["talkgroup"] == "3101", "clear telemetry event should include DMR talkgroup")
        launcher.started[0]["process"].terminated = True
        require(runtime.status()["running"] is False, "runtime should report stopped when decoder process exits")
        status = runtime.start(profile["id"])
        stopped = runtime.stop()
        require(stopped["running"] is False, "trunking runtime should stop")
        require(stopped["process"]["running"] is False, "trunking runtime should stop decoder process")

        dmr_profile = profiles.add({
            "name": "Local DMR test",
            "protocol": "dmr",
            "control_channel": 452500000,
            "decoder": "dsd-fme",
        })
        dmr_plan = toolchain.plan(dmr_profile)
        require(dmr_plan["engine"] == "dsd-fme", "DMR command plan should use DSD-FME")
        require("-fd" in dmr_plan["args"], "DSD-FME DMR plan should request DMR decode mode")

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
        events.add({"protocol": "p25", "frequency": 851512500, "talkgroup": "1001", "source": "2002", "encrypted": False, "status": "voice"})
        events.add({"protocol": "dmr", "frequency": 452500000, "talkgroup": "3101", "source": "4455", "encrypted": False, "status": "voice"})
        summary = events.summary()
        require(summary["total_events"] >= 5, "trunking summary should include total event count")
        require(summary["encrypted_events"] >= 1, "trunking summary should count encrypted events")
        require(summary["clear_events"] >= 2, "trunking summary should count clear events")
        require(summary["talkgroups"][0]["talkgroup"], "trunking summary should include talkgroup rows")
        require(any(row["talkgroup"] == "1001" and row["encrypted"] >= 1 for row in summary["talkgroups"]), "trunking summary should aggregate encrypted talkgroup counts")
        csv_text = events.to_csv()
        require("timestamp,protocol,frequency,talkgroup,source,status,encrypted,message" in csv_text, "trunking CSV should include stable headers")
        require("1001" in csv_text and "encrypted" in csv_text, "trunking CSV should include event rows")
        aliases.upsert({"kind": "talkgroup", "key": "1001", "label": "Dispatch", "color": "#ff0040"})
        aliases.upsert({"kind": "source", "key": "2002", "label": "Unit 2002"})
        exported_aliases = aliases.export_json()
        imported_aliases = TalkgroupAliasStore(base / "imported_aliases.json")
        alias_import = imported_aliases.import_json(exported_aliases)
        require(alias_import["imported"] == 2, "alias import should report imported count")
        labeled = aliases.apply(events.list(limit=20))
        require(any(row.get("talkgroup_label") == "Dispatch" for row in labeled), "alias store should label talkgroup events")
        require(any(row.get("source_label") == "Unit 2002" for row in labeled), "alias store should label source events")
        filtered = events.list(limit=20, talkgroup="1001", encrypted=True)
        require(filtered and all(row["talkgroup"] == "1001" and row["encrypted"] is True for row in filtered), "event log should filter by encrypted talkgroup")
        search_rows = events.list(limit=20, query="voice")
        require(search_rows and all("voice" in str(row).lower() for row in search_rows), "event log should filter by query text")
        missing = DecoderToolchain(base / "missing", locator=FakeDecoderTools({})).status()
        require(missing["op25"]["available"] is False and missing["dsd_fme"]["available"] is False, "decoder status should report missing engines")
        missing_runtime = TrunkingRuntime(agreement, profiles, events, toolchain=DecoderToolchain(base / "missing", locator=FakeDecoderTools({})), process_manager=DecoderProcessManager(launcher=FakeDecoderLauncher()))
        missing_status = missing_runtime.start(profile["id"])
        require(missing_status["decoder_state"] == "decoder-tool-missing", "runtime should not launch missing decoder engine")
        require(missing_status["process"]["running"] is False, "missing decoder engine must not start a process")


def validate_utility_decoders() -> None:
    from sdr.decoders import UtilityDecoderPlanner, UtilityDecoderStatus, UtilityEventLog

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        status = UtilityDecoderStatus(locator=FakeDecoderTools({
            "multimon-ng": "/usr/bin/multimon-ng",
            "redsea": "/usr/bin/redsea",
            "whisper": "/usr/local/bin/whisper",
        })).status()
        require(status["pocsag"]["available"] is True, "POCSAG decoder should detect multimon-ng")
        require(status["rds"]["available"] is True, "RDS decoder should detect redsea")
        require(status["transcription"]["available"] is True, "transcription decoder should detect whisper")

        planner = UtilityDecoderPlanner(locator=FakeDecoderTools({"multimon-ng": "/usr/bin/multimon-ng"}))
        pocsag = planner.plan({
            "decoder": "pocsag",
            "frequency": 152480000,
            "mode": "nfm",
            "sample_rate": 2000000,
            "audio_rate": 48000,
        })
        require(pocsag["ok"] is True and pocsag["decoder"] == "pocsag", "POCSAG plan should be valid when multimon-ng exists")
        require("multimon-ng" in " ".join(pocsag["args"]) and "POCSAG1200" in pocsag["args"], "POCSAG plan should use multimon-ng POCSAG1200")
        missing_rds = planner.plan({"decoder": "rds", "frequency": 98100000, "mode": "wfm"})
        require(missing_rds["ok"] is False and missing_rds["state"] == "decoder-tool-missing", "RDS plan should report missing redsea")

        events = UtilityEventLog(base / "utility_events.json")
        pager = events.add({"decoder": "pocsag", "frequency": 152480000, "capcode": "12345", "message": "test page"})
        require(pager["decoder"] == "pocsag" and pager["encrypted"] is False, "POCSAG event should persist as clear utility event")
        events.add({"decoder": "rds", "frequency": 98100000, "station": "KTOX", "radiotext": "test station"})
        transcript = events.add({"decoder": "transcription", "frequency": 162550000, "text": "weather alert"})
        require(events.summary()["total_events"] == 3, "utility event summary should count decoder events")
        require(any(row["decoder"] == "rds" for row in events.list(decoder="rds")), "utility events should filter by decoder")
        require(events.list(query="weather")[0]["id"] == transcript["id"], "utility events should filter by query")
        csv_text = events.to_csv()
        require("timestamp,decoder,frequency,status,encrypted,message" in csv_text, "utility decoder CSV should include stable headers")
        require("test page" in csv_text and "KTOX" in csv_text, "utility decoder CSV should include event values")


def validate_diagnostics() -> None:
    from sdr.diagnostics import build_sdr_diagnostics
    from sdr.device import HackRFManager
    from sdr.trunking import DecoderToolchain, LicensedOperationStore, TalkgroupAliasStore, TrunkingEventLog, TrunkingProfileStore, TrunkingRuntime

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        manager = HackRFManager(runner=FakeRunner())
        agreement = LicensedOperationStore(base / "agreement.json")
        profiles = TrunkingProfileStore(base / "profiles.json")
        events = TrunkingEventLog(base / "events.json")
        aliases = TalkgroupAliasStore(base / "aliases.json")
        toolchain = DecoderToolchain(base / "decoders", locator=FakeDecoderTools({"multi_rx.py": "/opt/op25/multi_rx.py"}))
        runtime = TrunkingRuntime(agreement, profiles, events, toolchain=toolchain)
        report = build_sdr_diagnostics(
            manager=manager,
            receiver_status={"running": False, "config": {"frequency": 162550000}},
            trunking=runtime,
            captures_dir=base,
            required_files=[ROOT / "services/sdr_server.py", ROOT / "static/sdr/index.html"],
            aliases=aliases,
            events=events,
        )
        require(report["ok"] is True, "diagnostics should mark fake hardware path ok")
        require(report["hackrf"]["connected"] is True, "diagnostics should include HackRF connection")
        require(report["readiness"]["ok"] is True, "diagnostics should include HackRF RX readiness")
        require(report["decoder_tools"]["op25"]["available"] is True, "diagnostics should include decoder tool status")
        require(report["event_summary"]["total_events"] == 0, "diagnostics should include trunking event summary")
        require(report["required_files"]["missing"] == [], "diagnostics should include required file status")
        require(report["next_steps"], "diagnostics should include actionable next steps")


def validate_server() -> None:
    import services.sdr_server as sdr_server
    from sdr.database import CaptureDatabase
    from sdr.device import HackRFManager

    if sdr_server.SDR_IMPORT_ERROR is not None:
        server = (ROOT / "services/sdr_server.py").read_text(encoding="utf-8")
        for route in (
            "/api/hackrf/info",
            "/api/hackrf/connect",
            "/api/hackrf/readiness",
            "/api/hackrf/test",
            "/api/receiver/start",
            "/api/receiver/frame",
            "/api/trunking/start",
            "/api/diagnostics",
        ):
            require(route in server, f"server source missing route {route}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        db = CaptureDatabase(Path(tmp) / "index.db")
        manager = HackRFManager(runner=FakeRunner())
        app, _socketio = sdr_server.create_app(testing=True, manager=manager, database=db)
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
        readiness = client.post(
            "/api/hackrf/readiness",
            data=json.dumps({"frequency": 2437000000, "sample_rate": 2000000, "sample_count": 256}),
            content_type="application/json",
        )
        require(readiness.status_code == 200, "readiness endpoint failed")
        require(readiness.get_json()["ok"] is True, "readiness endpoint should pass for fake HackRF")
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
        bookmark_payload = {"label": "Server airband", "frequency": 121500000, "mode": "am", "category": "airband"}
        added_bookmark = client.post("/api/receiver/bookmarks", data=json.dumps(bookmark_payload), content_type="application/json")
        require(added_bookmark.status_code == 200, "receiver bookmark create endpoint failed")
        categorized_bookmarks = client.get("/api/receiver/bookmarks?category=airband&q=server")
        require(categorized_bookmarks.status_code == 200 and categorized_bookmarks.get_json()["bookmarks"], "receiver bookmarks endpoint should filter category and query")
        bookmarks_export = client.get("/api/receiver/bookmarks.json")
        require(bookmarks_export.status_code == 200 and "bookmarks" in bookmarks_export.get_data(as_text=True), "receiver bookmark export endpoint failed")
        imported_bookmarks = client.post("/api/receiver/bookmarks/import", data=bookmarks_export.get_data(), content_type="application/json")
        require(imported_bookmarks.status_code == 200 and imported_bookmarks.get_json()["imported"] >= 1, "receiver bookmark import endpoint failed")
        activity = client.get("/api/receiver/activity")
        require(activity.status_code == 200 and activity.get_json()["summary"]["total_events"] >= 1, "receiver activity endpoint should report frame activity")
        activity_filtered = client.get("/api/receiver/activity?min_peak=-40")
        require(activity_filtered.status_code == 200 and "events" in activity_filtered.get_json(), "receiver activity endpoint should filter events")
        activity_csv = client.get("/api/receiver/activity.csv")
        require(activity_csv.status_code == 200 and "text/csv" in activity_csv.content_type, "receiver activity CSV endpoint failed")
        alert_rule = client.post(
            "/api/receiver/alerts/rules",
            data=json.dumps({"label": "Server NOAA", "frequency": 162550000, "tolerance_hz": 25000, "min_peak_db": -90}),
            content_type="application/json",
        )
        require(alert_rule.status_code == 200 and alert_rule.get_json()["rule"]["id"], "receiver alert rule create endpoint failed")
        client.post("/api/receiver/frame", data=json.dumps(receiver_payload), content_type="application/json")
        alerts = client.get("/api/receiver/alerts")
        require(alerts.status_code == 200 and alerts.get_json()["rules"] and alerts.get_json()["events"], "receiver alerts endpoint should return rules and events")
        alerts_csv = client.get("/api/receiver/alerts.csv")
        require(alerts_csv.status_code == 200 and "text/csv" in alerts_csv.content_type, "receiver alerts CSV endpoint failed")
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
        summary = client.get("/api/trunking/summary")
        require(summary.status_code == 200, "trunking summary endpoint failed")
        require("talkgroups" in summary.get_json()["summary"], "trunking summary endpoint should return talkgroups")
        alias = client.post(
            "/api/trunking/aliases",
            data=json.dumps({"kind": "talkgroup", "key": "1001", "label": "Dispatch"}),
            content_type="application/json",
        )
        require(alias.status_code == 200, "trunking alias endpoint failed")
        filtered_events = client.get("/api/trunking/events?talkgroup=1001&encrypted=1")
        require(filtered_events.status_code == 200, "trunking filtered events endpoint failed")
        decoder_status = client.get("/api/decoders/status")
        require(decoder_status.status_code == 200 and "pocsag" in decoder_status.get_json()["decoders"], "decoder status endpoint failed")
        decoder_plan = client.post(
            "/api/decoders/plan",
            data=json.dumps({"decoder": "pocsag", "frequency": 152480000, "mode": "nfm"}),
            content_type="application/json",
        )
        require(decoder_plan.status_code == 200 and "decoder" in decoder_plan.get_json(), "decoder plan endpoint failed")
        decoder_event = client.post(
            "/api/decoders/events",
            data=json.dumps({"decoder": "rds", "frequency": 98100000, "station": "KTOX"}),
            content_type="application/json",
        )
        require(decoder_event.status_code == 200 and decoder_event.get_json()["event"]["decoder"] == "rds", "decoder event endpoint failed")
        decoder_events = client.get("/api/decoders/events?decoder=rds")
        require(decoder_events.status_code == 200 and decoder_events.get_json()["events"], "decoder events endpoint should filter by decoder")
        decoder_csv = client.get("/api/decoders/events.csv")
        require(decoder_csv.status_code == 200 and "text/csv" in decoder_csv.content_type, "decoder events CSV endpoint failed")
        profiles_export = client.get("/api/trunking/profiles.json")
        require(profiles_export.status_code == 200 and "profiles" in profiles_export.get_data(as_text=True), "trunking profile export endpoint failed")
        aliases_export = client.get("/api/trunking/aliases.json")
        require(aliases_export.status_code == 200 and "aliases" in aliases_export.get_data(as_text=True), "trunking alias export endpoint failed")
        export = client.get("/api/trunking/events.csv")
        require(export.status_code == 200, "trunking CSV export endpoint failed")
        require("text/csv" in export.content_type, "trunking CSV export should use CSV content type")


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
    for token in ["Dashboard", "Receiver", "Listen", "NFM", "WFM", "AM", "USB", "LSB", "receiverSpectrum", "receiverWaterfall", "rxStep", "rxBandwidth", "rxSquelch", "receiverStatus", "VFO Deck", "Add VFO", "Export VFOs", "Import VFOs", "vfoList", "vfoActivity", "Activity Intelligence", "activityList", "activitySummary", "activityMinPeak", "Promote", "Watch Rules", "alertRuleLabel", "alertRules", "alertEvents", "Save Watch", "Scan Range", "Bookmarks", "bookmarkSearch", "bookmarkCategory", "bookmarkImportFile", "Import Bookmarks", "Decoders", "POCSAG", "RDS", "Transcription", "decoderStatus", "decoderEvents", "decoderPlanOutput", "Connect HackRF", "RX Readiness", "readinessOutput", "Test RX/Sweep", "USB / Serial", "Diagnostics", "diagnosticsOutput", "Waterfall", "Sweep", "Capture", "Settings", "js/api.js", "css/style.css"]:
        require(token in html, f"missing SDR UI token {token!r}")
    for token in ["Trunking", "Licensed Operation", "Encrypted traffic is logged", "trunkOperator", "trunkProfileName", "trunkControlChannel", "trunkStart", "trunkSummary", "trunkEventFilter", "trunkEncryptedFilter", "trunkAliasKey", "trunkExportCsv", "trunkExportProfiles", "trunkImportProfiles", "trunkProfileImportFile", "trunkExportAliases", "trunkImportAliases", "trunkAliasImportFile", "trunkProcessStatus", "trunkDecoderStatus", "trunkEvents"]:
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
    for required in ("services/sdr_server.py", "sdr/diagnostics.py", "sdr/trunking.py", "static/sdr/index.html", "tools/validate_sdr_suite.py"):
        require(f'require_file "{required}"' in installer, f"SDR installer must verify {required} exists before installing service")
    require("services/sdr_server.py" in diagnostic and "systemctl cat" in diagnostic and "127.0.0.1:8081" in diagnostic, "SDR diagnostic must inspect files, unit, and local port")
    require("hackrf_info" in diagnostic and "lsusb" in diagnostic and "/api/hackrf/readiness" in diagnostic, "SDR diagnostic must inspect HackRF tools, USB, and readiness endpoint")
    require("multi_rx.py" in diagnostic and "dsd-fme" in diagnostic, "SDR diagnostic must inspect trunking decoder tools")
    require("sys.path.insert(0, str(ROOT_DIR))" in server, "sdr_server.py must add repo root to sys.path before package imports")
    require("def run_socketio" in server and "except TypeError" in server and "allow_unsafe_werkzeug" in server, "sdr_server.py must tolerate Flask-SocketIO run argument differences")
    require("run_static_sdr_server" in server and "ThreadingHTTPServer" in server, "sdr_server.py must serve the page even when backend imports fail")
    require("/api/hackrf/connect" in server and "hackrf.connect()" in server, "sdr_server.py must expose explicit HackRF connect endpoint")
    require("/api/hackrf/readiness" in server and "readiness_check" in server, "sdr_server.py must expose HackRF readiness endpoint")
    require("/api/receiver/start" in server and "ReceiverSession" in server, "sdr_server.py must expose receiver session APIs")
    require("/api/receiver/scan" in server and "scan_hits_from_rows" in server, "sdr_server.py must expose receiver scan API")
    require("/api/receiver/bookmarks" in server and "BookmarkStore" in server, "sdr_server.py must expose bookmark APIs")
    require("/api/receiver/activity" in server and "ActivityStore" in server, "sdr_server.py must expose persistent receiver activity APIs")
    require("/api/receiver/alerts" in server and "AlertRuleStore" in server, "sdr_server.py must expose persistent receiver alert APIs")
    require("/api/trunking/agreement" in server and "LicensedOperationStore" in server, "sdr_server.py must expose trunking licensed-operation APIs")
    require("/api/trunking/start" in server and "TrunkingRuntime" in server and "DecoderToolchain" in server, "sdr_server.py must expose trunking runtime APIs")
    require("/api/trunking/events" in server and "TrunkingEventLog" in server, "sdr_server.py must expose trunking event APIs")
    require("/api/trunking/summary" in server and "/api/trunking/events.csv" in server and "/api/trunking/aliases" in server and "/api/trunking/profiles.json" in server and "/api/trunking/aliases.json" in server, "sdr_server.py must expose trunking analytics, aliases, and exports")
    require("/api/decoders/status" in server and "/api/decoders/events" in server and "/api/decoders/plan" in server and "UtilityDecoderPlanner" in server, "sdr_server.py must expose utility decoder status, events, and plans")
    require("collect_decoder_events" in server, "sdr_server.py must collect decoder telemetry for status/events")
    require("/api/hackrf/waterfall-row" in server and "read_iq_samples" in server, "sdr_server.py must expose HTTP waterfall row endpoint")
    require("/api/hackrf/demodulate" in server and "demodulate_audio" in server, "sdr_server.py must expose demodulation endpoint")
    require("/api/hackrf/test" in server and "hardware_test" in server, "sdr_server.py must expose HackRF hardware test endpoint")
    require("/api/serial/ports" in server and "/api/serial/probe" in server, "sdr_server.py must expose serial port endpoints")
    require("/api/diagnostics" in server and "build_sdr_diagnostics" in server, "sdr_server.py must expose SDR diagnostics endpoint")
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
    require("receiverAudioPayload" in sdr_app and "sample_count: 1048576" in sdr_app, "SDR app must request long enough audio chunks for stable playback")
    require("audioTimer = setInterval(receiverAudioLoop, 450)" in sdr_app, "SDR app should poll audio often enough for continuous playback")
    require("duration_sec" in sdr_app and "audioNextTime - audioCtx.currentTime" in sdr_app, "SDR app should report audio buffer duration/latency")
    require("readiness" in sdr_api and "runReadiness" in sdr_app and "readinessOutput" in sdr_app, "SDR UI must expose HackRF readiness checks")
    require("data-preset-frequency" in sdr_app and "tuneFrequency" in sdr_app, "SDR preset cards should tune the receiver")
    require("data-preset-start" in sdr_app and "applyPresetRange" in sdr_app and "applyPresetDefaults" in sdr_app, "SDR preset cards should support scan ranges and receiver defaults")
    require("vfos" in sdr_app and "renderVfos" in sdr_app and "addVfo" in sdr_app and "selectVfo" in sdr_app and "recordVfoActivity" in sdr_app, "SDR app must expose multi-VFO deck and activity tracking")
    require("serialPorts" in sdr_api and "serialProbe" in sdr_api and "testHackrf" in sdr_app, "SDR UI must expose hardware and serial tests")
    require("diagnostics" in sdr_api and "loadDiagnostics" in sdr_app, "SDR UI must expose diagnostics")
    require("receiverBookmarksImport" in sdr_api and "receiverBookmarksExportUrl" in sdr_api, "SDR API client must expose bookmark import/export")
    require("receiverScan" in sdr_api and "receiverBookmarks" in sdr_api and "runReceiverScan" in sdr_app and "bookmarkSearch" in sdr_app and "importBookmarks" in sdr_app, "SDR UI must expose scan and bookmark actions")
    require("receiverActivity" in sdr_api and "loadActivity" in sdr_app and "renderActivity" in sdr_app and "promoteActivity" in sdr_app, "SDR UI must expose persistent RF activity intelligence")
    require("receiverAlerts" in sdr_api and "receiverAlertRuleAdd" in sdr_api and "loadAlerts" in sdr_app and "saveAlertRule" in sdr_app and "renderAlerts" in sdr_app, "SDR UI must expose persistent RF watch rules and alerts")
    require("exportVfos" in sdr_app and "importVfos" in sdr_app and "downloadJson" in sdr_app, "SDR UI must support VFO group import/export")
    require("decoderStatus" in sdr_api and "decoderPlan" in sdr_api and "decoderEvents" in sdr_api, "SDR API client must expose utility decoder endpoints")
    require("loadDecoders" in sdr_app and "planDecoder" in sdr_app and "renderDecoderEvents" in sdr_app, "SDR UI must expose utility decoder workflow")
    for token in ("trunkingAgreement", "trunkingAcceptAgreement", "trunkingProfiles", "trunkingProfilesImport", "trunkingAliasesImport", "trunkingStart", "trunkingEvents"):
        require(token in sdr_api, f"SDR API client missing {token}")
    require("acceptTrunkAgreement" in sdr_app and "renderTrunkEvents" in sdr_app and "startTrunking" in sdr_app and "decoder_tools" in sdr_app and "trunkProcessStatus" in sdr_app and "renderTrunkSummary" in sdr_app and "saveTrunkAlias" in sdr_app and "importTrunkProfiles" in sdr_app and "importTrunkAliases" in sdr_app and "readJsonFile" in sdr_app and "trunkingEvents" in sdr_app and "SRC" in sdr_app, "SDR UI must expose trunking workflow, imports, and decoder status")
    require(".trunk-event.encrypted" in (ROOT / "static/sdr/css/style.css").read_text(encoding="utf-8"), "SDR UI must visually distinguish encrypted trunking events")
    require("scripts/install_sdr.sh" in readme and "scripts/diagnose_sdr.sh" in readme and "ktox-sdr" in readme, "README must document SDR service installation and diagnostics")
    for folder in ("sdr", "services", "static", "tools"):
        require(f'"$FIRMWARE_DIR/{folder}"' in main_installer, f"main installer must copy {folder}/")
    for required in ("services/sdr_server.py", "sdr/device.py", "sdr/demod.py", "sdr/receiver.py", "sdr/signals.py", "sdr/trunking.py", "sdr/diagnostics.py", "static/sdr/index.html", "tools/validate_sdr_suite.py", "scripts/install_sdr.sh"):
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
        validate_utility_decoders,
        validate_diagnostics,
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
