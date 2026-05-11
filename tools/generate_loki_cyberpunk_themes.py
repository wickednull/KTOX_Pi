#!/usr/bin/env python3
"""Compatibility wrapper for the Loki cyberpunk theme generator."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from payloads.offensive.loki_theme_generator import main

if __name__ == "__main__":
    raise SystemExit(main())
