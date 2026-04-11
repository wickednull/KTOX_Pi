# #!/usr/bin/env python3
“””
payload_compat.py — KTOx ↔ RaspyJack payload compatibility converter

Converts KTOx_Pi payloads so they run on RaspyJack, or converts
RaspyJack payloads so they run on KTOx_Pi.

Works on a single file, a folder (all .py files), or via –stdin.

## Usage examples

# Single file, KTOx → RaspyJack (writes alongside original as .rj.py)

python3 payload_compat.py –to raspyjack payloads/wifi/deauth.py

# Whole directory into an output folder

python3 payload_compat.py –to raspyjack payloads/wifi/ -o /tmp/rj_payloads/

# RaspyJack payload → KTOx (in-place, with auto-backup)

python3 payload_compat.py –to ktox my_rj_payload.py –in-place

# Preview changes without writing anything

python3 payload_compat.py –to raspyjack payloads/ –dry-run

# Custom paths

python3 payload_compat.py –to raspyjack payloads/snake.py \
–rj-root /home/pi/RaspyJack –ktox-root /root/KTOx

## Options

–to {raspyjack|ktox}   Target platform (required)
FILE_OR_DIR             Source file or directory
-o, –output PATH       Output file or directory (default: <name>.rj.py or <name>.ktox.py)
–in-place              Overwrite source file (backup saved as <file>.bak)
–dry-run               Print what would change; write nothing
–rj-root PATH          RaspyJack install root  (default: /root/RaspyJack)
–ktox-root PATH        KTOx install root       (default: /root/KTOx)
–quiet                 Suppress diff output; only print summary
“””

import argparse
import os
import re
import shutil
import sys
import textwrap
from pathlib import Path

# ── Shim inserted into KTOx → RaspyJack payloads ────────────────────────────

# Replaces the `from payloads._input_helper import get_button` line.

# Provides an identical get_button(pins, gpio) API using rj_input natively.

_RJ_SHIM = textwrap.dedent(”””  
# ── get_button shim (added by payload_compat.py for RaspyJack) ─────────
try:
import ktox_input as _rj_input
except Exception:
_rj_input = None
_RJ_BTN_MAP = {
“KEY_UP_PIN”:    “UP”,    “KEY_DOWN_PIN”:  “DOWN”,
“KEY_LEFT_PIN”:  “LEFT”,  “KEY_RIGHT_PIN”: “RIGHT”,
“KEY_PRESS_PIN”: “OK”,
“KEY1_PIN”: “KEY1”, “KEY2_PIN”: “KEY2”, “KEY3_PIN”: “KEY3”,
}
def get_button(pins, gpio):
"""RaspyJack-compatible drop-in for KTOx _input_helper.get_button."""
if _rj_input is not None:
try:
raw = _rj_input.get_virtual_button()
if raw:
mapped = _RJ_BTN_MAP.get(raw)
if mapped:
return mapped
except Exception:
pass
for btn, pin in pins.items():
if gpio.input(pin) == 0:
return btn
return None
# ── end shim ────────────────────────────────────────────────────────────
“””)

# Import line added to RaspyJack → KTOx payloads (if not already present)

_KTOX_IMPORT = “from payloads._input_helper import get_button\n”

# ── Conversion rules ─────────────────────────────────────────────────────────

