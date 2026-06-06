"""Signal processing helpers for the KTOX SDR Suite."""

from __future__ import annotations

import cmath
import math
from typing import Iterable, Sequence

try:
    import numpy as _np
except Exception:  # pragma: no cover - exercised on minimal Pi installs.
    _np = None


def _complex_samples(samples: Iterable[complex | float | int]) -> list[complex]:
    raw = list(samples)
    if not raw:
        return []
    if any(isinstance(item, complex) for item in raw):
        return [complex(item) for item in raw]
    if len(raw) % 2 == 0:
        return [complex(float(raw[i]), float(raw[i + 1])) for i in range(0, len(raw), 2)]
    return [complex(float(item), 0.0) for item in raw]


def _fallback_dft(samples: Sequence[complex], fft_size: int) -> list[float]:
    padded = list(samples[:fft_size])
    padded.extend([0j] * max(0, fft_size - len(padded)))
    powers: list[float] = []
    for k in range(fft_size):
        total = 0j
        for n, sample in enumerate(padded):
            total += sample * cmath.exp(-2j * math.pi * k * n / fft_size)
        powers.append(20.0 * math.log10(abs(total) + 1e-12))
    half = fft_size // 2
    return powers[half:] + powers[:half]


def power_spectrum(samples: Iterable[complex | float | int], fft_size: int = 1024) -> list[float]:
    """Return a shifted power spectrum in dB."""

    if fft_size <= 0:
        raise ValueError("fft_size must be positive")
    complex_samples = _complex_samples(samples)
    if _np is None:
        return _fallback_dft(complex_samples, fft_size)
    arr = _np.asarray(complex_samples, dtype=_np.complex64)
    if arr.size < fft_size:
        arr = _np.pad(arr, (0, fft_size - arr.size))
    else:
        arr = arr[:fft_size]
    window = _np.hanning(fft_size)
    spectrum = _np.fft.fftshift(_np.fft.fft(arr * window))
    power = 20 * _np.log10(_np.abs(spectrum) + 1e-12)
    return [float(value) for value in power.tolist()]


def normalize_power(powers: Iterable[float], floor_db: float = -120.0, ceiling_db: float = 0.0) -> list[int]:
    """Scale dB values to 0-255 for compact waterfall rows."""

    if ceiling_db <= floor_db:
        raise ValueError("ceiling_db must be greater than floor_db")
    span = ceiling_db - floor_db
    row = []
    for value in powers:
        scaled = int(round(((float(value) - floor_db) / span) * 255.0))
        row.append(max(0, min(255, scaled)))
    return row


def waterfall_row(samples: Iterable[complex | float | int], fft_size: int = 1024) -> list[int]:
    """Build one normalized waterfall row from IQ samples."""

    return normalize_power(power_spectrum(samples, fft_size=fft_size))


def detect_peaks(powers: Iterable[float], threshold: float, max_peaks: int = 12) -> list[dict]:
    """Find local maxima above `threshold`."""

    values = [float(value) for value in powers]
    peaks = []
    for idx, value in enumerate(values):
        left = values[idx - 1] if idx else float("-inf")
        right = values[idx + 1] if idx < len(values) - 1 else float("-inf")
        if value >= threshold and value >= left and value >= right:
            peaks.append({"bin": idx, "power": value})
    peaks.sort(key=lambda item: item["power"], reverse=True)
    return peaks[:max_peaks]
