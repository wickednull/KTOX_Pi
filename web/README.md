# KTOx WebUI

This WebUI provides a browser-based remote control for the KTOx LCD UI.
It streams LCD frames to the browser and forwards button input back to the device.

## Required folders and files on device
- `web/`
  - `web/index.html`
  - `web/app.js`
  - `web/ktox.png`
- `payloads/general/webui.py` (on-device controller that starts/stops the WebUI stack)
- `device_server.py` (WebSocket server for frames + input)
- `web_server.py` (static WebUI + read-only loot API)
- `rj_input.py` (virtual input bridge for browser controls)
- `LCD_1in44.py` and `LCD_Config.py` (LCD driver used by `payloads/general/webui.py`)

## Dependencies (install script)
These are the WebUI-relevant packages in `install_ktox.sh`:
- `python3-websockets` (WebSocket server dependency for `device_server.py`)
- `python3-pil` (Pillow for LCD rendering in `payloads/general/webui.py`)
- `python3-rpi.gpio` (GPIO input in `payloads/general/webui.py`)
- `fonts-dejavu-core` (font files used by the on-device UI)
- `procps` (provides `pkill`, used to stop the WebUI processes)

## How it runs
`payloads/general/webui.py` launches:
- `device_server.py` (WebSocket server on port `8765`)
- `web_server.py` (static frontend + loot API) on port `8080`

Open in a browser (recommended):
```
https://<device-ip>/
```

Fallback during rollout/troubleshooting:
```
http://<device-ip>:8080
```

## Authentication flow
- First run: blocking setup overlay asks for admin username/password.
- After setup: blocking login overlay appears on WebUI and IDE.
- Successful login creates an HTTP-only session cookie used for API calls.
- WebSocket access uses a short-lived WS ticket issued by `web_server.py`.
- Emergency fallback: recovery token auth is still supported.

## HTTPS/WSS architecture
- Public entrypoint: Caddy on `:443` (`https://<device-ip>/`).
- Upstream Web UI/API: `127.0.0.1:8080` (proxied by Caddy).
- Upstream device WebSocket: `127.0.0.1:8765` exposed as `wss://<device-ip>/ws`.
- On HTTPS requests, the backend sets session cookies with `Secure; HttpOnly; SameSite=Strict`.

## Self-signed certificate trust
- Installer config uses `tls internal` (self-signed local CA via Caddy).
- First browser visit may show a certificate warning until trust is added.
- You can continue with warning temporarily, or install/trust Caddy's local CA on your client for a clean lock icon.

## Migration and fallback behavior
- Existing auth/session logic is unchanged; only transport is upgraded (HTTP -> HTTPS, WS -> WSS on `/ws`).
- Legacy direct ports (`8080` and `8765`) remain available so access is not bricked if proxy setup fails.
- If Caddy installation/configuration fails, installer prints remediation and keeps current services running.


## Optional Kali Desktop noVNC mode
The Pentest tab can now start an optional browser-hosted Kali Linux desktop. This does not replace the KTOX WebUI or the structured Kali Pentest Suite; it adds a noVNC desktop frame above the existing tool console for GUI-heavy Kali workflows.

This is **not** another KTOX screen mirror. The existing LCD/WebUI mirror still streams the KTOX menu frame from `/dev/shm/ktox_last.jpg`; noVNC controls a Kali X desktop session on the same device. In the default `virtual` mode, that desktop is a headless X session that can launch Kali GUI tools and modify the same filesystem, network interfaces, loot, and processes as the rest of KTOX. If a real Kali desktop is already running on HDMI/console, set `KTOX_DESKTOP_MODE=existing` and `KTOX_DESKTOP_DISPLAY=:0` to attach noVNC to that existing X display instead.

Runtime pieces started by `payloads/offensive/novnc_manager.py`:
- Default `virtual` mode: `Xvfb` creates the virtual display (default `:1`, `1280x720x24`).
- Default `virtual` mode: a lightweight window manager is selected automatically (`startxfce4`, `openbox-session`, `lxsession`, `fluxbox`, `icewm-session`, or `xterm`).
- Existing-display mode: skips `Xvfb` and the window manager, then points `x11vnc` at `KTOX_DESKTOP_DISPLAY`.
- `x11vnc` exposes the selected display on localhost VNC port `5901` with an auto-generated password.
- `websockify`/`novnc_proxy` exposes noVNC on port `6080`.

WebUI controls/API:
- Open the main WebUI **Pentest** tab to auto-start the desktop frame.
- `GET /api/desktop/status`
- `POST /api/desktop/start`
- `POST /api/desktop/stop`

Caddy HTTPS deployments proxy `/desktop/*` to `127.0.0.1:6080`, including the noVNC WebSocket. Direct HTTP fallback uses the manager's `embed_url` on port `6080`.

Optional environment variables:
- `KTOX_NOVNC_HOST` (default `0.0.0.0`)
- `KTOX_NOVNC_PORT` (default `6080`)
- `KTOX_VNC_PORT` (default `5901`)
- `KTOX_DESKTOP_MODE` (`virtual` by default, or `existing` to control an existing Kali X display)
- `KTOX_DESKTOP_USE_EXISTING` (`1`/`true` also enables existing-display mode)
- `KTOX_DESKTOP_DISPLAY` (default `:1`; use `:0` for a normal HDMI/console X desktop)
- `KTOX_DESKTOP_GEOMETRY` (default `1280x720x24`, virtual mode only)
- `KTOX_XAUTHORITY` (optional Xauthority file for existing-display mode)
- `KTOX_NOVNC_PASSWORD` or `KTOX_NOVNC_PASSWORD_FILE`

## Environment variables (optional)
`device_server.py` supports:
- `RJ_FRAME_PATH` (default `/dev/shm/ktox_last.jpg`)
- `RJ_WS_HOST` (default `0.0.0.0`)
- `RJ_WS_PORT` (default `8765`)
- `RJ_FPS` (default `10`)
- `RJ_WS_TOKEN` (optional shared token)
- `RJ_WS_TOKEN_FILE` (optional token file; default `/root/KTOx/.webui_token`)
- `RJ_WEB_AUTH_FILE` (default `/root/KTOx/.webui_auth.json`)
- `RJ_WEB_AUTH_SECRET_FILE` (default `/root/KTOx/.webui_session_secret`)
- `RJ_WEB_SESSION_TTL` (default `28800`)
- `RJ_WEB_WS_TICKET_TTL` (default `120`)
- `RJ_INPUT_SOCK` (default `/dev/shm/rj_input.sock`)

## Notes
- The LCD frame mirror must exist at `RJ_FRAME_PATH`.
- If you want browser input to control the UI, `rj_input.py` must be present and
  the main UI must import it so it consumes virtual button events.

## Local sanity check (JS syntax)
From repo root:
```bash
./scripts/check_webui_js.sh
```
This verifies `web/shared.js`, `web/app.js`, and `web/ide.js` parse cleanly under Node.
