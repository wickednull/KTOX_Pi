"""Small server-side demodulators for KTOX SDR browser playback."""

from __future__ import annotations

import math
from typing import Iterable

try:
    import numpy as _np
except Exception:  # pragma: no cover - minimal installs use fallback path.
    _np = None


def _complex_iq(samples: Iterable[float]) -> list[complex]:
    raw = [float(item) for item in samples]
    if len(raw) % 2:
        raw = raw[:-1]
    return [complex(raw[i], raw[i + 1]) for i in range(0, len(raw), 2)]


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    peak = max(abs(value) for value in values) or 1.0
    scale = min(1.0, 0.95 / peak)
    return [max(-1.0, min(1.0, value * scale)) for value in values]


def _decimate(values: list[float], input_rate: int, audio_rate: int) -> list[float]:
    step = max(1, int(round(float(input_rate) / float(audio_rate))))
    return values[::step]


def _np_demod(iq: list[complex], mode: str) -> list[float] | None:
    if _np is None or not iq:
        return None
    arr = _np.asarray(iq, dtype=_np.complex64)
    mode = mode.lower()
    if mode in {"am", "raw"}:
        audio = _np.abs(arr)
        audio = audio - _np.mean(audio)
    elif mode in {"nfm", "wfm", "fm"}:
        phase = _np.unwrap(_np.angle(arr))
        audio = _np.diff(phase, prepend=phase[0])
        audio = audio * (8.0 if mode == "wfm" else 24.0)
    elif mode == "usb":
        audio = _np.real(arr)
    elif mode == "lsb":
        audio = _np.imag(arr)
    elif mode == "cw":
        audio = _np.abs(arr) - _np.mean(_np.abs(arr))
    else:
        audio = _np.real(arr)
    return [float(value) for value in audio.tolist()]


def demodulate_audio(
    samples: Iterable[float],
    sample_rate: int,
    mode: str = "nfm",
    audio_rate: int = 48000,
) -> dict:
    """Return browser-playable mono float PCM from interleaved IQ samples."""

    iq = _complex_iq(samples)
    audio = _np_demod(iq, mode)
    if audio is None:
        mode_l = mode.lower()
        if mode_l in {"am", "raw", "cw"}:
            mags = [abs(sample) for sample in iq]
            avg = sum(mags) / len(mags) if mags else 0.0
            audio = [value - avg for value in mags]
        elif mode_l in {"nfm", "wfm", "fm"}:
            audio = []
            prev = math.atan2(iq[0].imag, iq[0].real) if iq else 0.0
            gain = 8.0 if mode_l == "wfm" else 24.0
            for sample in iq:
                phase = math.atan2(sample.imag, sample.real)
                diff = phase - prev
                while diff > math.pi:
                    diff -= 2.0 * math.pi
                while diff < -math.pi:
                    diff += 2.0 * math.pi
                audio.append(diff * gain)
                prev = phase
        elif mode_l == "lsb":
            audio = [sample.imag for sample in iq]
        else:
            audio = [sample.real for sample in iq]
    audio = _normalize(_decimate(audio, int(sample_rate), int(audio_rate)))
    return {
        "audio": audio,
        "audio_rate": int(audio_rate),
        "mode": mode.lower(),
        "samples": len(audio),
        "duration_sec": (len(audio) / float(audio_rate)) if audio_rate else 0.0,
    }
