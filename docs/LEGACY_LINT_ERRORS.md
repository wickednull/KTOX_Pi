# Legacy lint errors (repo-wide Ruff scan)

Generated on **2026-04-28** from:

- `ruff check . --statistics`
- `ruff check . --output-format concise | ...` (directory aggregation)

These are called **legacy errors** because they are pre-existing issues across older code paths that were not introduced by the recent WiFi helper cleanup.

## Top error codes by count

- `F405` undefined-local-with-import-star-usage: **1505**
- `E701` multiple-statements-on-one-line-colon: **1058**
- `F401` unused-import: **930**
- `E722` bare-except: **566**
- `E702` multiple-statements-on-one-line-semicolon: **484**
- `E402` module-import-not-at-top-of-file: **339**
- `E401` multiple-imports-on-one-line: **297**
- `F821` undefined-name: **240**
- `F541` f-string-missing-placeholders: **201**
- `F841` unused-variable: **187**

Total currently reported: **6018**.

## Most-affected areas (top-level path grouping)

- `payloads/`: **2990**
- `Responder/`: **1625**
- `wifi/`: **41**
- several large single-file scripts (`ktox*.py`) each with tens to hundreds of findings.

## Practical meaning of “legacy” in this repo

1. A large portion lives in old/third-party-style code (`Responder/`) and older payload scripts.
2. The largest classes are style/safety debt (`import *`, multi-statements, bare `except`) rather than one new regression.
3. The prior PR intentionally scoped fixes to three WiFi helper files only, so these broader findings remained unchanged.
