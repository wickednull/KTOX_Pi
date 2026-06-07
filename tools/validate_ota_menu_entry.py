#!/usr/bin/env python3
"""Validate that the device OTA menu uses the hardened updater path."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "ktox_device.py"
GENERAL_UPDATER = ROOT / "payloads" / "general" / "auto_update.py"
UTILITY_UPDATER = ROOT / "payloads" / "utilities" / "auto_update.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    menu_text = MENU.read_text(encoding="utf-8", errors="replace")
    general_text = GENERAL_UPDATER.read_text(encoding="utf-8", errors="replace")
    utility_text = UTILITY_UPDATER.read_text(encoding="utf-8", errors="replace")

    require('partial(exec_payload,"general/auto_update")' in menu_text, "device menu OTA path changed unexpectedly")
    require("import LCD_1in44" in general_text, "general OTA should keep direct LCD display support")
    require("def _show(" in general_text, "general OTA should render its own status screens")
    require("def git_update(" in general_text, "general OTA should own the menu update path")
    require("def resolve_fetched_ref(" in general_text, "general OTA should resolve FETCH_HEAD/origin refs after fetch")
    require('"FETCH_HEAD"' in general_text, "general OTA should fall back to FETCH_HEAD")
    require("not a valid tree name" not in general_text, "general OTA should not contain stale tree-name messaging")
    require("def archive_update(" in general_text, "general OTA should include archive fallback")
    require("def download_archive(" in general_text, "general OTA should include urllib/curl/wget download fallback")
    require('"curl"' in general_text and '"wget"' in general_text, "general OTA should fall back to curl/wget")
    require("NO INTERNET" not in general_text, "general OTA should not show the stale no-internet screen")
    require("def archive_update(" in utility_text, "utility OTA should retain archive fallback")
    require("def github_probe(" in utility_text, "utility OTA should retain GitHub probe")
    print("OTA menu entry validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
