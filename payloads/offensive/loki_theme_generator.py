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

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "payloads" / "offensive" / "loki_themes"
ASSETS_DIR = ROOT / "assets"

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
    "NucleiScanner",
    "SearchSploitEnricher",
    "TestSSLScanner",
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
        "name": "Edgerunners",
        "subtitle": "NIGHT CITY OS // REDLINE BOOST",
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


SPRITE_CELL_SIZE = (32, 44)
SPRITE_SHEET_GRID = (3, 4)
SPRITE_ASSET_DIR = ASSETS_DIR / "sprites"
BACKGROUND_ASSET_DIRS = [SPRITE_ASSET_DIR / "Backgrounds", SPRITE_ASSET_DIR / "Background"]
SPRITE_ACTION_ALIASES = {
    "LogStandalone": "IDLE",
    "LogStandalone2": "NetworkScanner",
    "ZombifySSH": "SSHBruteforce",
    # Loki-recon scanner modules that do not have separate uploaded sprite files.
    "NucleiScanner": "NmapVulnScanner",
    "SearchSploitEnricher": "NmapVulnScanner",
    "TestSSLScanner": "NmapVulnScanner",
}

# Normal builds load the real artist-provided per-action PNGs from
# assets/sprites and fail if any required asset is missing. The source-drawn
# profiles below are kept only for legacy reference helpers, not as installer
# fallback output.
SPRITE_PROFILES = {
    "neon_runner": {
        "skin": (245, 168, 184, 255),
        "hair": (32, 237, 220, 255),
        "hair_shadow": (0, 142, 151, 255),
        "jacket": (19, 24, 44, 255),
        "trim": (42, 245, 210, 255),
        "pants": (31, 36, 80, 255),
        "shoe": (72, 122, 245, 255),
        "accent": (255, 58, 168, 255),
        "outline": (16, 12, 31, 255),
        "highlight": (142, 255, 246, 255),
        "bag": (47, 103, 238, 255),
        "style": "twintail",
    },
    "chrome_mantis": {
        "skin": (238, 170, 176, 255),
        "hair": (41, 26, 58, 255),
        "hair_shadow": (92, 48, 92, 255),
        "jacket": (244, 221, 92, 255),
        "trim": (84, 255, 142, 255),
        "pants": (25, 36, 76, 255),
        "shoe": (115, 207, 255, 255),
        "accent": (255, 245, 154, 255),
        "outline": (16, 12, 25, 255),
        "highlight": (255, 248, 179, 255),
        "bag": (39, 55, 116, 255),
        "style": "spike",
    },
    "edge_fury": {
        "skin": (245, 164, 169, 255),
        "hair": (255, 219, 94, 255),
        "hair_shadow": (221, 139, 90, 255),
        "jacket": (37, 28, 64, 255),
        "trim": (255, 69, 83, 255),
        "pants": (30, 42, 88, 255),
        "shoe": (76, 116, 194, 255),
        "accent": (255, 185, 75, 255),
        "outline": (18, 12, 25, 255),
        "highlight": (255, 239, 139, 255),
        "bag": (92, 113, 173, 255),
        "style": "swept",
    },
    "icewire_ghost": {
        "skin": (247, 176, 193, 255),
        "hair": (222, 242, 255, 255),
        "hair_shadow": (123, 185, 242, 255),
        "jacket": (24, 28, 58, 255),
        "trim": (96, 143, 255, 255),
        "pants": (36, 41, 84, 255),
        "shoe": (80, 126, 255, 255),
        "accent": (255, 123, 176, 255),
        "outline": (14, 16, 35, 255),
        "highlight": (245, 255, 255, 255),
        "bag": (74, 126, 255, 255),
        "style": "icebob",
    },
}

ACTION_ROWS = {
    "IDLE": 0,
    "NetworkScanner": 0,
    "NmapVulnScanner": 0,
    "SSHBruteforce": 1,
    "FTPBruteforce": 1,
    "TelnetBruteforce": 1,
    "SMBBruteforce": 1,
    "SQLBruteforce": 2,
    "RDPBruteforce": 2,
    "StealFilesSSH": 2,
    "StealFilesFTP": 2,
    "StealFilesSMB": 2,
    "StealFilesTelnet": 2,
    "StealDataSQL": 2,
    "LogStandalone": 3,
    "LogStandalone2": 3,
    "ZombifySSH": 3,
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


def panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], theme: dict, label: str = "", accent: tuple[int, int, int] | None = None) -> None:
    accent = accent or theme["accent2"]
    x1, y1, x2, y2 = box
    draw.rectangle(box, fill=theme["bg"] + (245,), outline=accent + (245,), width=1)
    draw.rectangle((x1 + 1, y1 + 1, x2 - 1, min(y1 + 10, y2)), fill=(8, 9, 16, 235))
    if label:
        draw.rectangle((x1 + 2, y1 + 2, x1 + 42, y1 + 9), fill=theme["accent"] + (255,))
        draw.text((x1 + 4, y1 + 1), label.upper()[:9], font=font(6, True), fill=(5, 5, 12, 255))


