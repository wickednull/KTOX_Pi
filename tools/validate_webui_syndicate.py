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

    require("layout-syndicate" in css and "grid-template-columns" in css, "Syndicate layout CSS is missing")
    require("#screen-syndicate" in css and "box-shadow: none !important" in css, "Syndicate screen must stay clean")
    require("inset 0 2px 8px rgba(0, 0, 0, 0.95)" not in css, "removed inner screen shadow returned")
    require("0 0 12px rgba(139, 0, 0, 0.15)" not in css, "removed red screen reflection returned")

    print("WebUI Syndicate/PWA validation passed")


if __name__ == "__main__":
    main()
