"""Receiver session model for the KTOX SDR Suite."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from sdr.demod import demodulate_audio
from sdr.device import HackRFManager
from sdr.processing import detect_peaks, normalize_power, power_spectrum, waterfall_row


SUPPORTED_MODES = {"nfm", "wfm", "fm", "am", "usb", "lsb", "cw", "raw"}


def _int_range(data: dict[str, Any], key: str, default: int, min_value: int, max_value: int) -> int:
    value = int(data.get(key, default))
    if value < min_value or value > max_value:
        raise ValueError(f"{key} out of range")
    return value


@dataclass
class ReceiverConfig:
    frequency: int = 162550000
    sample_rate: int = 2000000
    mode: str = "nfm"
    fft_size: int = 512
    audio_rate: int = 48000
    sample_count: int = 131072
    lna_gain: int = 16
    vga_gain: int = 20
    squelch: int = -90
    bandwidth: int = 12500

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ReceiverConfig":
        data = payload or {}
        mode = str(data.get("mode") or "nfm").lower()
        if mode not in SUPPORTED_MODES:
            raise ValueError("unsupported demodulation mode")
        return cls(
            frequency=_int_range(data, "frequency", 162550000, 1000000, 6000000000),
            sample_rate=_int_range(data, "sample_rate", 2000000, 1000000, 20000000),
            mode=mode,
            fft_size=_int_range(data, "fft_size", 512, 64, 4096),
            audio_rate=_int_range(data, "audio_rate", 48000, 8000, 96000),
            sample_count=_int_range(data, "sample_count", 131072, 4096, 1048576),
            lna_gain=_int_range(data, "lna_gain", 16, 0, 40),
            vga_gain=_int_range(data, "vga_gain", 20, 0, 62),
            squelch=_int_range(data, "squelch", -90, -140, 0),
            bandwidth=_int_range(data, "bandwidth", 12500, 100, 2000000),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReceiverSession:
    def __init__(self, manager: HackRFManager):
        self.manager = manager
        self.config = ReceiverConfig()
        self.running = False
        self.last_error = ""
        self.started_at = 0.0
        self.last_frame_at = 0.0
        self.last_audio_at = 0.0

    def start(self, config: ReceiverConfig) -> dict[str, Any]:
        self.config = config
        self.running = True
        self.last_error = ""
        self.started_at = time.time()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.manager.stop_active_process()
        self.running = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "config": self.config.as_dict(),
            "last_error": self.last_error,
            "started_at": self.started_at,
            "last_frame_at": self.last_frame_at,
            "last_audio_at": self.last_audio_at,
        }

    def _samples(self, sample_count: int | None = None) -> dict[str, Any]:
        cfg = self.config
        result = self.manager.read_iq_samples(
            cfg.frequency,
            sample_rate=cfg.sample_rate,
            sample_count=sample_count or max(cfg.fft_size, 4096),
            lna_gain=cfg.lna_gain,
            vga_gain=cfg.vga_gain,
        )
        if not result.get("ok"):
            self.last_error = str(result.get("error") or "RX sample read failed")
        return result

    def frame(self) -> dict[str, Any]:
        cfg = self.config
        result = self._samples(cfg.fft_size)
        if not result.get("ok"):
            return {"ok": False, "error": self.last_error, "status": self.status()}
        samples = result.get("samples", [])
        powers = power_spectrum(samples, fft_size=cfg.fft_size)
        peak_level = max(powers) if powers else -120.0
        self.last_frame_at = time.time()
        return {
            "ok": True,
            "status": self.status(),
            "frequency": cfg.frequency,
            "sample_rate": cfg.sample_rate,
            "spectrum": normalize_power(powers),
            "powers_db": powers,
            "waterfall": waterfall_row(samples, fft_size=cfg.fft_size),
            "peaks": detect_peaks(powers, threshold=max(cfg.squelch, peak_level - 20), max_peaks=8),
            "peak_db": peak_level,
            "squelch_open": peak_level >= cfg.squelch,
            "ts": self.last_frame_at,
        }

    def audio(self) -> dict[str, Any]:
        cfg = self.config
        result = self._samples(cfg.sample_count)
        if not result.get("ok"):
            return {"ok": False, "error": self.last_error, "status": self.status()}
        audio = demodulate_audio(
            result.get("samples", []),
            sample_rate=cfg.sample_rate,
            mode=cfg.mode,
            audio_rate=cfg.audio_rate,
        )
        self.last_audio_at = time.time()
        return {
            "ok": True,
            "status": self.status(),
            "frequency": cfg.frequency,
            "sample_rate": cfg.sample_rate,
            **audio,
        }