def stat_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], theme: dict, label: str, value: str, accent: tuple[int, int, int]) -> None:
    panel(draw, box, theme, label, accent)
    x1, y1, _, _ = box
    draw.text((x1 + 4, y1 + 13), value, font=font(16, True), fill=accent + (255,))
    draw.text((x1 + 54, y1 + 2), "o", font=font(6, True), fill=accent + (255,))


def draw_header(draw: ImageDraw.ImageDraw, size: tuple[int, int], theme: dict, title: str, portrait: bool) -> None:
    w, _ = size
    draw.line((0, 0, w, 0), fill=theme["accent"] + (255,), width=2)
    draw.line((0, 16, w, 16), fill=theme["accent"] + (255,), width=1)
    draw.polygon([(0, 0), (14, 0), (0, 14)], fill=theme["accent"] + (255,))
    draw.text((20 if portrait else 26, 4), title.upper(), font=font(10, True), fill=theme["accent"] + (255,))
    if not portrait:
        draw.text((238, 4), "// NIGHT CITY OS", font=font(8, True), fill=theme["accent2"] + (255,))
        draw.text((400, 4), "v2.077", font=font(8, True), fill=theme["accent"] + (255,))
    draw.rectangle((w - 45, 3, w - 7, 14), outline=theme["text"] + (120,), fill=(15, 18, 24, 230))
    draw.text((w - 36, 4), "87%", font=font(8, True), fill=theme["accent"] + (255,))


def draw_footer(draw: ImageDraw.ImageDraw, size: tuple[int, int], theme: dict, portrait: bool) -> None:
    w, h = size
    y = h - 17
    draw.line((0, y, w, y), fill=theme["accent"] + (255,), width=1)
    labels = ["EDDIES", "$ 9999", "NET KB", "> 4521", "STREET", "* 12", "RUNS", "^ 143"]
    x = 6
    for i, label in enumerate(labels):
        color = theme["accent"] if i % 2 == 0 else theme["accent2"]
        draw.text((x, y + 4), label, font=font(7, True), fill=color + (255,))
        x += 52 if not portrait else 44
        if portrait and x > w - 30:
            break


