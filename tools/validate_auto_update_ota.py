#!/usr/bin/env python3
"""Static validation for the KTOX OTA updater."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_UPDATE = ROOT / "payloads" / "utilities" / "auto_update.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    text = AUTO_UPDATE.read_text(encoding="utf-8", errors="replace")
    require("DEFAULT_GIT_URL" in text, "auto_update.py should keep a canonical GitHub remote")
    require("def _git(" in text and "timeout=" in text, "auto_update.py should use a git runner with timeouts")
    require("def ensure_git_remote(" in text, "auto_update.py should repair missing origin remote")
    require("def github_probe(" in text, "auto_update.py should probe GitHub separately from fetch")
    require("ls-remote" in text and "--heads" in text, "GitHub probe should check the remote branch")
    require("safe.directory" in text, "auto_update.py should tolerate root-owned Git safe.directory issues")
    require("fetch" in text, "auto_update.py should fetch the repository")
    require("refs/remotes/{GIT_REMOTE}/{GIT_BRANCH}" in text, "fetch should update the exact origin/main ref")
    require("github probe failed" in text, "fetch failures should report probe errors, not only generic connection text")
    require("fetch failed:" in text, "fetch failures should report git fetch stderr")
    require("def archive_update(" in text, "auto_update.py should support non-git GitHub archive fallback")
    require("codeload.github.com" in text, "archive fallback should download from GitHub codeload")
    require("def _download_archive(" in text, "archive fallback should have a dedicated downloader")
    require("curl" in text and "wget" in text, "archive fallback should use curl/wget when urllib fails")
    require("def _find_archive_root(" in text, "archive fallback should find the extracted repo by contents")
    require('"install.sh"' in text and '"payloads"' in text, "archive root detection should use repo markers")
    require('startswith("KTOx_Pi-' not in text, "archive fallback should not depend on extracted folder casing")
    require("tarfile.open" in text and "copytree" in text, "archive fallback should unpack and copy repo files")
    require("archive fallback" in text, "git_update should report when archive fallback is used")
    require("def diagnose_git_update(" in text and "--diagnose" in text, "auto_update.py should expose SSH diagnostic mode")
    require("DIAGNOSE_ONLY" in text and "if not DIAGNOSE_ONLY:" in text, "diagnostic mode should bypass LCD/GPIO setup")
    print("auto update OTA validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
