#!/usr/bin/env python3
"""Validate KTOx Game Center PS1 ROM support."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GAME_CENTER = ROOT / "payloads" / "games" / "game_center.py"


def _literal_from_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} assignment not found")


def main() -> int:
    source = GAME_CENTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    emulators = _literal_from_assignment(tree, "EMULATORS")

    psx = emulators.get("psx")
    assert psx, "psx emulator metadata missing"
    assert ".bin" in psx.get("ext", []), "PS1 .bin ROMs are not recognized"

    empty_library = re.search(r"No ROMs yet\.[^']+", source)
    assert empty_library, "empty-library upload hint not found"
    assert ".bin" in empty_library.group(0), "Game Center UI/help text does not mention .bin uploads"

    print("Game Center PS1 .bin support metadata is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
