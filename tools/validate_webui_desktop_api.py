from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    server = read("web_server.py")
    app = read("web/app.js")
    manager = read("payloads/offensive/novnc_manager.py")

    require("/api/desktop/install-deps" in app, "desktop dependency install endpoint is not requested by app.js")
    require("`/api/desktop/${action}`" in app, "desktop start/stop endpoints are not requested by app.js")

    require("payloads.offensive" in server and "novnc_manager" in server, "web_server.py does not import the noVNC manager")
    for route in (
        "/api/desktop/status",
        "/api/desktop/start",
        "/api/desktop/stop",
        "/api/desktop/install-deps",
    ):
        require(route in server, f"{route} is not routed by web_server.py")

    for method in (
        "status()",
        "start_server()",
        "stop_server()",
        "install_dependencies_async()",
    ):
        require(method in server, f"web_server.py does not call novnc_manager.{method}")

    require("def status()" in manager, "noVNC manager status function is missing")
    require("def start_server(" in manager, "noVNC manager start function is missing")
    require("def stop_server(" in manager, "noVNC manager stop function is missing")
    require("def install_dependencies_async(" in manager, "noVNC manager async install function is missing")

    print("WebUI desktop noVNC API validation passed")


if __name__ == "__main__":
    main()
