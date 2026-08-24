from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = read("web/index.html")
    app = read("web/app.js")
    css = read("web/ui.css")
    shared = read("web/shared.js")

    require('rel="manifest"' in index and "manifest.webmanifest" in index, "PWA manifest is not linked")
    require((ROOT / "web" / "manifest.webmanifest").exists(), "PWA manifest file is missing")
    require('id="deviceShell"' in index, "device shell is missing")
    require("layout-syndicate" in index and "screen-syndicate" in index, "Syndicate layout/canvas is missing")

    require("const canvasSyndicate" in app and "ctxSyndicate" in app, "Syndicate canvas is not wired")
    require("setLayoutVisible" in app, "theme switching does not explicitly show/hide layouts")
    require("ensureDeviceShellChild" in app, "mis-nested device layouts are not repaired")
    require("layoutSyndicate" in app, "Syndicate layout is not handled in JS")
    require("theme-syndicate" in app, "legacy Syndicate theme class is not cleared")

    require("getWsUrlCandidates" in shared or "getWsUrlCandidates" in app, "WebSocket candidates are missing")
    require("pageshow" in app and "online" in app and "visibilitychange" in app, "iOS reconnect hooks are missing")
    require("SERVER_HEARTBEAT_TIMEOUT" in app, "silent WebSocket drop detection is missing")
    require("WS_CONNECT_TIMEOUT" in app, "iOS WebSocket connect timeout is missing")
    require("return [\n          sameOriginWs," in shared, "same-origin WebSocket must be tried first on ported web UI")

    require("layout-syndicate" in css and "display: block !important" in css, "Syndicate layout must match vertical handheld layouts")
    require("grid-template-columns: minmax(260px, 1fr) minmax(232px, auto)" not in css, "Syndicate controls must not be a right-side grid column")
    require("#screen-syndicate" in css and "box-shadow: none !important" in css, "Syndicate screen must stay clean")
    require("inset 0 2px 8px rgba(0, 0, 0, 0.95)" not in css, "removed inner screen shadow returned")
    require("0 0 12px rgba(139, 0, 0, 0.15)" not in css, "removed red screen reflection returned")
    require('id="mobileTopBar"' in index, "mobile top bar must be addressable for safe-area positioning")
    require("#systemTab.mobile-system-tab" in css and "body.mobile-system-overlay #systemTab" not in css, "mobile system monitor must remain a normal tab")
    require("#deviceTab.mobile-device-focus" in css and "overflow: hidden !important" in css, "mobile device tab must not scroll the virtual device")
    require(".status-text[data-state=\"connecting\"]" in css and "ktoxStatusBlink" in css, "WebSocket status must be a blinking LED")
    require("statusEl.textContent = ''" in app and "dataset.state" in app, "WebSocket status text/IP must be hidden behind LED state")

    print("WebUI Syndicate/PWA validation passed")


if __name__ == "__main__":
    main()
