#!/usr/bin/env python3
"""Generate KTOx cyberpunk Loki theme pack assets.

The generated folders are intentionally self-contained so they can be copied
into ``vendor/loki/loki/themes`` after loki-recon has been cloned.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "payloads" / "offensive" / "loki_themes"

ACTIONS = [
    "IDLE",
    "NetworkScanner",
    "NmapVulnScanner",
    "SSHBruteforce",
    "FTPBruteforce",
    "TelnetBruteforce",
    "SMBBruteforce",
    "SQLBruteforce",
    "RDPBruteforce",
    "StealFilesSSH",
    "StealFilesFTP",
    "StealFilesSMB",
    "StealFilesTelnet",
    "StealDataSQL",
    "LogStandalone",
    "LogStandalone2",
    "ZombifySSH",
]

STAT_LABELS = [
    ("TGT", 260, 7), ("PRT", 335, 7), ("VUL", 410, 7),
    ("CRD", 260, 45), ("ZMB", 335, 45), ("DAT", 410, 45),
    ("¥", 4, 77), ("LVL", 4, 197), ("NET", 201, 77), ("ATK", 201, 197),
]
STAT_LABELS_P = [
    ("T", 8, 49), ("P", 82, 49), ("V", 156, 49),
    ("C", 8, 87), ("Z", 82, 87), ("D", 156, 87),
    ("¥", 4, 361), ("LV", 4, 445), ("KB", 154, 361), ("AT", 154, 445),
]

THEMES = {
    "neon_runner": {
        "name": "Neon Runner",
        "subtitle": "HOT PINK // CYAN STREET OPS",
        "bg": (4, 2, 18), "panel": (14, 8, 35), "grid": (24, 188, 210),
        "accent": (255, 42, 170), "accent2": (0, 245, 255), "text": (220, 255, 255),
        "hair": (0, 240, 255), "jacket": (25, 20, 70), "trim": (255, 42, 170),
        "moods": {"target": "Overdrive", "swarm": "Neon Riot", "recon": "Ghostwalk"},
        "web": {"bg_dark": "#050212", "bg_surface": "#0f0823", "bg_elevated": "#190d35", "accent": "#ff2aaa", "accent_bright": "#00f5ff", "accent_dim": "#8d1f75", "text_primary": "#dcffff", "text_secondary": "#88e8f0", "text_muted": "#5c6f8e", "border": "#263d66", "border_light": "#ff2aaa", "glow": "0 0 14px rgba(255, 42, 170, 0.36)", "font_title": "'Orbitron', 'Arial Black', sans-serif", "nav_label_display": "Neon"},
    },
    "chrome_mantis": {
        "name": "Chrome Mantis",
        "subtitle": "ACID GREEN // BLACK CHROME",
        "bg": (2, 8, 8), "panel": (7, 22, 20), "grid": (90, 255, 95),
        "accent": (164, 255, 40), "accent2": (55, 255, 210), "text": (220, 255, 220),
        "hair": (30, 220, 170), "jacket": (18, 36, 34), "trim": (164, 255, 40),
        "moods": {"target": "Slice", "swarm": "Mantis Storm", "recon": "Optic Camo"},
        "web": {"bg_dark": "#020808", "bg_surface": "#071614", "bg_elevated": "#0b211f", "accent": "#a4ff28", "accent_bright": "#37ffd2", "accent_dim": "#4a8f28", "text_primary": "#dcffdc", "text_secondary": "#9bddb2", "text_muted": "#587061", "border": "#1d4b3b", "border_light": "#55ff91", "glow": "0 0 14px rgba(164, 255, 40, 0.32)", "font_title": "'Share Tech Mono', monospace", "nav_label_display": "Chrome"},
    },
    "edge_fury": {
        "name": "Edge Fury",
        "subtitle": "GOLD CREW // REDLINE BOOST",
        "bg": (13, 6, 9), "panel": (34, 14, 22), "grid": (255, 202, 66),
        "accent": (255, 216, 74), "accent2": (255, 56, 76), "text": (255, 238, 190),
        "hair": (255, 218, 80), "jacket": (45, 23, 52), "trim": (255, 56, 76),
        "moods": {"target": "Redline", "swarm": "Crew Rush", "recon": "Back Alley"},
        "web": {"bg_dark": "#0d0609", "bg_surface": "#220e16", "bg_elevated": "#321521", "accent": "#ffd84a", "accent_bright": "#ff384c", "accent_dim": "#9c6f24", "text_primary": "#ffeebe", "text_secondary": "#eabf7b", "text_muted": "#7f5964", "border": "#57323a", "border_light": "#ff384c", "glow": "0 0 14px rgba(255, 56, 76, 0.34)", "font_title": "'Rajdhani', 'Arial Narrow', sans-serif", "nav_label_display": "Edge"},
    },
    "icewire_ghost": {
        "name": "Icewire Ghost",
        "subtitle": "WHITE ICE // BLUE INTRUSION",
        "bg": (3, 7, 20), "panel": (9, 18, 45), "grid": (124, 186, 255),
        "accent": (185, 225, 255), "accent2": (78, 126, 255), "text": (236, 248, 255),
        "hair": (202, 232, 255), "jacket": (26, 30, 62), "trim": (78, 126, 255),
        "moods": {"target": "Black ICE", "swarm": "Blue Crash", "recon": "Silent Trace"},
        "web": {"bg_dark": "#030714", "bg_surface": "#09122d", "bg_elevated": "#101c42", "accent": "#b9e1ff", "accent_bright": "#4e7eff", "accent_dim": "#315190", "text_primary": "#ecf8ff", "text_secondary": "#9ebce8", "text_muted": "#596d96", "border": "#22365f", "border_light": "#7cbbff", "glow": "0 0 14px rgba(124, 186, 255, 0.30)", "font_title": "'Exo 2', 'Arial', sans-serif", "nav_label_display": "Icewire"},
    },
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for base in [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/local/share/fonts")]:
        for name in names:
            path = base / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def add_scanlines(draw: ImageDraw.ImageDraw, size: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    w, h = size
    for y in range(0, h, 4):
        draw.line((0, y, w, y), fill=color)


def glow_line(draw: ImageDraw.ImageDraw, xy: Iterable[int], color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = xy
    for width, alpha in [(5, 45), (3, 90), (1, 255)]:
        draw.line((x1, y1, x2, y2), fill=color + (alpha,), width=width)


def background(theme: dict, size: tuple[int, int], portrait: bool = False, title: str = "") -> Image.Image:
    img = Image.new("RGBA", size, theme["bg"] + (255,))
    d = ImageDraw.Draw(img, "RGBA")
    w, h = size
    # gradient blocks
    for i in range(0, max(w, h), 8):
        alpha = int(18 + 30 * math.sin(i / 21))
        d.line((0, i, w, i - w // 2), fill=theme["panel"] + (alpha,), width=5)
    for x in range(0, w, 24):
        d.line((x, 0, x, h), fill=theme["grid"] + (30,))
    for y in range(0, h, 24):
        d.line((0, y, w, y), fill=theme["grid"] + (24,))
    add_scanlines(d, size, (0, 0, 0, 38))

    # panels
    if portrait:
        panels = [(2, 2, w - 3, 112), (4, 118, w - 5, 304), (4, 316, w - 5, h - 4)]
    else:
        panels = [(2, 2, 245, 70), (250, 2, w - 3, 70), (2, 74, 246, h - 4), (250, 74, w - 3, h - 4)]
    for p in panels:
        d.rounded_rectangle(p, radius=5, fill=theme["panel"] + (210,), outline=theme["grid"] + (190,), width=1)
        d.rectangle((p[0] + 2, p[1] + 2, p[2] - 2, p[1] + 4), fill=theme["accent"] + (200,))

    # angular frise and battery shell
    if portrait:
        d.text((8, 8), title.upper(), font=font(18, True), fill=theme["accent"] + (255,))
        d.text((8, 29), theme["subtitle"], font=font(8), fill=theme["accent2"] + (255,))
        d.rounded_rectangle((178, 8, 218, 31), radius=3, outline=theme["accent2"] + (220,), width=2)
        d.rectangle((218, 14, 221, 25), fill=theme["accent2"] + (220,))
        for label, x, y in STAT_LABELS_P:
            d.text((x, y - 12), label, font=font(9, True), fill=theme["accent2"] + (255,))
        glow_line(d, (8, 174, w - 8, 174), theme["accent"])
        d.text((8, 312), "AVATAR", font=font(10, True), fill=theme["accent2"] + (255,))
    else:
        d.text((8, 8), title.upper(), font=font(24, True), fill=theme["accent"] + (255,))
        d.text((10, 36), theme["subtitle"], font=font(9), fill=theme["accent2"] + (255,))
        d.rounded_rectangle((188, 8, 232, 31), radius=3, outline=theme["accent2"] + (220,), width=2)
        d.rectangle((232, 14, 236, 25), fill=theme["accent2"] + (220,))
        for label, x, y in STAT_LABELS:
            d.text((x, y + 20), label, font=font(9, True), fill=theme["accent2"] + (255,))
        glow_line(d, (250, 126, w - 6, 126), theme["accent"])
        d.text((259, 128), "CHATTER", font=font(9, True), fill=theme["accent2"] + (255,))
    return img


def draw_sprite(theme: dict, action: str, frame: int, icon: bool = False) -> Image.Image:
    size = 46 if icon else 175
    scale = 2 if icon else 7
    # Keep the generated PNG dimensions that Loki expects, but render into a
    # larger scratch canvas first.  The old fixed y=38 origin clipped the
    # 27-unit leg/foot rectangles at both 175px and 46px output sizes.
    render_size = 92 if icon else 260
    origin_y = 19 if icon else 52
    img = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    cx = render_size // 2
    bob = int(math.sin(frame * math.pi / 2) * scale)
    skin = (245, 170, 178)
    shadow = (32, 16, 38)
    # neon halo
    for r, alpha in [(31, 35), (22, 60)]:
        d.ellipse((cx - r, 20 - r // 3, cx + r, 20 + r), outline=theme["accent2"] + (alpha,), width=max(1, scale // 2))
    # body/head using pixel-ish rectangles
    def rect(x1, y1, x2, y2, c):
        d.rectangle((cx + x1 * scale, origin_y + y1 * scale + bob, cx + x2 * scale, origin_y + y2 * scale + bob), fill=c)
    rect(-4, -2, 4, 5, skin)
    rect(-6, -4, 6, -1, theme["hair"])
    rect(-5, 5, 5, 15, theme["jacket"])
    rect(-6, 7, -4, 15, theme["trim"])
    rect(4, 7, 6, 15, theme["accent2"])
    rect(-4, 15, -1, 24, (25, 36, 80))
    rect(1, 15, 4, 24, (25, 36, 80))
    walk = [-2, 0, 2, 0][frame % 4]
    rect(-6 + walk, 24, -2 + walk, 27, theme["accent"])
    rect(2 - walk, 24, 6 - walk, 27, theme["accent2"])
    rect(-3, 0, 5, 1, shadow)
    # action prop
    prop_color = theme["accent"] if sum(action.encode("utf-8")) % 2 else theme["accent2"]
    if "Scanner" in action or action == "IDLE":
        d.arc((cx - 9 * scale, 26, cx + 9 * scale, 26 + 18 * scale), 200, 340, fill=prop_color + (220,), width=max(1, scale // 2))
    elif "Bruteforce" in action:
        rect(6, 10, 10, 13, prop_color)
    elif "Steal" in action or "Data" in action:
        rect(-10, 12, -6, 18, prop_color)
    else:
        rect(7, 5, 9, 18, prop_color)
    if render_size != size:
        img = img.resize((size, size), Image.Resampling.NEAREST)
    return img


def comments(theme_name: str) -> dict[str, list[str]]:
    return {
        "IDLE": [f"{theme_name} link idling.", "Neon rain on standby.", "Waiting for a hostile skyline."],
        "NetworkScanner": ["Sweeping alleys for live hosts.", "Pinging the grid glow by glow.", "Mapping the local sprawl."],
        "NmapVulnScanner": ["Running black-market vuln augury.", "ICE seams are being traced.", "Enumerating exposed chrome."],
        "SSHBruteforce": ["Trying SSH keys in the rain.", "Port 22 gets a neon knock."],
        "FTPBruteforce": ["FTP vault tumblers spinning.", "Old doors still leak light."],
        "TelnetBruteforce": ["Telnet ghosts answer too loudly.", "Vintage access, modern attitude."],
        "SMBBruteforce": ["SMB shares under streetlight.", "Checking corporate file alleys."],
        "SQLBruteforce": ["Querying the chrome oracle.", "Database locks meet neon picks."],
        "RDPBruteforce": ["Remote desktop visor online.", "RDP windows glow in the haze."],
        "StealFilesSSH": ["Siphoning files through SSH smoke.", "Secure copy, insecure choices."],
        "StealFilesFTP": ["Dragging loot from FTP shadows.", "Plaintext crates are moving."],
        "StealFilesSMB": ["SMB lockers are opening.", "Corporate folders hit the street."],
        "StealFilesTelnet": ["Telnet relics spill secrets.", "Old wire, fresh data."],
        "StealDataSQL": ["Dumping tables under neon glass.", "Records flow like blue rain."],
        "LogStandalone": ["Signal logged to the deck.", "Trace note pinned."],
        "LogStandalone2": ["Second log shard captured.", "More street telemetry saved."],
        "ZombifySSH": ["SSH shell recruited to the crew.", "Another chrome ghost joins."],
    }


def theme_json(key: str, t: dict) -> dict:
    text, accent, accent2 = list(t["text"]), list(t["accent"]), list(t["accent2"])
    return {
        "theme_name": t["name"], "web_title": f"Loki // {t['name']}",
        "text_color": text, "accent_color": accent,
        "animation_mode": "sequential", "image_display_delaymin": 0.65, "image_display_delaymax": 0.95,
        "comment_delaymin": 11, "comment_delaymax": 22, "moods": t["moods"],
        "skin_layout_landscape": {
            "stats": {"color": text, "align": "left", "target": {"x": 293, "y": 7}, "port": {"x": 368, "y": 7}, "vuln": {"x": 443, "y": 7}, "cred": {"x": 293, "y": 45}, "zombie": {"x": 368, "y": 45}, "data": {"x": 443, "y": 45}, "gold": {"x": 23, "y": 77, "color": accent}, "level": {"x": 44, "y": 197}, "networkkb": {"x": 246, "y": 77, "color": accent2}, "attacks": {"x": 246, "y": 197, "color": accent}},
            "character": {"x": 31, "y": 49, "w": 170, "h": 170, "align": "left"},
            "status": {"show_icon": True, "icon_x": 257, "icon_y": 79, "icon_size": 46, "color": text, "sub_color": accent, "text_x": 310, "text_y": 80, "sub_text_y": 105, "main_font_size": 22, "sub_font_size": 18, "max_text_w": 166, "align": "left"},
            "dialogue": {"x": 257, "y": 145, "max_w": 216, "color": text, "font_size": 20, "line_height": 20, "max_lines": 3, "align": "left"},
            "battery": {"x": 210, "y": 11, "font_size": 16, "color": text, "align": "center"},
        },
        "skin_layout_portrait": {
            "stats": {"color": text, "align": "left", "target": {"x": 38, "y": 49}, "port": {"x": 112, "y": 49}, "vuln": {"x": 186, "y": 49}, "cred": {"x": 38, "y": 87}, "zombie": {"x": 112, "y": 87}, "data": {"x": 186, "y": 87}, "gold": {"x": 23, "y": 361, "color": accent}, "level": {"x": 37, "y": 445}, "networkkb": {"x": 186, "y": 361, "color": accent2}, "attacks": {"x": 186, "y": 445, "color": accent}},
            "character": {"x": 38, "y": 327, "w": 145, "h": 145, "align": "left"},
            "status": {"show_icon": True, "icon_x": 6, "icon_y": 122, "icon_size": 46, "color": text, "sub_color": accent, "text_x": 60, "text_y": 123, "sub_text_y": 148, "main_font_size": 22, "sub_font_size": 18, "max_text_w": 158, "align": "left"},
            "dialogue": {"x": 8, "y": 184, "max_w": 206, "color": text, "font_size": 20, "line_height": 24, "max_lines": 4, "align": "left"},
            "battery": {"x": 198, "y": 10, "font_size": 16, "color": text, "align": "center"},
        },
        "menu_colors": {"bg": list(t["panel"]), "title": accent, "selected": accent2, "unselected": text, "on": accent2, "off": [150, 55, 75], "dim": [75, 85, 105], "warning": [255, 210, 76], "submenu": accent},
        "pause_menu_colors": {"bg": list(t["panel"]), "text": text, "accent": accent},
        "web": t["web"],
    }


def build(out: Path = DEFAULT_OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for key, t in THEMES.items():
        root = out / key
        if root.exists():
            shutil.rmtree(root)
        (root / "images" / "status").mkdir(parents=True)
        (root / "comments").mkdir()
        for name, size, portrait in [
            ("main_bg.png", (480, 222), False), ("main_bg_portrait.png", (222, 480), True),
            ("menu_bg.png", (480, 222), False), ("settings_bg.png", (480, 222), False),
            ("pause_bg.png", (480, 222), False), ("pause_bg_portrait.png", (222, 480), True),
        ]:
            background(t, size, portrait, t["name"] if "main" in name else name.replace("_bg.png", "")).save(root / "images" / name)
        (root / "theme.json").write_text(json.dumps(theme_json(key, t), indent=4) + "\n", encoding="utf-8")
        (root / "comments" / "comments.json").write_text(json.dumps(comments(t["name"]), indent=4) + "\n", encoding="utf-8")
        for action in ACTIONS:
            action_dir = root / "images" / "status" / action
            action_dir.mkdir(parents=True)
            draw_sprite(t, action, 0, icon=True).save(action_dir / f"{action}.png")
            for frame in range(1, 5):
                draw_sprite(t, action, frame, icon=False).save(action_dir / f"{action}{frame}.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Directory to receive generated Loki theme folders.",
    )
    args = parser.parse_args()
    build(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
