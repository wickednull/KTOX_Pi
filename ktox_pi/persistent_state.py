#!/usr/bin/env python3
"""Preserve user-owned KTOx state across installs and OTA updates."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

USER_FILES = (
    "gui_conf.json",
    "discord_webhook.txt",
    ".webui_auth.json",
    ".webui_session_secret",
    ".webui_token",
    ".tailscale_auth_key",
    "zram_config.json",
)
USER_DIRS = (
    "config",
    "roms",
    "loot",
    "img/screensaver",
)


def _copy_path(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True


def _deep_merge(defaults: dict, user: dict) -> dict:
    merged = dict(defaults)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _restore_gui_conf(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if not dst.exists():
        _copy_path(src, dst)
        return True
    try:
        defaults = json.loads(dst.read_text(encoding="utf-8") or "{}")
        user = json.loads(src.read_text(encoding="utf-8") or "{}")
        dst.write_text(json.dumps(_deep_merge(defaults, user), indent=2) + "\n", encoding="utf-8")
        return True
    except Exception:
        _copy_path(src, dst)
        return True


def backup_user_state(root: str | os.PathLike[str] = "/root/KTOx", backup_root: str | os.PathLike[str] = "/tmp") -> tuple[str, list[str]]:
    root_path = Path(root)
    backup_dir = Path(backup_root) / f"ktox_user_state_{int(time.time())}"
    copied: list[str] = []
    for rel in USER_FILES:
        if _copy_path(root_path / rel, backup_dir / rel):
            copied.append(rel)
    for rel in USER_DIRS:
        if _copy_path(root_path / rel, backup_dir / rel):
            copied.append(rel)
    return str(backup_dir), copied


def restore_user_state(backup_dir: str | os.PathLike[str], root: str | os.PathLike[str] = "/root/KTOx") -> tuple[bool, list[str]]:
    backup_path = Path(backup_dir)
    root_path = Path(root)
    if not backup_path.exists():
        return False, []
    restored: list[str] = []
    for rel in USER_FILES:
        src = backup_path / rel
        dst = root_path / rel
        if rel == "gui_conf.json":
            if _restore_gui_conf(src, dst):
                restored.append(rel)
        elif _copy_path(src, dst):
            restored.append(rel)
    for rel in USER_DIRS:
        if _copy_path(backup_path / rel, root_path / rel):
            restored.append(rel)
    return True, restored