def background(theme: dict, size: tuple[int, int], portrait: bool = False, title: str = "") -> Image.Image:
    img = Image.new("RGBA", size, theme["bg"] + (255,))
    d = ImageDraw.Draw(img, "RGBA")
    w, h = size

    # dense terminal scanlines and subtle grid, matching the Loki/Edgerunners UI mockups
    for y in range(0, h, 2):
        d.line((0, y, w, y), fill=(0, 0, 0, 62))
    for x in range(0, w, 12):
        d.line((x, 18, x, h - 18), fill=theme["grid"] + (18,))
    for y in range(18, h - 18, 12):
        d.line((0, y, w, y), fill=theme["grid"] + (16,))

    draw_header(d, size, theme, title, portrait)
    draw_footer(d, size, theme, portrait)

    if portrait:
        stat_boxes = [
            ((5, 40, 78, 76), "TARGET", "192", theme["accent2"]),
            ((82, 40, 150, 76), "PORT", "22", theme["accent"]),
            ((154, 40, 217, 76), "VULN", "7", theme["accent"]),
            ((5, 78, 78, 112), "CRED", "13", theme["accent"]),
            ((82, 78, 150, 112), "ZOMB", "4", theme["accent"]),
            ((154, 78, 217, 112), "DATA", "27", theme["accent2"]),
        ]
        for box, label, value, accent in stat_boxes:
            stat_box(d, box, theme, label, value, accent)
        panel(d, (4, 118, w - 5, 306), theme, "PROCESS", theme["accent"])
        d.text((15, 139), "IDLE", font=font(18, True), fill=theme["accent"] + (255,))
        d.text((58, 164), "STANDING BY", font=font(13, True), fill=theme["accent2"] + (255,))
        d.text((9, 320), "ID:DM", font=font(7, True), fill=(0, 0, 10, 255))
        panel(d, (36, 338, 185, h - 30), theme, "ID:DM", theme["accent"])
        d.line((0, h - 27, w, h - 27), fill=theme["accent2"] + (220,))
        d.text((8, h - 24), "// EDGERUNNER ACTIVE", font=font(7, True), fill=theme["accent2"] + (255,))
    else:
        panel(d, (23, 27, 200, 194), theme, "ID:DM", theme["accent"])
        stat_boxes = [
            ((209, 27, 276, 62), "TARGET", "192", theme["accent2"]),
            ((279, 27, 346, 62), "PORT", "22", theme["accent"]),
            ((349, 27, 416, 62), "VULN", "7", theme["accent"]),
            ((209, 64, 276, 100), "CRED", "13", theme["accent"]),
            ((279, 64, 346, 100), "ZOMB", "4", theme["accent"]),
            ((349, 64, 416, 100), "DATA", "27", theme["accent2"]),
        ]
        for box, label, value, accent in stat_boxes:
            stat_box(d, box, theme, label, value, accent)
        panel(d, (209, 108, w - 7, h - 28), theme, "PROCESS", theme["accent"])
        d.text((220, 124), "SSH BRUTEFORCE", font=font(11, True), fill=theme["accent"] + (255,))
        d.text((220, 139), "192.168.1.42:22", font=font(9, True), fill=theme["accent2"] + (255,))
        d.text((216, h - 43), "> Hammering port 22.", font=font(9), fill=theme["text"] + (255,))
        d.text((216, h - 31), "> Corp ICE is noisy.", font=font(9), fill=theme["text"] + (255,))
    return img


def px(draw: ImageDraw.ImageDraw, x: int, y: int, color: tuple[int, int, int, int], scale: int = 1) -> None:
    draw.rectangle((x * scale, y * scale, (x + 1) * scale - 1, (y + 1) * scale - 1), fill=color)


def block(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, color: tuple[int, int, int, int], scale: int = 1) -> None:
    draw.rectangle((x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1), fill=color)


def real_sprite_path(action: str, frame: int, icon: bool = False) -> Path | None:
    """Return the uploaded sprite PNG for an action/frame if available."""
    stem = SPRITE_ACTION_ALIASES.get(action, action)
    suffix = "" if icon else str(max(1, min(frame, 4)))
    path = SPRITE_ASSET_DIR / f"{stem}{suffix}.png"
    if path.exists():
        return path
    if not icon:
        icon_path = SPRITE_ASSET_DIR / f"{stem}.png"
        if icon_path.exists():
            return icon_path
    return None


def load_real_sprite(action: str, frame: int, icon: bool = False) -> Image.Image | None:
    """Load an artist-provided action sprite without redrawing or altering it."""
    path = real_sprite_path(action, frame, icon)
    if path is None:
        return None
    with Image.open(path) as source:
        return source.convert("RGBA")


def require_real_sprite(action: str, frame: int, icon: bool = False) -> Image.Image:
    """Load a real uploaded sprite and fail instead of silently drawing a fake one."""
    sprite = load_real_sprite(action, frame, icon)
    if sprite is None:
        stem = SPRITE_ACTION_ALIASES.get(action, action)
        suffix = "" if icon else str(frame)
        raise FileNotFoundError(
            f"Missing required Loki sprite asset: {SPRITE_ASSET_DIR / f'{stem}{suffix}.png'}"
        )
    return sprite


def background_asset_path(name: str) -> Path | None:
    """Return an uploaded background PNG path if present."""
    for directory in BACKGROUND_ASSET_DIRS:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def load_background_asset(name: str, size: tuple[int, int]) -> Image.Image | None:
    """Load and normalize an uploaded background PNG."""
    path = background_asset_path(name)
    if path is None:
        return None
    with Image.open(path) as source:
        bg = source.convert("RGB")
    if bg.size != size:
        bg = bg.resize(size, Image.Resampling.BICUBIC)
    return bg


