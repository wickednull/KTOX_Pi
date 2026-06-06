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
    server = read("web_server.py")
    manifest = read("web/manifest.webmanifest")

    require('rel="icon"' in index and "ktox.png" in index, "browser icon link is missing")
    require('rel="apple-touch-icon"' in index and "ktox.png" in index, "iOS icon link is missing")
    require('"icons"' in manifest and "ktox.png" in manifest, "PWA manifest icons are missing")

    require('id="systemTab"' in index, "mobile system monitor panel is missing")
    for element_id in (
        "mobileSystemStatus",
        "mobSysCpuValue",
        "mobSysTempValue",
        "mobSysMemValue",
        "mobSysMemMeta",
        "mobSysDiskValue",
        "mobSysDiskMeta",
        "mobSysUptime",
        "mobSysLoad",
        "mobSysPayload",
        "mobSysInterfaces",
        "mobSysHostname",
        "mobSysKernel",
        "mobSysTailscale",
    ):
        require(f'id="{element_id}"' in index, f"{element_id} is missing from mobile system monitor")
        require(element_id in app, f"{element_id} is not wired in app.js")

    require("loadMobileSystemStatus" in app, "mobile system loader is missing")
    require("setActiveTab('system')" in app, "mobile system nav does not open the system panel")
    require("tab === 'device' || tab === 'terminal';" in app, "system monitor must be a real mobile tab, not part of the device tab")
    require("mobile-system-overlay" not in app, "mobile system overlay state should not be used")
    css = read("web/ui.css")
    require("#systemTab.mobile-system-tab" in css, "mobile system tab styling is missing")
    require("body.mobile-system-overlay #systemTab" not in css, "old mobile system overlay CSS returned")

    require("/dev/shm/ktox_payload_request.json" in server, "WebUI no longer writes KTOx payload request path")
    require("/dev/shm/rj_payload_request.json" in server, "WebUI no longer writes compatibility payload request path")
    require("dos_syn_flood.py" in server or '"dos"' in server, "DoS/SYN flood payload category coverage is missing")

    require('"hostname"' in server and '"kernel"' in server and '"tailscale"' in server, "extended system stats are missing")

    print("WebUI mobile system/icon/payload validation passed")


if __name__ == "__main__":
    main()
