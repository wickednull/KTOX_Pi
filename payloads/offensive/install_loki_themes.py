#!/usr/bin/env python3
"""Install KTOx Loki cyberpunk theme pack into a loki-recon checkout."""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

THEME_PACK = Path(__file__).resolve().parent / "loki_themes"
DEFAULT_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_CANDIDATES = [
    Path(__file__).resolve().parent / "loki_theme_generator.py",
    DEFAULT_ROOT / "tools" / "generate_loki_cyberpunk_themes.py",
]


def resolve_target(path_arg: str | None) -> Path:
    """Resolve either a KTOx root, vendor/loki root, or Loki themes directory."""
    if path_arg:
        raw = Path(path_arg).expanduser().resolve()
    else:
        raw = DEFAULT_ROOT

    candidates = []
    if raw.name == "themes":
        candidates.append(raw)
    candidates.extend([
        raw / "loki" / "themes",
        raw / "vendor" / "loki" / "loki" / "themes",
        raw / "loki" / "loki" / "themes",
    ])

    for candidate in candidates:
        if candidate.parent.exists() or candidate.exists():
            return candidate
    return raw / "vendor" / "loki" / "loki" / "themes"


def generate_theme_pack(out_dir: Path) -> list[Path]:
    """Generate PNG-backed theme folders into out_dir and return them."""
    generator = next((path for path in GENERATOR_CANDIDATES if path.exists()), None)
    if generator is None:
        searched = ", ".join(str(path) for path in GENERATOR_CANDIDATES)
        print(f"Theme generator not found. Searched: {searched}", file=sys.stderr)
        return []

    spec = importlib.util.spec_from_file_location("loki_theme_generator", generator)
    if spec is None or spec.loader is None:
        print(f"Could not load theme generator: {generator}", file=sys.stderr)
        return []

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.build(out_dir)
    except ModuleNotFoundError as exc:
        if exc.name == "PIL":
            print(
                "Pillow is required to generate Loki theme PNG assets. "
                "Install it with: python3 -m pip install pillow",
                file=sys.stderr,
            )
            return []
        raise

    return sorted(p for p in out_dir.iterdir() if (p / "theme.json").exists())


def install_theme(src: Path, target_root: Path) -> None:
    dst = target_root / src.name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        help="KTOx root, vendor/loki root, or direct loki/themes path. Defaults to this repository root.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List bundled theme IDs without installing.",
    )
    args = parser.parse_args(argv)

    themes = sorted(p for p in THEME_PACK.iterdir() if (p / "theme.json").exists())
    if args.list:
        for theme in themes:
            print(theme.name)
        return 0

    if not themes:
        print(f"No bundled Loki themes found in {THEME_PACK}", file=sys.stderr)
        return 1

    target_root = resolve_target(args.target)
    if not target_root.parent.exists():
        print(
            f"Loki themes parent directory not found: {target_root.parent}\n"
            "Run setup_loki.sh first so vendor/loki is cloned, or pass a direct themes path.",
            file=sys.stderr,
        )
        return 1

    target_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ktox_loki_themes_") as tmp:
        generated_themes = generate_theme_pack(Path(tmp))
        if not generated_themes:
            return 1

        for theme in generated_themes:
            install_theme(theme, target_root)
            print(f"installed {theme.name} -> {target_root / theme.name}")

    print(f"Installed {len(generated_themes)} KTOx Loki cyberpunk themes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
