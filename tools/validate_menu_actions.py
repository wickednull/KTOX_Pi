#!/usr/bin/env python3
"""
Static validator for KTOx device menu action wiring.

Checks:
1) String submenu actions reference existing menu keys.
2) `partial(exec_payload, "...")` and `exec_payload("...")` literal paths exist.
3) `self.<method>` menu call targets exist on the owning class.
4) Bare function-name menu targets exist in module scope (defined or imported).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

MENU_FILES = ("ktox_device.py", "ktox_device_pi.py", "ktox_device_root.py")
PAYLOAD_DIR = Path("payloads")


def _defined_symbols(tree: ast.Module) -> set[str]:
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                symbols.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
    return symbols


def _class_methods(tree: ast.Module) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = {
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            out[node.name] = methods
    return out


def _find_menu_function(tree: ast.Module) -> tuple[str, ast.FunctionDef] | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_menu":
                    return node.name, item
    return None


def _menu_dict(menu_fn: ast.FunctionDef) -> ast.Dict | None:
    for node in ast.walk(menu_fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return node.value
    return None


def _iter_menu_items(menu_dict: ast.Dict):
    for key_node, val_node in zip(menu_dict.keys, menu_dict.values):
        key = key_node.value if isinstance(key_node, ast.Constant) else None
        if not isinstance(key, str):
            continue
        if isinstance(val_node, (ast.Tuple, ast.List)):
            for entry in val_node.elts:
                if isinstance(entry, ast.Tuple) and len(entry.elts) >= 2:
                    yield key, entry.elts[0], entry.elts[1], entry.lineno


def _payload_refs_by_regex(text: str) -> set[str]:
    refs = set()
    for pattern in (
        r'partial\(exec_payload,\s*"([^"]+)"\)',
        r'exec_payload\(\s*"([^"]+)"\s*[,)]',
    ):
        refs.update(re.findall(pattern, text))
    return refs


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    src = path.read_text(errors="ignore")
    tree = ast.parse(src, filename=str(path))
    symbols = _defined_symbols(tree)
    class_methods = _class_methods(tree)

    menu_ref = _find_menu_function(tree)
    if not menu_ref:
        return [f"{path}: no class _menu() found"]
    class_name, menu_fn = menu_ref
    menu_dict = _menu_dict(menu_fn)
    if menu_dict is None:
        return [f"{path}: _menu() return dict not statically parseable"]

    menu_keys = {
        key.value
        for key in menu_dict.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }

    for _, _label, action, lineno in _iter_menu_items(menu_dict):
        # submenu key string
        if isinstance(action, ast.Constant) and isinstance(action.value, str):
            target = action.value
            if not target.startswith("pay_") and target not in menu_keys:
                errors.append(f"{path}:{lineno}: submenu key '{target}' not found in _menu keys")
            continue

        # self.method action
        if isinstance(action, ast.Attribute) and isinstance(action.value, ast.Name) and action.value.id == "self":
            meth = action.attr
            if meth not in class_methods.get(class_name, set()):
                errors.append(f"{path}:{lineno}: self.{meth} not found on class {class_name}")
            continue

        # bare function action
        if isinstance(action, ast.Name):
            if action.id not in symbols:
                errors.append(f"{path}:{lineno}: callable '{action.id}' not found in module symbols")

    for rel in sorted(_payload_refs_by_regex(src)):
        payload_file = PAYLOAD_DIR / (rel if rel.endswith(".py") else f"{rel}.py")
        if not payload_file.exists():
            errors.append(f"{path}: payload ref '{rel}' -> missing {payload_file}")

    return errors


def main() -> int:
    all_errors: list[str] = []
    for file_name in MENU_FILES:
        p = Path(file_name)
        if not p.exists():
            all_errors.append(f"{file_name}: file missing")
            continue
        all_errors.extend(validate_file(p))

    if all_errors:
        print("Menu action validation failed:")
        for err in all_errors:
            print(f" - {err}")
        return 1

    print("Menu action validation passed for all device menu files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
