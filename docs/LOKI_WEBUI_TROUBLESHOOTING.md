# Loki WebUI Troubleshooting

KTOX uses the `brainphreak/loki-recon` project as a vendored Git submodule at
`vendor/loki`. The KTOX launcher is `payloads/offensive/loki_manager.py`.

## Quick Checks

```bash
cd /root/KTOx
python3 payloads/offensive/verify_loki_structure.py
python3 payloads/offensive/loki_manager.py status
```

Expected vendor files include:

- `vendor/loki/loki.py`
- `vendor/loki/loki/Loki.py`
- `vendor/loki/loki/webapp.py`
- `vendor/loki/loki/web/index.html`

## Start, Stop, Restart

```bash
cd /root/KTOx
python3 payloads/offensive/loki_manager.py start
python3 payloads/offensive/loki_manager.py status
python3 payloads/offensive/loki_manager.py stop
```

The WebUI listens on `http://<device-ip>:8000/` by default.

## First-Time Setup

If the vendor checkout or Python environment is missing, run:

```bash
cd /root/KTOx
sudo bash setup_loki.sh /root/KTOx
```

That script validates `vendor/loki`, installs system dependencies, creates
`vendor/loki/.venv`, and installs Loki's Python dependencies.

## Port 8000 Is Closed

Check whether Loki is running:

```bash
python3 payloads/offensive/loki_manager.py status
```

If it is stopped, start it:

```bash
python3 payloads/offensive/loki_manager.py start
```

If another process owns the port:

```bash
sudo lsof -i :8000
```

Stop only the process you identify as Loki. Avoid broad `pkill` cleanup unless
you have confirmed it targets only the Loki process.

## WebUI Loads But API Fails

Check common endpoints:

```bash
curl -i http://localhost:8000/
curl -i http://localhost:8000/api/v1/status
python3 payloads/offensive/test_loki_webui.py
```

Then inspect the log:

```bash
tail -n 80 /root/KTOx/loot/loki.log
```

## Vendor Layout Looks Wrong

Run:

```bash
python3 payloads/offensive/verify_loki_structure.py
```

If files are missing, update the submodule on a development checkout:

```bash
git submodule update --init --recursive vendor/loki
```

On a deployed Pi without the full Git checkout, rerun setup:

```bash
sudo bash setup_loki.sh /root/KTOx
```

## Collect Diagnostics

```bash
cd /root/KTOx
python3 payloads/offensive/verify_loki_structure.py > /tmp/loki_diag.txt
python3 payloads/offensive/loki_manager.py status >> /tmp/loki_diag.txt
python3 payloads/offensive/test_loki_webui.py >> /tmp/loki_diag.txt
tail -n 80 loot/loki.log >> /tmp/loki_diag.txt 2>/dev/null || true
cat /tmp/loki_diag.txt
```

## Key Files

| File | Purpose |
|------|---------|
| `/root/KTOx/vendor/loki/` | Vendored `brainphreak/loki-recon` checkout |
| `/root/KTOx/vendor/loki/loki.py` | Loki entry point |
| `/root/KTOx/vendor/loki/loki/webapp.py` | Loki WebUI application |
| `/root/KTOx/payloads/offensive/loki_manager.py` | KTOX start/stop/status manager |
| `/root/KTOx/loot/loki.log` | KTOX Loki manager log |

## Upstream

- https://github.com/brainphreak/loki-recon