def _make_rules_to_rj(ktox_root: str, rj_root: str) -> list[tuple]:
“””
Return ordered list of (pattern, replacement) for KTOx → RaspyJack.
Patterns are plain strings (not regex) unless prefixed with RE:.
“””
return [
# Input helper import → inject shim marker (replaced in post-process)
(“from payloads._input_helper import get_button”,
“**KTOX_SHIM_PLACEHOLDER**”),

```
    # Root path variable name
    ("KTOX_ROOT", "RJ_ROOT"),

    # Hard-coded root strings
    (f"'{ktox_root}'",  f"'{rj_root}'"),
    (f'"{ktox_root}"',  f'"{rj_root}"'),

    # Bare path references inside strings (e.g. os.path.join calls)
    (ktox_root, rj_root),

    # Loot sub-paths (belt-and-suspenders)
    (f"{ktox_root}/loot", f"{rj_root}/loot"),
    (f"{ktox_root}/wordlists", f"{rj_root}/wordlists"),
    (f"{ktox_root}/img", f"{rj_root}/img"),
]
```

def _make_rules_to_ktox(ktox_root: str, rj_root: str) -> list[tuple]:
“””
Return ordered list of (pattern, replacement) for RaspyJack → KTOx.
“””
return [
# Root path variable name
(“RJ_ROOT”, “KTOX_ROOT”),

```
    # Hard-coded root strings
    (f"'{rj_root}'",  f"'{ktox_root}'"),
    (f'"{rj_root}"',  f'"{ktox_root}"'),

    # Bare path references
    (rj_root, ktox_root),

    # Loot sub-paths
    (f"{rj_root}/loot", f"{ktox_root}/loot"),
    (f"{rj_root}/wordlists", f"{ktox_root}/wordlists"),
    (f"{rj_root}/img", f"{ktox_root}/img"),
]
```

# ── Core conversion logic ────────────────────────────────────────────────────

def _convert_to_rj(source: str, ktox_root: str, rj_root: str) -> str:
“”“Convert a KTOx payload string to RaspyJack.”””
result = source
for old, new in _make_rules_to_rj(ktox_root, rj_root):
result = result.replace(old, new)

```
# Replace shim placeholder with actual shim
result = result.replace("__KTOX_SHIM_PLACEHOLDER__", _RJ_SHIM.rstrip("\n"))

# If source used get_button but didn't have the import line
# (e.g. already had it under a different form), inject shim before first import
if "get_button" in source and "__KTOX_SHIM_PLACEHOLDER__" not in source and _RJ_SHIM.split("\n")[2] not in result:
    result = _inject_before_first_import(result, _RJ_SHIM)

return result
```

def _convert_to_ktox(source: str, ktox_root: str, rj_root: str) -> str:
“”“Convert a RaspyJack payload string to KTOx.”””
result = source
for old, new in _make_rules_to_ktox(ktox_root, rj_root):
result = result.replace(old, new)

```
# Add _input_helper import if the file uses GPIO buttons and doesn't
# already import get_button
uses_gpio_buttons = (
    "GPIO.input(" in result or
    "gpio.input(" in result or
    "get_button" in result
)
already_imported = "from payloads._input_helper import get_button" in result

if uses_gpio_buttons and not already_imported:
    result = _inject_before_first_import(result, _KTOX_IMPORT)

return result
```

def _inject_before_first_import(source: str, injection: str) -> str:
“”“Insert injection text before the first import statement in source.”””
lines = source.splitlines(keepends=True)
insert_at = 0
for i, line in enumerate(lines):
stripped = line.lstrip()
if stripped.startswith(“import “) or stripped.startswith(“from “):
insert_at = i
break
else:
# No import found — prepend at top
return injection + source

```
lines.insert(insert_at, injection if injection.endswith("\n") else injection + "\n")
return "".join(lines)
```

# ── Diff display ─────────────────────────────────────────────────────────────

def _summarise_changes(original: str, converted: str, label: str) -> list[str]:
“”“Return human-readable lines describing what changed.”””
orig_lines = original.splitlines()
conv_lines = converted.splitlines()
changes = []
if len(orig_lines) != len(conv_lines):
changes.append(f”  {label}: line count {len(orig_lines)} → {len(conv_lines)}”)
# Find changed lines
max_lines = max(len(orig_lines), len(conv_lines))
diff_count = 0
for i in range(max_lines):
ol = orig_lines[i] if i < len(orig_lines) else “<missing>”
cl = conv_lines[i] if i < len(conv_lines) else “<added>”
if ol != cl:
diff_count += 1
if diff_count <= 8:  # Show first 8 changed lines
changes.append(f”  L{i+1:4d}  - {ol.rstrip()}”)
changes.append(f”        + {cl.rstrip()}”)
if diff_count > 8:
changes.append(f”  … and {diff_count - 8} more changed line(s)”)
return changes

# ── File processor ────────────────────────────────────────────────────────────

def process_file(
src_path: Path,
dst_path: Path | None,
direction: str,
ktox_root: str,
rj_root: str,
dry_run: bool,
in_place: bool,
quiet: bool,
) -> bool:
“””
Process one .py file. Returns True if any changes were made.
“””
try:
source = src_path.read_text(encoding=“utf-8”, errors=“replace”)
except Exception as e:
print(f”[ERROR] Cannot read {src_path}: {e}”, file=sys.stderr)
return False

```
if direction == "raspyjack":
    converted = _convert_to_rj(source, ktox_root, rj_root)
else:
    converted = _convert_to_ktox(source, ktox_root, rj_root)

changed = converted != source
tag = "CHANGED" if changed else "no-op  "
print(f"  [{tag}] {src_path.name}")

if changed and not quiet:
    for line in _summarise_changes(source, converted, src_path.name):
        print(line)

if dry_run or not changed:
    return changed

# Determine output path
if dst_path is None:
    if in_place:
        bak = src_path.with_suffix(src_path.suffix + ".bak")
        shutil.copy2(src_path, bak)
        dst_path = src_path
    else:
        suffix = ".rj.py" if direction == "raspyjack" else ".ktox.py"
        dst_path = src_path.with_name(src_path.stem + suffix)

dst_path.parent.mkdir(parents=True, exist_ok=True)
try:
    dst_path.write_text(converted, encoding="utf-8")
    if dst_path != src_path:
        print(f"         → {dst_path}")
except Exception as e:
    print(f"[ERROR] Cannot write {dst_path}: {e}", file=sys.stderr)
    return False

return changed
```

# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
parser = argparse.ArgumentParser(
description=“Convert KTOx payloads ↔ RaspyJack payloads”,
formatter_class=argparse.RawDescriptionHelpFormatter,
epilog=**doc**,
)
parser.add_argument(”–to”, required=True, choices=[“raspyjack”, “ktox”],
dest=“direction”, metavar=”{raspyjack|ktox}”,
help=“Target platform”)
parser.add_argument(“source”, nargs=”?”, default=None,
help=“Source .py file or directory”)
parser.add_argument(”-o”, “–output”, default=None,
help=“Output file or directory”)
parser.add_argument(”–in-place”, action=“store_true”,
help=“Overwrite source file (auto-backup as .bak)”)
parser.add_argument(”–dry-run”, action=“store_true”,
help=“Show what would change; write nothing”)
parser.add_argument(”–rj-root”, default=”/root/RaspyJack”,
help=“RaspyJack install root  (default: /root/RaspyJack)”)
parser.add_argument(”–ktox-root”, default=”/root/KTOx”,
help=“KTOx install root       (default: /root/KTOx)”)
parser.add_argument(”–quiet”, action=“store_true”,
help=“Only print summary, suppress per-line diffs”)
args = parser.parse_args()

```
if args.source is None:
    parser.print_help()
    sys.exit(0)

src = Path(args.source)
out = Path(args.output) if args.output else None
direction = args.direction

target_label = "RaspyJack" if direction == "raspyjack" else "KTOx_Pi"
print(f"\n payload_compat.py  →  converting to {target_label}")
print(f"  KTOx root  : {args.ktox_root}")
print(f"  RJ root    : {args.rj_root}")
if args.dry_run:
    print("  [DRY RUN — no files will be written]")
print()

files: list[tuple[Path, Path | None]] = []

if src.is_file():
    if out and out.is_dir():
        dst = out / src.name
    else:
        dst = out
    files.append((src, dst))

elif src.is_dir():
    py_files = sorted(src.rglob("*.py"))
    if not py_files:
        print(f"No .py files found in {src}", file=sys.stderr)
        sys.exit(1)
    for f in py_files:
        if out:
            rel = f.relative_to(src)
            dst = out / rel
        else:
            dst = None
        files.append((f, dst))
else:
    print(f"[ERROR] {src} is not a file or directory.", file=sys.stderr)
    sys.exit(1)

changed_count = 0
for src_path, dst_path in files:
    if process_file(
        src_path, dst_path,
        direction, args.ktox_root, args.rj_root,
        args.dry_run, args.in_place, args.quiet,
    ):
        changed_count += 1

total = len(files)
verb = "would change" if args.dry_run else "changed"
print(f"\n  Done. {changed_count}/{total} file(s) {verb}.")
if args.dry_run:
    print("  Run without --dry-run to apply changes.")
```

if **name** == “**main**”:
main()