def draw_reference_sprite(profile: dict, direction: int, pose: int) -> Image.Image:
    """Draw one generated frame in the same 3x4 shape as the supplied sheets."""
    w, h = SPRITE_CELL_SIZE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    skin = profile["skin"]
    hair = profile["hair"]
    hair_shadow = profile["hair_shadow"]
    jacket = profile["jacket"]
    trim = profile["trim"]
    pants = profile["pants"]
    shoe = profile["shoe"]
    accent = profile["accent"]
    outline = profile["outline"]
    highlight = profile["highlight"]
    bag = profile["bag"]
    style = profile["style"]
    center = 15
    walk = [-2, 0, 2][pose]
    arm = [1, 0, -1][pose]

    def b(x: int, y: int, bw: int, bh: int, color: tuple[int, int, int, int]) -> None:
        # one-pixel dark keyline makes generated sprites read like imported sheets
        block(d, x - 1, y - 1, bw + 2, bh + 2, outline)
        block(d, x, y, bw, bh, color)

    def pnt(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        px(d, x, y, outline)
        px(d, x, y, color)

    # contact shadow and little trailing satchel/gear block visible in the samples
    block(d, 8, 39, 15, 2, (0, 0, 0, 150))
    facing_back = direction == 3
    facing_left = direction == 1
    facing_right = direction == 2

    if facing_left or facing_right:
        side = -1 if facing_left else 1
        # legs and shoes
        b(center - 2 + walk, 28, 3, 8, pants)
        b(center + 1 - walk, 27, 3, 9, pants)
        b(center - 3 + walk, 36, 5, 2, shoe)
        b(center + 1 - walk, 36, 5, 2, highlight if style == "icebob" else shoe)
        # torso, coat stripe and rear gear
        b(center - 4, 18, 8, 10, jacket)
        b(center - 4, 19, 2, 9, trim)
        b(center + 2, 19, 2, 9, accent)
        b(center - side * 8, 23, 4, 6, bag)
        # arms
        b(center + side * 4, 20 + arm, 2, 8, skin)
        b(center - side * 5, 21 - arm, 2, 7, jacket)
        # face and facial shade
        b(center - 3, 11, 7, 7, skin)
        block(d, center + side * 1, 12, 3, 6, (242, 129, 160, 255))
        px(d, center + side * 3, 14, (16, 10, 24, 255))
        block(d, center - 4, 17, 5, 1, (255, 205, 210, 255))
        # hair mass by style
        if style == "twintail":
            b(center - 6, 8, 11, 4, hair)
            b(center - 6, 12, 3, 9, hair_shadow)
            b(center - side * 8, 9, 4, 15, hair)
            b(center - side * 8, 22, 3, 4, hair_shadow)
            block(d, center - 3, 7, 7, 2, highlight)
        elif style == "spike":
            b(center - 6, 9, 10, 4, hair)
            b(center - 2, 6, 7, 3, hair_shadow)
            b(center + 1, 3, 4, 4, hair_shadow)
            b(center + 4, 7, 3, 5, hair)
            block(d, center - 3, 10, 5, 1, highlight)
        elif style == "swept":
            b(center - 6, 8, 11, 4, hair)
            b(center - 2, 6, 10, 3, hair)
            b(center + side * 4, 9, 6, 6, hair_shadow)
            block(d, center - 4, 8, 6, 1, highlight)
        else:
            b(center - 7, 8, 10, 5, hair)
            b(center - side * 6, 7, 5, 8, hair_shadow)
            b(center - side * 8, 11, 4, 10, hair)
            block(d, center - 4, 8, 6, 1, highlight)
        return img

    # front/back rows
    b(center - 5 + walk, 28, 4, 8, pants)
    b(center + 1 - walk, 28, 4, 8, pants)
    b(center - 6 + walk, 36, 6, 2, shoe)
    b(center + 1 - walk, 36, 6, 2, highlight if style == "icebob" else shoe)
    b(center - 7, 18, 14, 10, jacket)
    b(center - 7, 19, 2, 9, trim)
    b(center + 5, 19, 2, 9, accent)
    b(center - 9, 20 + arm, 2, 8, skin if not facing_back else jacket)
    b(center + 7, 20 - arm, 2, 8, skin if not facing_back else jacket)
    if facing_back:
        b(center - 5, 11, 10, 7, hair_shadow)
        b(center - 5, 15, 10, 3, hair)
        b(center - 5, 21, 10, 7, bag)
        block(d, center - 4, 22, 8, 2, accent)
    else:
        b(center - 4, 11, 8, 7, skin)
        block(d, center - 3, 12, 6, 2, (255, 196, 207, 255))
        px(d, center - 2, 14, (18, 12, 28, 255))
        px(d, center + 2, 14, (18, 12, 28, 255))
        block(d, center - 2, 17, 4, 1, (210, 79, 118, 255))
    if style == "twintail":
        b(center - 7, 8, 14, 5, hair)
        b(center - 11, 10, 4, 14, hair)
        b(center + 7, 10, 4, 14, hair)
        b(center - 12, 23, 3, 4, hair_shadow)
        b(center + 9, 23, 3, 4, hair_shadow)
        block(d, center - 3, 7, 7, 2, highlight)
    elif style == "spike":
        b(center - 7, 9, 13, 4, hair)
        b(center - 2, 6, 7, 3, hair_shadow)
        b(center + 1, 3, 4, 4, hair_shadow)
        b(center + 5, 7, 3, 5, hair_shadow)
        block(d, center - 4, 10, 7, 1, highlight)
    elif style == "swept":
        b(center - 8, 8, 15, 5, hair)
        b(center - 2, 6, 11, 3, hair)
        b(center + 5, 10, 5, 7, hair_shadow)
        block(d, center - 5, 8, 7, 1, highlight)
    else:
        b(center - 8, 8, 13, 5, hair)
        b(center - 10, 9, 5, 11, hair_shadow)
        b(center - 10, 13, 4, 8, hair)
        block(d, center - 5, 8, 8, 1, highlight)
    return img


def sprite_frame(theme_key: str, action: str, frame: int) -> Image.Image:
    profile = SPRITE_PROFILES[theme_key]
    col = (frame - 1) % SPRITE_SHEET_GRID[0]
    row = ACTION_ROWS.get(action, 0)
    return draw_reference_sprite(profile, row, col)


def draw_sprite(theme_key: str, theme: dict, action: str, frame: int, icon: bool = False) -> Image.Image:
    size = 46 if icon else 175
    real_sprite = require_real_sprite(action, frame, icon)
    if real_sprite.size == (size, size):
        return real_sprite

    # This branch is only for malformed/mismatched assets. Correct uploaded
    # 46x46 icons and 175x175 frames are copied byte-for-byte by build().
    real_sprite.thumbnail((size, size), Image.Resampling.NEAREST)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.alpha_composite(real_sprite, ((size - real_sprite.width) // 2, size - real_sprite.height))
    return img


COMMENT_BANKS = {
    "neon_runner": {
        "IDLE": ["Pulse at zero. Neon still breathing.", "Deck is warm; alley is louder.", "Chrome boots dry under pink rain."],
        "NetworkScanner": ["Cyan pings skip across rooftops.", "Mapping signs, vents, and bad ideas.", "Every AP leaves a little glow."],
        "NmapVulnScanner": ["Port glass cracks under neon.", "Service banners spill street rumors.", "Vuln scan rides the rail line."],
        "SSHBruteforce": ["Pink keys tap on port 22.", "Trying creds between thunderclaps."],
        "FTPBruteforce": ["Old FTP doors hum in cyan.", "Plaintext crates rattle open."],
        "TelnetBruteforce": ["Telnet ghosts answer the payphone.", "Legacy wire, fresh bruise."],
        "SMBBruteforce": ["Share alleys get a neon sweep.", "SMB lockers blink unlocked."],
        "SQLBruteforce": ["Query lights chase wet asphalt.", "Database locks meet glow picks."],
        "RDPBruteforce": ["Remote windows flare hot pink.", "RDP glass gets fingerprinted."],
        "StealFilesSSH": ["SCP smoke curls into the bag.", "Files ride a cyan backstreet."],
        "StealFilesFTP": ["FTP loot dragged under signage.", "Anonymous crates move fast."],
        "StealFilesSMB": ["Corporate folders hit the street.", "SMB cabinets cough up secrets."],
        "StealFilesTelnet": ["Telnet relics leak vintage gold.", "Old shells spill new data."],
        "StealDataSQL": ["Tables pour like neon rain.", "Rows copied before the light changes."],
        "LogStandalone": ["Trace note pinned to the rail.", "Signal shard logged in pink."],
        "LogStandalone2": ["Second shard hums in cyan.", "Telemetry stacked and tagged."],
        "ZombifySSH": ["SSH ghost joins the sprint.", "Another shell follows the runner."],
        "NucleiScanner": ["Template sparks trace every weak seam.", "Nuclei signatures bloom in cyan."],
        "SearchSploitEnricher": ["Exploit notes pinned under neon.", "Public CVEs get street names."],
        "TestSSLScanner": ["TLS glass hums under pink probes.", "Cipher suites leak rainbow static."],
    },
    "chrome_mantis": {
        "IDLE": ["Blades folded. Optics awake.", "Quiet chrome, loud intent.", "Mantis waits behind black glass."],
        "NetworkScanner": ["Green feelers comb the subnet.", "Hosts twitch under acid light.", "Chrome antennae taste the LAN."],
        "NmapVulnScanner": ["ICE seams marked for cutting.", "Service armor gets measured.", "Green razors read every port."],
        "SSHBruteforce": ["Port 22 under mantis taps.", "Keys click like folded knives."],
        "FTPBruteforce": ["FTP husk split at the hinge.", "Old vault, acid prybar."],
        "TelnetBruteforce": ["Telnet shell chirps in the dark.", "Legacy prey moves too slow."],
        "SMBBruteforce": ["SMB joints exposed and tagged.", "Share carapace flexes open."],
        "SQLBruteforce": ["Green queries cut the lock.", "Database chitin starts to split."],
        "RDPBruteforce": ["RDP visor reflects the blade.", "Remote glass under claw pressure."],
        "StealFilesSSH": ["SSH files lifted with pincers.", "Secure copy, surgical exit."],
        "StealFilesFTP": ["FTP meat pulled from old bone.", "Plaintext carrion bagged."],
        "StealFilesSMB": ["SMB folders clipped clean.", "Corporate molting collected."],
        "StealFilesTelnet": ["Telnet fossils crack open.", "Ancient wire gives up marrow."],
        "StealDataSQL": ["Tables diced into green strips.", "Rows carved out quiet."],
        "LogStandalone": ["Cut mark logged.", "Chrome scratch archived."],
        "LogStandalone2": ["Second incision recorded.", "Telemetry folded into the case."],
        "ZombifySSH": ["SSH husk stands back up.", "Another chrome limb obeys."],
        "NucleiScanner": ["Templates unfold like green blades.", "Nuclei cuts across exposed seams."],
        "SearchSploitEnricher": ["Exploit trails etched into chrome.", "CVE scent locked and tagged."],
        "TestSSLScanner": ["TLS armor gets a mantis tap.", "Cipher plating flexes under acid light."],
    },
    "edge_fury": {
        "IDLE": ["Waiting on a gig, choom.", "Net's quiet. Too quiet.", "Stay frosty."],
        "NetworkScanner": ["Night City blocks lighting up.", "Pinging every rooftop in range.", "Scanner rides the street grid."],
        "NmapVulnScanner": ["ICE cracks under yellow heat.", "Ports squeal like bad chrome.", "Vulns tagged for the crew."],
        "SSHBruteforce": ["Hammering port 22, choom.", "Some corpo used 'password123'."],
        "FTPBruteforce": ["FTP is preem ancient tech.", "Old vaults still pay eddies."],
        "TelnetBruteforce": ["Telnet? That's museum-grade dumb.", "Vintage wire gets flatlined."],
        "SMBBruteforce": ["SMB shares smell like payroll.", "Crew is checking every locker."],
        "SQLBruteforce": ["Database sings under pressure.", "Query the corpo oracle."],
        "RDPBruteforce": ["RDP window, back-alley entry.", "Remote desktop gets zeroed."],
        "StealFilesSSH": ["SCP bag filling with receipts.", "Files delta out through smoke."],
        "StealFilesFTP": ["FTP crates loaded for the run.", "Plaintext loot, easy eddies."],
        "StealFilesSMB": ["SMB folders jacked clean.", "Corp docs ride with us now."],
        "StealFilesTelnet": ["Telnet relic spits secrets.", "Old access, new payday."],
        "StealDataSQL": ["Tables dump like bad memories.", "Rows are eddies in disguise."],
        "LogStandalone": ["Gig note saved.", "Street telemetry pocketed."],
        "LogStandalone2": ["Second shard clipped.", "More receipts for the fixer."],
        "ZombifySSH": ["SSH shell joins the crew.", "Another chrome ghost on payroll."],
        "NucleiScanner": ["Nuclei templates hit like chrome sparks.", "Weak spots light up for the fixer."],
        "SearchSploitEnricher": ["Exploit intel sells for eddies.", "CVE receipts clipped to the gig."],
        "TestSSLScanner": ["TLS gets read under redline glare.", "Cipher stack sweats in Night City."],
    },
    "icewire_ghost": {
        "IDLE": ["White noise. Blue breath.", "Ghost idle beneath black ICE.", "No footprints in the frost."],
        "NetworkScanner": ["Cold pings cross the dark water.", "Subnet frost blooms blue.", "Every host exhales vapor."],
        "NmapVulnScanner": ["ICE fractures under white light.", "Ports freeze, then confess.", "Scanner traces blue fault lines."],
        "SSHBruteforce": ["Port 22 gets frostbitten.", "Keys turn slowly in the cold."],
        "FTPBruteforce": ["FTP archive thaw in progress.", "Old doors crack under ice."],
        "TelnetBruteforce": ["Telnet signal found under snow.", "Legacy line goes brittle."],
        "SMBBruteforce": ["SMB shares iced and indexed.", "File lockers frost over."],
        "SQLBruteforce": ["Blue queries drift through glass.", "Database lock chills open."],
        "RDPBruteforce": ["RDP visor fogs from inside.", "Remote pane turns blue."],
        "StealFilesSSH": ["SSH files vanish in snowfall.", "Secure copy leaves no tracks."],
        "StealFilesFTP": ["FTP crates slide across ice.", "Plaintext frozen for pickup."],
        "StealFilesSMB": ["SMB cabinets open silently.", "Corporate snowpack collected."],
        "StealFilesTelnet": ["Telnet fossils thaw and spill.", "Old wire cracks white."],
        "StealDataSQL": ["Tables drift out under frost.", "Rows crystallize in the cache."],
        "LogStandalone": ["Cold trace archived.", "Blue shard logged."],
        "LogStandalone2": ["Second frost mark saved.", "Telemetry disappears into white."],
        "ZombifySSH": ["SSH ghost rises quiet.", "Another frozen shell obeys."],
        "NucleiScanner": ["Nuclei frost maps every fracture.", "Templates drift through blue fault lines."],
        "SearchSploitEnricher": ["Exploit records freeze into focus.", "CVE ghosts line up in the snow."],
        "TestSSLScanner": ["TLS panes fog under white ICE.", "Cipher frost exposes the weak links."],
    },
}


def copy_sprite_asset(action: str, frame: int, destination: Path, icon: bool = False) -> None:
    """Copy the uploaded sprite into a Loki theme, preserving bytes when sized correctly."""
    path = real_sprite_path(action, frame, icon)
    if path is None:
        stem = SPRITE_ACTION_ALIASES.get(action, action)
        suffix = "" if icon else str(frame)
        raise FileNotFoundError(
            f"Missing required Loki sprite asset: {SPRITE_ASSET_DIR / f'{stem}{suffix}.png'}"
        )
    expected = (46, 46) if icon else (175, 175)
    with Image.open(path) as source:
        if source.size == expected:
            shutil.copyfile(path, destination)
            return
    draw_sprite("neon_runner", THEMES["neon_runner"], action, frame, icon=icon).save(destination)


def copy_background_asset(name: str, destination: Path, size: tuple[int, int]) -> bool:
    """Copy an uploaded background into a Loki theme when available."""
    path = background_asset_path(name)
    if path is None:
        return False
    with Image.open(path) as source:
        if source.size == size:
            shutil.copyfile(path, destination)
            return True
    bg = load_background_asset(name, size)
    if bg is None:
        return False
    bg.save(destination)
    return True


def comments(theme_key: str) -> dict[str, list[str]]:
    return COMMENT_BANKS[theme_key]


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
            destination = root / "images" / name
            if not copy_background_asset(name, destination, size):
                bg = background(t, size, portrait, t["name"] if "main" in name else name.replace("_bg.png", ""))
                bg.save(destination)
        (root / "theme.json").write_text(json.dumps(theme_json(key, t), indent=4) + "\n", encoding="utf-8")
        (root / "comments" / "comments.json").write_text(json.dumps(comments(key), indent=4) + "\n", encoding="utf-8")
        for action in ACTIONS:
            action_dir = root / "images" / "status" / action
            action_dir.mkdir(parents=True)
            copy_sprite_asset(action, 0, action_dir / f"{action}.png", icon=True)
            for frame in range(1, 5):
                copy_sprite_asset(action, frame, action_dir / f"{action}{frame}.png", icon=False)


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
