#!/usr/bin/env python3
"""
KTOx Payload – Cyberpunk Web Browser
=====================================
- Full text-based browser for 128x128 LCD
- Tabs, bookmarks, history, search engines
- On-screen keyboard for URL entry
- Dark red/black cyberpunk theme

Controls:
  UP/DOWN    – scroll page
  LEFT       – back to previous page
  RIGHT      – forward (if history exists)
  OK         – open selected link / confirm
  KEY1       – open URL entry (keyboard)
  KEY2       – open bookmarks menu
  KEY3       – exit

Dependencies: beautifulsoup4, requests, lxml
Install: pip install beautifulsoup4 requests lxml
"""

import os
import sys
import time
import threading
import urllib.parse
import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from payloads._darksec_keyboard import DarkSecKeyboard

# Hardware
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not found")
    sys.exit(1)

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128
try:
    font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
except:
    font_sm = font_bold = ImageFont.load_default()

# ----------------------------------------------------------------------
# Data directories
# ----------------------------------------------------------------------
DATA_DIR = "/root/KTOx/loot/Browser"
os.makedirs(DATA_DIR, exist_ok=True)
BOOKMARKS_FILE = os.path.join(DATA_DIR, "bookmarks.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Default settings
settings = {
    "search_engine": "duckduckgo",  # google, duckduckgo, bing
    "homepage": "https://lite.duckduckgo.com/lite",
}

# ----------------------------------------------------------------------
# Browser state
# ----------------------------------------------------------------------
class Tab:
    def __init__(self, url, title="New Tab"):
        self.url = url
        self.title = title
        self.page_text = []      # list of lines for display
        self.links = []          # list of (text, url)
        self.scroll = 0
        self.history_index = -1  # within session history
        self.session_history = []  # list of URLs in this tab

class Browser:
    def __init__(self):
        self.tabs = [Tab(settings["homepage"], "Home")]
        self.current_tab = 0
        self.loading = False
        self.status = "Ready"
        self.clipboard = ""
        self.load_settings()
        self.load_bookmarks()
        self.load_history()

    def load_settings(self):
        global settings
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                settings.update(saved)

    def save_settings(self):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f)

    def load_bookmarks(self):
        if os.path.exists(BOOKMARKS_FILE):
            with open(BOOKMARKS_FILE, 'r') as f:
                self.bookmarks = json.load(f)
        else:
            self.bookmarks = []

    def save_bookmarks(self):
        with open(BOOKMARKS_FILE, 'w') as f:
            json.dump(self.bookmarks, f)

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                self.history = json.load(f)
        else:
            self.history = []

    def save_history(self):
        # Keep last 100 entries
        self.history = self.history[-100:]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(self.history, f)

    def add_to_history(self, url, title):
        entry = {"url": url, "title": title, "time": datetime.now().isoformat()}
        self.history.append(entry)
        self.save_history()

    def add_bookmark(self, url, title):
        for b in self.bookmarks:
            if b["url"] == url:
                return
        self.bookmarks.append({"url": url, "title": title})
        self.save_bookmarks()

    def remove_bookmark(self, idx):
        if 0 <= idx < len(self.bookmarks):
            del self.bookmarks[idx]
            self.save_bookmarks()

    def fetch_page(self, url):
        self.loading = True
        self.status = f"Loading {url[:20]}..."
        self.update_display()
        try:
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            headers = {"User-Agent": "KTOxBrowser/2.0 (Cyberpunk)"}
            resp = requests.get(url, timeout=15, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Remove script/style tags
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            # Extract title
            title = soup.find('title')
            title_text = title.get_text(strip=True) if title else url[:30]
            # Extract text content
            text = soup.get_text(separator="\n")
            lines = []
            for line in text.splitlines():
                line = line.strip()
                if line:
                    lines.append(line)
            # Extract links
            links = []
            for a in soup.find_all('a', href=True):
                txt = a.get_text(strip=True)
                if txt and len(txt) > 1:
                    href = urllib.parse.urljoin(url, a['href'])
                    links.append((txt[:22], href))
            # Wrap text for 20 char width
            wrapped = []
            for line in lines:
                wrapped.extend([line[i:i+20] for i in range(0, len(line), 20)])
            # Limit to 500 lines
            wrapped = wrapped[:500]
            # Store in current tab
            tab = self.tabs[self.current_tab]
            tab.page_text = wrapped
            tab.links = links
            tab.title = title_text
            tab.url = url
            # Add to session history
            tab.session_history.append(url)
            tab.history_index = len(tab.session_history) - 1
            self.status = f"Loaded {title_text[:20]}"
            self.add_to_history(url, title_text)
        except Exception as e:
            tab = self.tabs[self.current_tab]
            tab.page_text = [f"Error: {str(e)[:30]}", "", "Press KEY1 to enter URL"]
            tab.links = []
            self.status = "Failed"
        finally:
            self.loading = False
            self.update_display()

    def go_back(self):
        tab = self.tabs[self.current_tab]
        if tab.history_index > 0:
            tab.history_index -= 1
            url = tab.session_history[tab.history_index]
            self.fetch_page(url)

    def go_forward(self):
        tab = self.tabs[self.current_tab]
        if tab.history_index < len(tab.session_history) - 1:
            tab.history_index += 1
            url = tab.session_history[tab.history_index]
            self.fetch_page(url)

    def new_tab(self, url=None):
        if url is None:
            url = settings["homepage"]
        new = Tab(url)
        self.tabs.append(new)
        self.current_tab = len(self.tabs) - 1
        self.fetch_page(url)

    def close_tab(self, idx):
        if len(self.tabs) <= 1:
            return
        del self.tabs[idx]
        if self.current_tab >= len(self.tabs):
            self.current_tab = len(self.tabs) - 1
        self.update_display()

    def switch_tab(self, delta):
        self.current_tab = (self.current_tab + delta) % len(self.tabs)
        self.update_display()

    def update_display(self):
        # Called to redraw LCD with current tab content
        draw_browser(self)

def osk_input(prompt="Enter URL:", initial=""):
    # Shared DarkSec keyboard (single source of truth for LCD input behavior)
    kb = DarkSecKeyboard(width=W, height=H, lcd=LCD, gpio_pins=PINS, gpio_module=GPIO)
    result = kb.run()
    if result is None:
        return None
    result = result.strip()
    return result or initial

# ----------------------------------------------------------------------
# Browser UI drawing
# ----------------------------------------------------------------------
def draw_browser(browser):
    tab = browser.tabs[browser.current_tab]
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    # Header: title + tab indicator
    d.rectangle((0,0,W,17), fill="#8B0000")
    title = f"[{browser.current_tab+1}/{len(browser.tabs)}] {tab.title[:15]}"
    d.text((4,3), title[:20], font=font_sm, fill=(231, 76, 60))
    # Status line
    d.text((4, H-24), browser.status[:23], font=font_sm, fill=(171, 178, 185))
    # Content
    lines = tab.page_text[tab.scroll:tab.scroll+6]
    y = 20
    for line in lines:
        d.text((4, y), line[:23], font=font_sm, fill=(171, 178, 185))
        y += 12
    # Links indicator
    if tab.links:
        d.text((4, H-12), f"🔗 {len(tab.links)} links", font=font_sm, fill=(231, 76, 60))
    else:
        d.text((4, H-12), "No links", font=font_sm, fill=(86, 101, 115))
    # Scrollbar
    total = max(1, len(tab.page_text))
    if total > 6:
        sb_h = H - 20 - 24
        bar_h = max(3, int(sb_h * 6 / total))
        bar_y = 18 + int(sb_h * tab.scroll / total)
        d.rectangle((W-3, 18, W-1, H-25), fill=(34, 0, 0))
        d.rectangle((W-3, bar_y, W-1, bar_y+bar_h), fill=(231, 76, 60))
    LCD.LCD_ShowImage(img, 0, 0)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

# ----------------------------------------------------------------------
# Menu screens (bookmarks, history, settings)
# ----------------------------------------------------------------------
def show_bookmarks_menu(browser):
    idx = 0
    while True:
        lines = ["📖 BOOKMARKS", ""]
        if browser.bookmarks:
            for i, bm in enumerate(browser.bookmarks):
                marker = ">" if i == idx else " "
                lines.append(f"{marker} {bm['title'][:16]}")
        else:
            lines.append("(empty)")
        lines.append("")
        lines.append("UP/DOWN OK=open K2=del K3=back")
        draw_screen(lines, title="BOOKMARKS")
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "UP":
            idx = (idx - 1) % max(1, len(browser.bookmarks))
        elif btn == "DOWN":
            idx = (idx + 1) % max(1, len(browser.bookmarks))
        elif btn == "OK" and browser.bookmarks:
            url = browser.bookmarks[idx]["url"]
            browser.fetch_page(url)
            break
        elif btn == "KEY2" and browser.bookmarks:
            browser.remove_bookmark(idx)
            if idx >= len(browser.bookmarks):
                idx = max(0, len(browser.bookmarks)-1)

def show_history_menu(browser):
    idx = 0
    while True:
        lines = ["📜 HISTORY", ""]
        history = browser.history[-20:]  # last 20 entries
        if history:
            for i, entry in enumerate(history):
                marker = ">" if i == idx else " "
                lines.append(f"{marker} {entry['title'][:16]}")
        else:
            lines.append("(empty)")
        lines.append("")
        lines.append("UP/DOWN OK=open K3=back")
        draw_screen(lines, title="HISTORY")
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "UP":
            idx = (idx - 1) % max(1, len(history))
        elif btn == "DOWN":
            idx = (idx + 1) % max(1, len(history))
        elif btn == "OK" and history:
            url = history[idx]["url"]
            browser.fetch_page(url)
            break

def show_settings_menu(browser):
    engines = ["google", "duckduckgo", "bing"]
    engine_names = {"google": "Google", "duckduckgo": "DuckDuckGo", "bing": "Bing"}
    engine_idx = engines.index(settings["search_engine"])
    while True:
        lines = ["⚙️ SETTINGS", "", f"Search: {engine_names[engines[engine_idx]]}", "", "UP/DOWN change", "OK save", "K3 back"]
        draw_screen(lines, title="SETTINGS")
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "UP":
            engine_idx = (engine_idx - 1) % len(engines)
        elif btn == "DOWN":
            engine_idx = (engine_idx + 1) % len(engines)
        elif btn == "OK":
            settings["search_engine"] = engines[engine_idx]
            browser.save_settings()
            draw_screen(["Settings saved"], title="SETTINGS")
            time.sleep(1)
            break

def draw_screen(lines, title="BROWSER", title_color="#8B0000"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0,0,W,17), fill=title_color)
    d.text((4,3), title[:20], font=font_sm, fill=(231, 76, 60))
    y = 20
    for line in lines[:7]:
        d.text((4,y), line[:23], font=font_sm, fill=(171, 178, 185))
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK KEY1/2/3", font=font_sm, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    browser = Browser()
    # Start with homepage
    browser.fetch_page(settings["homepage"])
    held = {}
    while True:
        browser.update_display()
        btn = wait_btn(0.5)
        if btn == "KEY3":
            break
        elif btn == "UP":
            tab = browser.tabs[browser.current_tab]
            if tab.scroll > 0:
                tab.scroll -= 1
        elif btn == "DOWN":
            tab = browser.tabs[browser.current_tab]
            max_scroll = max(0, len(tab.page_text) - 6)
            if tab.scroll < max_scroll:
                tab.scroll += 1
        elif btn == "LEFT":
            browser.go_back()
        elif btn == "RIGHT":
            browser.go_forward()
        elif btn == "KEY1":
            url = osk_input("Enter URL:", "")
            if url:
                browser.fetch_page(url)
        elif btn == "KEY2":
            # Open menu: choose Bookmarks, History, Settings, New Tab
            menu_idx = 0
            menu_items = ["Bookmarks", "History", "Settings", "New Tab", "Close Tab"]
            while True:
                lines = ["📌 MENU", ""]
                for i, item in enumerate(menu_items):
                    marker = ">" if i == menu_idx else " "
                    lines.append(f"{marker} {item}")
                draw_screen(lines, title="BROWSER MENU")
                btn2 = wait_btn(0.5)
                if btn2 == "KEY3":
                    break
                elif btn2 == "UP":
                    menu_idx = (menu_idx - 1) % len(menu_items)
                elif btn2 == "DOWN":
                    menu_idx = (menu_idx + 1) % len(menu_items)
                elif btn2 == "OK":
                    if menu_idx == 0:
                        show_bookmarks_menu(browser)
                    elif menu_idx == 1:
                        show_history_menu(browser)
                    elif menu_idx == 2:
                        show_settings_menu(browser)
                    elif menu_idx == 3:
                        browser.new_tab()
                    elif menu_idx == 4:
                        browser.close_tab(browser.current_tab)
                    break
        elif btn == "OK":
            # Open the first link on the page (or selected link? For simplicity, open first)
            tab = browser.tabs[browser.current_tab]
            if tab.links:
                _, url = tab.links[0]
                browser.fetch_page(url)
        time.sleep(0.05)

    GPIO.cleanup()
    LCD.LCD_Clear()

if __name__ == "__main__":
    # Install dependencies if missing
    try:
        import requests, bs4
    except ImportError:
        os.system("pip install beautifulsoup4 requests lxml")
    main()
