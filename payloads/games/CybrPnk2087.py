#!/usr/bin/env python3
"""
KTOx Payload – CybrPnk2087
author: wickednull
=======================================================================
Massive RPG with modular story (Acts 1-10), turn‑based combat, XP, leveling,
quickhacks, reputation events, and all original side gigs, crew, shop, save/load.

Controls: 
  UP/DOWN = scroll / move cursor
  OK = select / next page
  KEY1 = inventory
  KEY2 = return to Afterlife hub
  KEY3 = exit
"""

import os
import sys
import time
import random
import textwrap
import json

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Paths & Hardware
# ----------------------------------------------------------------------
LOOT_DIR = "/root/KTOx/loot"
os.makedirs(LOOT_DIR, exist_ok=True)
SAVE_FILE = os.path.join(LOOT_DIR, "cyberpunk_save.json")

PINS = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26,
    "OK": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16,
}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()
FONT = font(9)
FONT_BOLD = font(10)

# Global image/draw for optimisation
IMAGE = Image.new("RGB", (W, H), (10, 0, 0))
DRAW = ImageDraw.Draw(IMAGE)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def wait_for_release(btn_name):
    pin = PINS[btn_name]
    while GPIO.input(pin) == 0:
        time.sleep(0.02)

# ==============================
# UI Helpers (optimised)
# ==============================
def wrap_text(text, width=18):
    return textwrap.wrap(text, width=width)

def display_text(lines, title=None):
    global IMAGE, DRAW
    DRAW.rectangle((0, 0, W, H), fill=(10, 0, 0))
    y = 2
    if title:
        DRAW.text((2, y), title.upper(), font=FONT_BOLD, fill="CYAN")
        y += 12
        DRAW.line((0, y-2, W, y-2), fill="WHITE")
    for line in lines[:8]:
        DRAW.text((2, y), line, font=FONT, fill="WHITE")
        y += 11
    LCD.LCD_ShowImage(IMAGE, 0, 0)

def menu_choice(options, title="SELECT"):
    idx = 0
    while True:
        lines = [title, "-" * 18]
        for i, opt in enumerate(options):
            prefix = "> " if i == idx else "  "
            lines.append(f"{prefix}{opt}")
        display_text(lines)
        btn = wait_btn()
        if btn == "UP":
            idx = (idx - 1) % len(options)
        elif btn == "DOWN":
            idx = (idx + 1) % len(options)
        elif btn == "OK":
            wait_for_release("OK")
            return idx
        elif btn == "KEY2":
            return -1
        elif btn == "KEY3":
            sys.exit(0)

def show_message(text, wait=True):
    pages = []
    for line in text.split("\n"):
        pages.extend(wrap_text(line))
    page = 0
    while page < len(pages):
        lines = pages[page:page+8]
        display_text(lines, title="MESSAGE")
        btn = wait_btn()
        if btn == "OK":
            page += 8
        elif btn == "KEY2":
            return "hub"
        elif btn == "KEY3":
            sys.exit(0)
    if wait:
        wait_btn(timeout=2)

def prompt_yes_no(question):
    while True:
        lines = wrap_text(question, width=18)
        lines.append("")
        lines.append("> Yes")
        lines.append("  No")
        display_text(lines, title="CHOOSE")
        btn = wait_btn()
        if btn == "OK":
            return True
        elif btn == "KEY1":
            return False
        elif btn == "KEY2":
            return None
        elif btn == "KEY3":
            sys.exit(0)
        time.sleep(0.1)

# ==============================
# Enhanced Combat System
# ==============================
class Combatant:
    def __init__(self, name, hp, attack, speed=10, defense=0, abilities=None):
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.attack = attack
        self.speed = speed
        self.defense = defense
        self.status = None      # "Burn" or "Glitch"
        self.status_turns = 0
        self.abilities = abilities or []

    def is_alive(self):
        return self.hp > 0

    def take_damage(self, dmg):
        reduction = self.defense // 2
        actual = max(1, dmg - reduction)
        self.hp = max(0, self.hp - actual)
        return actual

    def apply_status(self, status, turns):
        self.status = status
        self.status_turns = turns

    def end_turn(self):
        if self.status == "Burn":
            dmg = 5
            self.hp = max(0, self.hp - dmg)
            show_message(f"{self.name} burns for {dmg} damage!")
            self.status_turns -= 1
            if self.status_turns <= 0:
                self.status = None
        elif self.status == "Glitch":
            self.status_turns -= 1
            if self.status_turns <= 0:
                self.status = None

def combat_encounter(player_crew, enemies_data, game):
    """Enhanced combat with speed sorting and status effects."""
    enemies = [Combatant(e[0], e[1], e[2], e[3] if len(e)>3 else 10) for e in enemies_data]
    all_fighters = sorted(player_crew + enemies, key=lambda x: x.speed, reverse=True)
    turn_counter = 0
    while any(e.is_alive() for e in enemies) and any(p.is_alive() for p in player_crew):
        fighter = all_fighters[turn_counter % len(all_fighters)]
        if not fighter.is_alive():
            turn_counter += 1
            continue
        if fighter in player_crew:
            # Player turn
            action = menu_choice(["Attack", "Quickhack", "Item", "Info"], title=f"{fighter.name}'s turn")
            if action == -1:
                return "hub"
            if action == 0:
                alive_enemies = [e for e in enemies if e.is_alive()]
                if not alive_enemies:
                    continue
                target_idx = menu_choice([f"{e.name} HP:{e.hp}/{e.max_hp}" for e in alive_enemies], title="Attack whom?")
                if target_idx == -1:
                    return "hub"
                target = alive_enemies[target_idx]
                dmg = fighter.attack + random.randint(-2, 4)
                actual = target.take_damage(dmg)
                show_message(f"{fighter.name} hits {target.name} for {actual}!")
                if not target.is_alive():
                    show_message(f"{target.name} is defeated!")
            elif action == 1:  # Quickhack (requires cyberdeck)
                if not game.has_item("cyberdeck"):
                    show_message("No cyberdeck installed.")
                    continue
                hack_choice = menu_choice(["Short Circuit (20E)", "Weapon Glitch (30E)", "Overheat (40E)"], "QUICKHACK")
                if hack_choice == -1:
                    continue
                if hack_choice == 0 and game.energy >= 20:
                    game.energy -= 20
                    dmg = 20
                    alive_enemies = [e for e in enemies if e.is_alive()]
                    if alive_enemies:
                        target = alive_enemies[0]
                        actual = target.take_damage(dmg)
                        show_message(f"Short Circuit! {target.name} takes {actual} damage.")
                elif hack_choice == 1 and game.energy >= 30:
                    game.energy -= 30
                    alive_enemies = [e for e in enemies if e.is_alive()]
                    if alive_enemies:
                        target = alive_enemies[0]
                        target.apply_status("Glitch", 2)
                        show_message(f"Weapon Glitch! {target.name} will glitch for 2 turns.")
                elif hack_choice == 2 and game.energy >= 40:
                    game.energy -= 40
                    alive_enemies = [e for e in enemies if e.is_alive()]
                    if alive_enemies:
                        target = alive_enemies[0]
                        target.apply_status("Burn", 3)
                        show_message(f"Overheat! {target.name} burns for 3 turns.")
                else:
                    show_message("Not enough energy.")
            elif action == 2:  # Item
                if not game.inventory:
                    show_message("No items.")
                    continue
                usable = [i for i in game.inventory if i in ["MaxDoc", "Stim", "medkit", "synthetic_meat", "real_burger"]]
                if not usable:
                    show_message("No usable items.")
                    continue
                item_idx = menu_choice(usable, title="Use which?")
                if item_idx == -1:
                    continue
                item = usable[item_idx]
                if item == "MaxDoc" or item == "medkit":
                    heal = 30 if item == "MaxDoc" else 50
                    fighter.hp = min(fighter.max_hp, fighter.hp + heal)
                    game.inventory.remove(item)
                    show_message(f"{fighter.name} used {item}. +{heal} HP.")
                elif item in ["synthetic_meat", "real_burger"]:
                    heal = 20 if item == "synthetic_meat" else 35
                    fighter.hp = min(fighter.max_hp, fighter.hp + heal)
                    game.inventory.remove(item)
                    show_message(f"{fighter.name} ate {item}. +{heal} HP.")
                elif item == "Stim":
                    fighter.attack += 5
                    game.inventory.remove(item)
                    show_message(f"{fighter.name} used Stim. Attack boosted!")
            elif action == 3:
                show_message(f"{fighter.name} HP:{fighter.hp}/{fighter.max_hp} Atk:{fighter.attack}")
        else:
            # Enemy AI
            alive_players = [p for p in player_crew if p.is_alive()]
            if not alive_players:
                return False
            target = random.choice(alive_players)
            if fighter.status == "Glitch":
                show_message(f"{fighter.name} glitches and misses!")
                fighter.end_turn()
                turn_counter += 1
                continue
            dmg = fighter.attack + random.randint(-2, 2)
            actual = target.take_damage(dmg)
            show_message(f"{fighter.name} attacks {target.name} for {actual}!")
            if not target.is_alive():
                show_message(f"{target.name} is down!")
                player_crew.remove(target)
        fighter.end_turn()
        turn_counter += 1
        if not any(p.is_alive() for p in player_crew):
            return False
        if not any(e.is_alive() for e in enemies):
            # Victory – award XP
            xp_gain = 50 + len(enemies_data)*10
            game.xp += xp_gain
            show_message(f"Victory! +{xp_gain} XP.")
            while game.xp >= 500:
                game.level_up()
            return True
    return False

# ==============================
# Modular Mission System
# ==============================
MISSIONS = {
    "act1_intro": {
        "title": "ACT 1: THE HEIST",
        "text": ["Rook: 'Steal the prototype chip from a Militech convoy.'"],
        "enemies": [("Militech Guard", 30, 8, 10), ("Militech Guard", 30, 8, 10)],
        "next": "act1_escape"
    },
    "act1_escape": {
        "title": "ACT 1: ESCAPE",
        "text": ["Alarms blare. Militech elites pursue you."],
        "enemies": [("Militech Elite", 45, 12, 12)],
        "next": "act2_voodoo"
    },
    "act2_voodoo": {
        "title": "ACT 2: VOODOO SECRETS",
        "text": ["Sable demands you deal with a NetWatch agent."],
        "enemies": [("NetWatch Agent", 40, 10, 11), ("NetWatch Drone", 25, 8, 9)],
        "next": "act3_militech"
    },
    "act3_militech": {
        "title": "ACT 3: MILITECH CONFLICT",
        "text": ["Vector offers a deal. Fight or sell out?"],
        "enemies": [("Vector", 60, 15, 13), ("Militech Soldier", 40, 10, 10)],
        "next": "act4_arasaka"
    },
    "act4_arasaka": {
        "title": "ACT 4: ARASAKA FACILITY",
        "text": ["Infiltrate the old Arasaka tower."],
        "enemies": [("Arasaka Cyborg", 80, 20, 14)],
        "next": "act5_orbital"
    },
    "act5_orbital": {
        "title": "ACT 5: ORBITAL LIFT",
        "text": ["You reach the space elevator. Security bots everywhere."],
        "enemies": [("Orbital Guard", 70, 18, 12), ("Security Drone", 50, 14, 15)],
        "next": "act6_crystal_palace"
    },
    "act6_crystal_palace": {
        "title": "ACT 6: CRYSTAL PALACE",
        "text": ["Zero‑G combat on a corpo space station."],
        "enemies": [("Elite Merc", 90, 22, 13), ("Zero‑G Drone", 60, 16, 16)],
        "next": "act7_blackwall"
    },
    "act7_blackwall": {
        "title": "ACT 7: BLACKWALL BREACH",
        "text": ["You dive into the net. Rogue AI attacks."],
        "enemies": [("Blackwall Daemon", 100, 25, 15)],
        "next": "act8_clone_vat"
    },
    "act8_clone_vat": {
        "title": "ACT 8: CLONE VAT",
        "text": ["Arasaka's secret cloning lab. Sabotage the vats."],
        "enemies": [("Clone Soldier", 80, 20, 12), ("Lab Tech", 50, 12, 10)],
        "next": "act9_siege"
    },
    "act9_siege": {
        "title": "ACT 9: NIGHT CITY SIEGE",
        "text": ["Total war on the streets. Militech vs Arasaka."],
        "enemies": [("Militech Commander", 100, 24, 14), ("Arasaka Ninja", 90, 22, 16)],
        "next": "act10_nirvana"
    },
    "act10_nirvana": {
        "title": "ACT 10: DIGITAL NIRVANA",
        "text": ["The final choice: merge with the AI or stay human."],
        "enemies": [("AI Avatar", 120, 30, 18)],
        "next": None
    }
}

def run_modular_mission(game, mission_key):
    """Handle the modular story mission chain."""
    while mission_key and mission_key in MISSIONS:
        m = MISSIONS[mission_key]
        game.show_text(m["text"], title=m["title"])
        # Build player crew (Niko + recruited crew)
        player_crew = [Combatant("Niko", game.health, 15 + game.level, 12)]
        for member in game.crew:
            if member == "Maya":
                player_crew.append(Combatant("Maya", 70, 18, 14))
            elif member == "Jin":
                player_crew.append(Combatant("Jin", 60, 12, 16, abilities=[("Overclock", 1.5)]))
            elif member == "Lina":
                player_crew.append(Combatant("Lina", 50, 10, 12, abilities=[("EMP", 1.2)]))
        result = combat_encounter(player_crew, m["enemies"], game)
        if result == "hub":
            return
        if not result:
            show_message("You died. Game Over.")
            game.running = False
            return
        # After victory, update health and energy
        for p in player_crew:
            if p.name == "Niko":
                game.health = p.hp
        game.energy = min(100, game.energy + 10)
        mission_key = m["next"]
    show_message("You completed the main story! Congratulations, legend.")
    game.running = False

# ----------------------------------------------------------------------
# Game Engine
# ----------------------------------------------------------------------
class Game:
    def __init__(self):
        self.inventory = []
        self.flags = {}
        self.scene = "start_menu"
        self.running = True
        self.rep_arasaka = 0
        self.rep_militech = 0
        self.rep_voodoo = 0
        self.rep_netwatch = 0
        self.street_cred = 0
        self.crew = []          # List of crew member names
        self.crew_loyalty = 50  # Overall loyalty 0-100
        self.romance = None
        self.health = 100
        self.eddies = 500
        self.equipped_weapon = None
        self.equipped_cyberware = None
        self.player_name = "Niko"
        self.xp = 0
        self.level = 1
        self.energy = 100

    def level_up(self):
        self.level += 1
        self.xp -= 500
        self.health = self.max_health()
        self.energy = 100
        show_message(f"LEVEL UP! You are now Level {self.level}\nMax HP increased to {self.health}")

    def max_health(self):
        return 100 + (self.level * 10)

    # ---------- Reputation ----------
    def change_reputation(self, faction, delta):
        if faction == "arasaka":
            self.rep_arasaka = max(-10, min(10, self.rep_arasaka + delta))
        elif faction == "militech":
            self.rep_militech = max(-10, min(10, self.rep_militech + delta))
        elif faction == "voodoo":
            self.rep_voodoo = max(-10, min(10, self.rep_voodoo + delta))
        elif faction == "netwatch":
            self.rep_netwatch = max(-10, min(10, self.rep_netwatch + delta))
        elif faction == "street":
            self.street_cred = max(-10, min(10, self.street_cred + delta))

    # ---------- Inventory ----------
    def add_item(self, item):
        if item not in self.inventory:
            self.inventory.append(item)

    def remove_item(self, item):
        if item in self.inventory:
            self.inventory.remove(item)

    def has_item(self, item):
        return item in self.inventory

    # ---------- Flags ----------
    def set_flag(self, flag, value=True):
        self.flags[flag] = value

    def check_flag(self, flag):
        return self.flags.get(flag, False)

    # ---------- Crew ----------
    def add_crew(self, member):
        if member not in self.crew:
            self.crew.append(member)
            self.crew_loyalty = min(100, self.crew_loyalty + 10)

    def set_romance(self, person):
        self.romance = person

    # ---------- Items ----------
    def use_item(self, item):
        if item == "synthetic_meat":
            self.health = min(self.max_health(), self.health + 20)
            self.remove_item("synthetic_meat")
            return "You eat synthetic meat. +20 health."
        elif item == "real_burger":
            self.health = min(self.max_health(), self.health + 35)
            self.remove_item("real_burger")
            return "You eat a real burger. +35 health."
        elif item == "medkit":
            self.health = min(self.max_health(), self.health + 50)
            self.remove_item("medkit")
            return "You use a medkit. +50 health."
        elif item == "smart_rifle":
            self.equipped_weapon = "smart_rifle"
            return "You equip the smart rifle. Combat bonuses applied."
        elif item == "thermal_katana":
            self.equipped_weapon = "thermal_katana"
            return "You equip the thermal katana. Combat bonuses applied."
        elif item == "cyberdeck":
            self.equipped_cyberware = "cyberdeck"
            return "You install the cyberdeck. Hacking options unlocked."
        elif item == "optical_camo":
            self.equipped_cyberware = "optical_camo"
            return "You install optical camo. Stealth improved."
        else:
            return f"You can't use {item}."

    def open_inventory(self):
        while True:
            opts = ["USE ITEM", "VIEW CREW", "EQUIP WEAPON", "BACK"]
            choice = menu_choice(opts, title="INVENTORY")
            if choice == -1 or choice == 3:
                return
            elif choice == 0:
                if not self.inventory:
                    show_message("Empty.")
                else:
                    idx = menu_choice(self.inventory, title="Use which?")
                    if idx == -1: continue
                    item = self.inventory[idx]
                    msg = self.use_item(item)
                    show_message(msg)
            elif choice == 1:
                if not self.crew:
                    show_message("No crew.")
                else:
                    menu_choice(self.crew, title="CREW")
            elif choice == 2:
                weapons = [w for w in self.inventory if any(kw in w.lower() for kw in ["pistol","smg","katana","rifle"])]
                if not weapons:
                    show_message("No weapons.")
                else:
                    idx = menu_choice(weapons, title="Equip")
                    if idx != -1:
                        self.equipped_weapon = weapons[idx]
                        show_message(f"Equipped {weapons[idx]}.")

    # ---------- Save / Load ----------
    def save_game(self):
        data = {
            "inventory": self.inventory,
            "flags": self.flags,
            "scene": self.scene,
            "rep_arasaka": self.rep_arasaka,
            "rep_militech": self.rep_militech,
            "rep_voodoo": self.rep_voodoo,
            "rep_netwatch": self.rep_netwatch,
            "street_cred": self.street_cred,
            "crew": self.crew,
            "crew_loyalty": self.crew_loyalty,
            "romance": self.romance,
            "health": self.health,
            "eddies": self.eddies,
            "equipped_weapon": self.equipped_weapon,
            "equipped_cyberware": self.equipped_cyberware,
            "xp": self.xp,
            "level": self.level,
            "energy": self.energy,
        }
        try:
            with open(SAVE_FILE, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except:
            return False

    def load_game(self):
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
            for k, v in data.items():
                setattr(self, k, v)
            return True
        except:
            return False

    # ---------- UI Wrappers ----------
    def _wrap(self, text):
        return textwrap.wrap(text, width=23)

    def show_text(self, raw_lines, title="2087"):
        all_lines = []
        for line in raw_lines:
            if not line.strip():
                all_lines.append("")
            else:
                all_lines.extend(self._wrap(line))
        pages = [all_lines[i:i+5] for i in range(0, len(all_lines), 5)]
        if not pages:
            pages = [["(nothing)"]]
        page_idx = 0
        while True:
            lines = pages[page_idx]
            global IMAGE, DRAW
            DRAW.rectangle((0, 0, W, H), fill=(10, 0, 0))
            DRAW.rectangle((0, 0, W, 13), fill=(139, 0, 0))
            DRAW.text((4, 2), title[:20], font=FONT_BOLD, fill=(231, 76, 60))
            y = 16
            for line in lines:
                DRAW.text((4, y), line[:23], font=FONT, fill=(171, 178, 185))
                y += 12
            if len(pages) > 1:
                DRAW.text((W-15, H-12), f"{page_idx+1}/{len(pages)}", font=FONT, fill=(192,57,43))
            inv_str = f"HP:{self.health} E:{self.eddies} Lv:{self.level}"
            rep_str = f"A:{self.rep_arasaka} M:{self.rep_militech}"
            DRAW.text((4, H-12), f"{inv_str[:12]} {rep_str}", font=FONT, fill=(192,57,43))
            LCD.LCD_ShowImage(IMAGE, 0, 0)
            btn = wait_btn(0.2)
            if btn == "UP":
                page_idx = max(0, page_idx-1)
                wait_for_release("UP")
            elif btn == "DOWN":
                page_idx = min(len(pages)-1, page_idx+1)
                wait_for_release("DOWN")
            elif btn == "OK":
                if page_idx < len(pages)-1:
                    page_idx += 1
                else:
                    wait_for_release("OK")
                    return
                wait_for_release("OK")
            elif btn == "KEY2":
                wait_for_release("KEY2")
                self.scene = "afterlife_hub"
                return
            elif btn == "KEY3":
                wait_for_release("KEY3")
                self.running = False
                return

    def choose(self, choices, title="2087"):
        if not choices:
            return None
        selected = 0
        while True:
            global IMAGE, DRAW
            DRAW.rectangle((0, 0, W, H), fill=(10, 0, 0))
            DRAW.rectangle((0, 0, W, 13), fill=(139, 0, 0))
            DRAW.text((4, 2), title[:20], font=FONT_BOLD, fill=(231, 76, 60))
            y = 16
            start = max(0, selected - 2)
            end = min(len(choices), start + 5)
            visible = choices[start:end]
            for i, ch in enumerate(visible):
                actual_idx = start + i
                if actual_idx == selected:
                    DRAW.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
                    DRAW.text((4, y), f"> {ch[:21]}", font=FONT, fill=(255, 255, 255))
                else:
                    DRAW.text((4, y), f"  {ch[:21]}", font=FONT, fill=(171, 178, 185))
                y += 12
            if len(choices) > 5:
                DRAW.text((W-10, H-12), f"{selected+1}/{len(choices)}", font=FONT, fill=(192,57,43))
            inv_str = f"HP:{self.health} E:{self.eddies} Lv:{self.level}"
            rep_str = f"A:{self.rep_arasaka} M:{self.rep_militech}"
            DRAW.text((4, H-12), f"{inv_str[:12]} {rep_str}", font=FONT, fill=(192,57,43))
            LCD.LCD_ShowImage(IMAGE, 0, 0)
            btn = wait_btn(0.2)
            if btn == "UP":
                selected = max(0, selected-1)
                wait_for_release("UP")
            elif btn == "DOWN":
                selected = min(len(choices)-1, selected+1)
                wait_for_release("DOWN")
            elif btn == "OK":
                wait_for_release("OK")
                return selected
            elif btn == "KEY2":
                wait_for_release("KEY2")
                self.scene = "afterlife_hub"
                return -1
            elif btn == "KEY3":
                wait_for_release("KEY3")
                self.running = False
                return -2

# =============================================================================
# SCENE DEFINITIONS (All original side content + new framework)
# =============================================================================
def scene_start_menu(g):
    while True:
        g.show_text(["Cyberpunk 2087", "Choose an option:"])
        choices = ["New Game", "Continue"]
        idx = g.choose(choices)
        if idx == 0:
            g.__init__()
            g.scene = "start"
            return "start"
        elif idx == 1:
            if g.load_game():
                g.show_text(["Game loaded.", f"Returning to {g.scene}"])
                return g.scene
            else:
                g.show_text(["No save file found.", "Starting new game."])
                g.scene = "start"
                return "start"
        else:
            # -1 or other: stay in menu
            continue

def scene_start(g):
    g.show_text([
        ">>> 2087 <<<",
        "Night City. The neon never dies. Arasaka is a ghost, Militech runs the streets.",
        "You are Niko. Twenty-three, chromeless, broke. You heard a rumor:",
        "A netrunner named Lucy still haunts the old networks. Some say she's looking for a crew.",
        "You don't believe in ghosts. But you believe in eddies."
    ])
    choices = ["Go to the Afterlife", "Scavenge the Combat Zone", "Visit Kabuki market"]
    idx = g.choose(choices)
    if idx == 0: return "afterlife_hub"
    elif idx == 1: return "combat_zone"
    elif idx == 2: return "kabuki"
    else: return "afterlife_hub"  # Cancel

# --------------------- CENTRAL HUB ---------------------
def scene_afterlife_hub(g):
    g.show_text([
        "The Afterlife. A drink called 'David Martinez' is still the bestseller.",
        f"Health: {g.health} | Eddies: {g.eddies} | Level: {g.level}",
        "Who do you want to talk to?"
    ])
    choices = ["Main Story (Modular Acts)", "Talk to Fixer (side gigs)", "Talk to Bartender (food/rumors)", "Visit Shop", "Talk to your crew", "Save Game", "Leave"]
    idx = g.choose(choices)
    if idx == 0:
        run_modular_mission(g, "act1_intro")
        return "afterlife_hub"
    elif idx == 1: return "fixer_gigs"
    elif idx == 2: return "bartender"
    elif idx == 3: return "shop"
    elif idx == 4: return "crew_hub"
    elif idx == 5:
        if g.save_game():
            g.show_text(["Game saved."])
        else:
            g.show_text(["Save failed."])
        return "afterlife_hub"
    elif idx == 6: return "street"
    else: return "afterlife_hub"

# --------------------- STREET with reputation events ---------------------
def scene_street(g):
    # Reputation-based random encounter
    if random.random() < 0.2 and (g.rep_arasaka < -5 or g.rep_militech < -5):
        show_message("Arasaka assassins ambush you!")
        player_crew = [Combatant("Niko", g.health, 15 + g.level, 12)]
        for m in g.crew:
            if m == "Maya":
                player_crew.append(Combatant("Maya", 70, 18, 14))
            elif m == "Jin":
                player_crew.append(Combatant("Jin", 60, 12, 16))
            elif m == "Lina":
                player_crew.append(Combatant("Lina", 50, 10, 12))
        result = combat_encounter(player_crew, [("Arasaka Assassin", 60, 15, 13)], g)
        if result == "hub":
            return "afterlife_hub"
        if result:
            g.health = player_crew[0].hp
            show_message("You survive the attack.")
        else:
            g.running = False
            return None
    g.show_text([
        "You step outside. Night City streets. Rain. Neon reflections.",
        "Where to now?"
    ])
    choices = ["Go back to Afterlife", "Explore the Combat Zone", "Visit Kabuki market", "Go to Pacifica"]
    idx = g.choose(choices)
    if idx == 0: return "afterlife_hub"
    elif idx == 1: return "combat_zone"
    elif idx == 2: return "kabuki"
    elif idx == 3: return "pacifica_side"
    else: return "afterlife_hub"

# --------------------- SIDE GIGS (Original) ---------------------
def scene_fixer_gigs(g):
    g.show_text([
        "Fixer: 'Niko, I got work. Militech convoy job still open.'",
        "Also, a corpo wants a data extraction from a gang hideout."
    ])
    choices = ["Take Militech convoy job", "Take data extraction job", "Just browse", "Back"]
    idx = g.choose(choices)
    if idx == 0:
        if g.check_flag("militech_job"):
            g.show_text(["You already accepted this job."])
            return "fixer_gigs"
        else:
            g.set_flag("militech_job")
            g.change_reputation("militech", -1)
            return "militech_prep"
    elif idx == 1:
        return "data_extraction"
    elif idx == 2:
        g.show_text(["Fixer shrugs."])
        return "afterlife_hub"
    else:  # idx == 3 or -1
        return "afterlife_hub"

def scene_data_extraction(g):
    g.show_text([
        "The gang hideout is guarded. You need a weapon or stealth."
    ])
    if g.has_item("smart_rifle") or g.has_item("thermal_katana"):
        g.show_text(["You fight through and get the data. +2000 eddies, +5 street cred."])
        g.eddies += 2000
        g.change_reputation("street", 5)
    else:
        g.show_text(["Without a weapon, you fail. You lose 500 eddies."])
        g.eddies = max(0, g.eddies - 500)
    return "afterlife_hub"

def scene_bartender(g):
    g.show_text([
        "Bartender: 'Want something to eat? Synthetic meat (20 eddies, +20 HP) or real burger (50 eddies, +35 HP).'"
    ])
    choices = ["Buy synthetic meat", "Buy real burger", "Just chat", "Back"]
    idx = g.choose(choices)
    if idx == 0:
        if g.eddies >= 20:
            g.eddies -= 20
            g.add_item("synthetic_meat")
            g.show_text(["You bought synthetic meat."])
        else:
            g.show_text(["Not enough eddies."])
    elif idx == 1:
        if g.eddies >= 50:
            g.eddies -= 50
            g.add_item("real_burger")
            g.show_text(["You bought a real burger."])
        else:
            g.show_text(["Not enough eddies."])
    elif idx == 2:
        g.show_text(["Bartender: 'Heard Militech is up to something. Also, Lucy might be in Pacifica.'"])
    # idx 3 or -1 just returns
    return "afterlife_hub"

def scene_shop(g):
    g.show_text([
        "Shopkeeper: 'What do you need? Weapons, cyberware, medkits?'"
    ])
    choices = ["Smart rifle (2000 eddies)", "Optical camo (1500 eddies)", "Medkit (100 eddies)", "Back"]
    idx = g.choose(choices)
    if idx == 0:
        if g.eddies >= 2000:
            g.eddies -= 2000
            g.add_item("smart_rifle")
            g.show_text(["You bought a smart rifle."])
        else:
            g.show_text(["Not enough eddies."])
    elif idx == 1:
        if g.eddies >= 1500:
            g.eddies -= 1500
            g.add_item("optical_camo")
            g.show_text(["You bought optical camo."])
        else:
            g.show_text(["Not enough eddies."])
    elif idx == 2:
        if g.eddies >= 100:
            g.eddies -= 100
            g.add_item("medkit")
            g.show_text(["You bought a medkit."])
        else:
            g.show_text(["Not enough eddies."])
    return "afterlife_hub"

def scene_crew_hub(g):
    if not g.crew:
        g.show_text(["You have no crew yet. Explore to recruit Maya, Jin, or Lina."])
        return "afterlife_hub"
    crew_names = ", ".join(g.crew)
    g.show_text([f"Your crew: {crew_names}. Loyalty: {g.crew_loyalty}%"])
    choices = []
    for member in g.crew:
        choices.append(f"Talk to {member}")
    choices.append("Back")
    idx = g.choose(choices)
    if idx == -1 or idx == len(choices)-1:
        return "afterlife_hub"
    member = g.crew[idx]
    if member == "Maya":
        return "talk_maya"
    elif member == "Jin":
        return "talk_jin"
    elif member == "Lina":
        return "talk_lina"
    return "afterlife_hub"

def scene_talk_maya(g):
    g.show_text(["Maya: 'You saved my life, Niko. I trust you. Want to grab a drink sometime?'"])
    choices = ["Yes (romance path)", "No, just friends"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_romance("maya")
        g.show_text(["You and Maya start dating. She joins you permanently."])
    return "afterlife_hub"

def scene_talk_jin(g):
    g.show_text(["Jin: 'Niko, you're a good leader. I've got your back.'"])
    return "afterlife_hub"

def scene_talk_lina(g):
    g.show_text(["Lina: 'The tech is ready. Need an upgrade?'"])
    choices = ["Install cyberware", "Just chat", "Back"]
    idx = g.choose(choices)
    if idx == 0:
        if g.has_item("cyberdeck"):
            g.equipped_cyberware = "cyberdeck"
            g.show_text(["Lina installs the cyberdeck. Hacking options unlocked."])
        elif g.has_item("optical_camo"):
            g.equipped_cyberware = "optical_camo"
            g.show_text(["Lina installs optical camo. Stealth improved."])
        else:
            g.show_text(["You have no cyberware to install."])
    return "afterlife_hub"

# --------------------- COMBAT ZONE (Original) ---------------------
def scene_combat_zone(g):
    g.show_text([
        "The Combat Zone. Scavs, Maelstrom remnants, and desperate souls.",
        "You spot a wounded solo being cornered by three thugs."
    ])
    choices = ["Help the solo", "Ignore and loot nearby", "Join the thugs"]
    idx = g.choose(choices)
    if idx == 0:
        player_crew = [Combatant("Niko", g.health, 15 + g.level, 12)]
        result = combat_encounter(player_crew, [("Thug", 30, 8, 10), ("Thug", 30, 8, 10), ("Thug Leader", 40, 10, 11)], g)
        if result == "hub": return "afterlife_hub"
        if result:
            g.health = player_crew[0].hp
            g.add_crew("Maya")
            g.show_text(["You fight them off. The solo introduces herself as Maya."])
            return "maya_recruit"
        else:
            g.running = False
            return None
    elif idx == 1:
        g.add_item("junk")
        return "combat_zone_loot"
    elif idx == 2:
        g.change_reputation("street", -2)
        return "combat_zone_bad"
    else:
        return "afterlife_hub"

def scene_maya_recruit(g):
    g.show_text([
        "Maya: 'Thanks, choom. I'm Maya. I'm a solo. You got a crew?'",
        "'Not yet. But I'm building one. Want in?'",
        "She grins. 'You just saved my life. I owe you. I'm in.'"
    ])
    return "afterlife_hub"

def scene_combat_zone_loot(g):
    g.show_text(["You find a damaged cyberdeck. It might work."])
    g.add_item("broken_cyberdeck")
    return "afterlife_hub"

def scene_combat_zone_bad(g):
    g.show_text(["The thugs kill the solo. They turn on you. You barely escape."])
    return "afterlife_hub"

# --------------------- KABUKI (Original) ---------------------
def scene_kabuki(g):
    g.show_text([
        "Kabuki market. Smells of noodles and ozone.",
        "A street vendor whispers: 'You looking for a netrunner? I know one.'"
    ])
    choices = ["Follow the vendor", "Ignore and look yourself", "Buy a hot dog"]
    idx = g.choose(choices)
    if idx == 0: return "vendor_netrunner"
    elif idx == 1: return "kabuki_search"
    elif idx == 2: return "kabuki_hotdog"
    else: return "afterlife_hub"

def scene_vendor_netrunner(g):
    g.show_text([
        "The vendor leads you to a basement. A figure in a hooded jacket sits at a terminal.",
        "'Name's Jin. I heard you need a netrunner. I'm the best in Kabuki.'"
    ])
    choices = ["Hire Jin (500 eddies)", "Promise a cut of future jobs", "Leave"]
    idx = g.choose(choices)
    if idx == 0 and g.eddies >= 500:
        g.eddies -= 500
        g.add_crew("Jin")
        return "jin_crew"
    elif idx == 1:
        g.set_flag("debt_to_jin")
        g.add_crew("Jin")
        return "jin_crew"
    elif idx == 2:
        return "kabuki"
    else:
        return "afterlife_hub"

def scene_jin_crew(g):
    g.show_text(["Jin: 'Alright, Niko. I'll join your crew. Just don't get me killed.'"])
    return "afterlife_hub"

def scene_kabuki_search(g):
    g.show_text(["You search the market but find no netrunner. Just junk."])
    g.add_item("junk")
    return "afterlife_hub"

def scene_kabuki_hotdog(g):
    g.show_text(["The hot dog is surprisingly good. +5 morale."])
    return "afterlife_hub"

# --------------------- MILITECH JOB CHAIN (Original) ---------------------
def scene_militech_prep(g):
    g.show_text([
        "You prepare for the Militech job. You need more firepower.",
        "Maya suggests hitting a weapon stash."
    ])
    choices = ["Hit the weapon stash", "Go alone to the convoy", "Find a techie first"]
    idx = g.choose(choices)
    if idx == 0: return "weapon_stash"
    elif idx == 1: return "convoy_alone"
    elif idx == 2: return "find_techie"
    else: return "afterlife_hub"

def scene_weapon_stash(g):
    g.show_text([
        "You and Maya break into a Militech armory. Guards everywhere.",
        "Maya distracts them. You grab a smart rifle and a thermal katana."
    ])
    g.add_item("smart_rifle")
    g.add_item("thermal_katana")
    return "convoy"

def scene_convoy_alone(g):
    g.show_text([
        "You ambush the convoy alone. Outnumbered, you nearly die.",
        "But you manage to grab the prototype neural processor."
    ])
    g.add_item("prototype_neural_processor")
    g.change_reputation("militech", -3)
    return "after_convoy"

def scene_find_techie(g):
    g.show_text([
        "You ask around for a techie. A contact points you to a garage in Rancho Coronado.",
        "A woman named Lina works on a heavily modified Thorton."
    ])
    choices = ["Hire Lina", "Fix your own gear", "Leave"]
    idx = g.choose(choices)
    if idx == 0:
        g.add_crew("Lina")
        return "lina_crew"
    elif idx == 1:
        return "convoy"
    else:
        return "afterlife_hub"

def scene_lina_crew(g):
    g.show_text(["Lina: 'I'll join. But I get a 20% cut of every job.'"])
    return "convoy"

def scene_convoy(g):
    g.show_text([
        "With your crew ready, you hit the Militech convoy.",
        "Jin disables their comms. Maya snipes the turrets. Lina hotwires the transport.",
        "You grab the prototype. Success!"
    ])
    g.add_item("prototype_neural_processor")
    g.eddies += 10000
    g.change_reputation("street", 3)
    return "after_convoy"

def scene_after_convoy(g):
    g.show_text([
        "You return to the Afterlife. Fixer pays you 10k eddies.",
        "Word spreads. You're no longer a nobody. A Militech agent approaches you."
    ])
    choices = ["Talk to Militech agent", "Ignore her", "Take a break at the bar"]
    idx = g.choose(choices)
    if idx == 0: return "militech_agent"
    elif idx == 1: return "afterlife_hub"
    elif idx == 2: return "bar_break"
    else: return "afterlife_hub"

def scene_militech_agent(g):
    g.show_text([
        "Agent: 'Niko, we saw your work. Militech wants to hire you for a bigger job.",
        "Infiltrate the old Arasaka tower ruins. Retrieve data on the Relic 2.0 prototype.'"
    ])
    choices = ["Accept Militech job", "Refuse", "Ask about payment"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_flag("arasaka_job")
        g.change_reputation("militech", 2)
        return "arasaka_tower"
    elif idx == 1:
        return "afterlife_hub"
    elif idx == 2:
        g.show_text(["Agent: '20k eddies, plus a full cyberware suite.'"])
        return "militech_agent"
    else:
        return "afterlife_hub"

def scene_bar_break(g):
    g.show_text([
        "You sit at the bar. A woman with silver hair sits next to you.",
        "'You're Niko. I heard you're looking for a ghost.'"
    ])
    choices = ["Who are you?", "What ghost?", "Ignore her"]
    idx = g.choose(choices)
    if idx == 0:
        return "mysterious_woman"
    elif idx == 1:
        return "ghost_talk"
    else:
        return "afterlife_hub"

def scene_mysterious_woman(g):
    g.show_text([
        "'My name is Maya. No, not your solo. Different Maya.'",
        "'I know where Lucy is. But you'll need to prove yourself first.'"
    ])
    g.set_flag("met_mysterious_maya")
    return "afterlife_hub"

def scene_ghost_talk(g):
    g.show_text([
        "'The ghost netrunner. Lucy. She's real. And she's looking for someone to help her finish what David started.'"
    ])
    return "afterlife_hub"

# --------------------- ARASAKA TOWER (Original) ---------------------
def scene_arasaka_tower(g):
    g.show_text([
        "The old Arasaka tower is a crumbling skeleton. Radiation warnings everywhere.",
        "Your crew suits up. Jin says, 'The subnet is still active. And there's something in there.'"
    ])
    choices = ["Enter the tower", "Abort the mission", "Search for another entrance"]
    idx = g.choose(choices)
    if idx == 0: return "tower_entrance"
    elif idx == 1: return "afterlife_hub"
    elif idx == 2: return "tower_side"
    else: return "afterlife_hub"

def scene_tower_side(g):
    g.show_text([
        "You find a side entrance. It's a maintenance shaft.",
        "You climb down. It leads directly to the sublevel lab.",
        "You bypass the main security."
    ])
    return "tower_sublevel"

def scene_tower_entrance(g):
    g.show_text([
        "The main lobby is dark. Bodies of Arasaka security from decades ago.",
        "A ghostly projection flickers: 'Warning – unauthorized access. Security systems active.'"
    ])
    choices = ["Hack the terminal", "Fight through", "Use the vents"]
    idx = g.choose(choices)
    if idx == 0 and "Jin" in g.crew:
        return "tower_hack"
    elif idx == 1 and "Maya" in g.crew:
        return "tower_fight"
    elif idx == 2:
        return "tower_vents"
    else:
        return "tower_fail"

def scene_tower_hack(g):
    g.show_text(["Jin cracks the security. 'There's a Black ICE. Hold on...'", "He bypasses it. The door opens."])
    return "tower_sublevel"

def scene_tower_fight(g):
    g.show_text(["Maya engages the automated turrets. You take cover. Lina disables them with an EMP."])
    return "tower_sublevel"

def scene_tower_vents(g):
    g.show_text(["You crawl through vents. The air is stale. You emerge in a server room."])
    return "tower_sublevel"

def scene_tower_fail(g):
    g.show_text(["Alarms blare. The floor collapses. You barely escape with your life."])
    return "afterlife_hub"

def scene_tower_sublevel(g):
    g.show_text([
        "Sublevel -3. The relic research lab. A single terminal glows.",
        "On it: 'Project Relic 2.0 – engram transfer complete. Status: active.'"
    ])
    choices = ["Download data", "Destroy the terminal", "Search for physical drives"]
    idx = g.choose(choices)
    if idx == 0:
        g.add_item("relic_data")
        return "tower_ending"
    elif idx == 1:
        return "tower_destroy"
    elif idx == 2:
        return "tower_search"
    else:
        return "afterlife_hub"

def scene_tower_destroy(g):
    g.show_text(["You smash the terminal. The data is lost. Militech is furious."])
    g.change_reputation("militech", -5)
    return "after_convoy"

def scene_tower_search(g):
    g.show_text(["You find a hidden databank. It contains the Relic 2.0 schematics."])
    g.add_item("relic_schematics")
    return "tower_ending"

def scene_tower_ending(g):
    g.show_text([
        "You escape as the tower begins to collapse. Militech is pleased.",
        "You are now a legend. But the ghost netrunner finally contacts you."
    ])
    return "lucy_contact"

# --------------------- LUCY / ENDGAME (Original) ---------------------
def scene_lucy_contact(g):
    g.show_text([
        "A secure message appears on your agent: 'Niko. Meet me at the old netrunner den in Pacifica.",
        "Come alone. – L'"
    ])
    choices = ["Go to Pacifica", "Ignore the message", "Bring your crew"]
    idx = g.choose(choices)
    if idx == 0: return "pacifica_den"
    elif idx == 1: return "afterlife_hub"
    elif idx == 2: return "crew_lucy"
    else: return "afterlife_hub"

def scene_pacifica_den(g):
    g.show_text([
        "You enter the den. Holographic ghosts of netrunners past.",
        "A figure in a white jacket turns. Silver hair. 'I'm Lucy. You've heard of me.'"
    ])
    choices = ["Ask about David", "Offer to help her", "Ask for a job"]
    idx = g.choose(choices)
    if idx == 0: return "lucy_david"
    elif idx == 1: return "lucy_help"
    elif idx == 2: return "lucy_job"
    else: return "afterlife_hub"

def scene_lucy_david(g):
    g.show_text([
        "Lucy's eyes harden. 'David's dead. But his dream isn't. Arasaka still has engrams.",
        "'I want to free them. Will you help me?'"
    ])
    choices = ["Yes", "No", "Ask about payment"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_flag("lucy_mission")
        return "lucy_mission"
    elif idx == 1:
        return "afterlife_hub"
    elif idx == 2:
        g.show_text(["Lucy: 'There's no payment. Only justice.'"])
        return "lucy_david"
    else:
        return "afterlife_hub"

def scene_lucy_help(g):
    g.show_text([
        "Lucy: 'Good. We need to infiltrate the last Arasaka subnet. The Mikoshi backup.'"
    ])
    g.set_flag("lucy_mission")
    return "lucy_mission"

def scene_lucy_job(g):
    g.show_text(["Lucy: 'I don't have jobs. I have a cause. Are you in?'"])
    choices = ["Yes", "No"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_flag("lucy_mission")
        return "lucy_mission"
    else:
        return "afterlife_hub"

def scene_crew_lucy(g):
    g.show_text([
        "You bring your crew. Lucy is annoyed but accepts.",
        "Maya: 'A ghost? This is insane.' Jin: 'I've heard legends about her.'"
    ])
    return "pacifica_den"

def scene_lucy_mission(g):
    g.show_text([
        "Lucy explains: 'The Mikoshi backup is in a hidden bunker beneath the Badlands.",
        "We need to jack in simultaneously. One mistake and we're all fried.'"
    ])
    choices = ["Proceed with mission", "Back out", "Ask for more time to prepare"]
    idx = g.choose(choices)
    if idx == 0: return "mikoshi_bunker"
    elif idx == 1: return "afterlife_hub"
    elif idx == 2: return "lucy_prepare"
    else: return "afterlife_hub"

def scene_lucy_prepare(g):
    g.show_text(["You gather better gear. Jin upgrades his deck. Lina builds a portable ICE."])
    return "mikoshi_bunker"

def scene_mikoshi_bunker(g):
    g.show_text([
        "The bunker is heavily guarded. Lucy hacks the turrets. You fight through.",
        "Inside, a massive server. Lucy: 'This is it. David's engram is in there.'"
    ])
    choices = ["Help Lucy extract engrams", "Sabotage the server for Militech", "Destroy everything"]
    idx = g.choose(choices)
    if idx == 0:
        return "ending_legend"
    elif idx == 1:
        return "ending_sellout"
    elif idx == 2:
        return "ending_purge"
    else:
        return "afterlife_hub"

def scene_pacifica_side(g):
    g.show_text(["In Pacifica, a street preacher warns of the Voodoo Boys' net."])
    choices = ["Ignore him", "Ask for a job"]
    idx = g.choose(choices)
    if idx == 1:
        g.set_flag("voodoo_contact")
        return "voodoo_side"
    else:
        return "afterlife_hub"

def scene_voodoo_side(g):
    g.show_text(["The Voodoo Boys offer you a netrunning gig. Payment: 3k."])
    choices = ["Accept", "Refuse"]
    idx = g.choose(choices)
    if idx == 0:
        g.eddies += 3000
        g.change_reputation("voodoo", 2)
        return "afterlife_hub"
    else:
        return "afterlife_hub"

# --------------------- ENDINGS (Original) ---------------------
def ending_legend(g):
    g.show_text([
        "You extract the engrams. David's is incomplete, but his dream lives on.",
        "Lucy thanks you. She vanishes into the net. Your crew becomes legendary.",
        "You are Niko, the one who freed the ghosts. ENDING: GHOST LEGEND"
    ])
    g.running = False
    return None

def ending_sellout(g):
    g.show_text([
        "You sell the Mikoshi data to Militech. They pay you a fortune.",
        "But Lucy is captured. Your crew disowns you. You are rich and alone.",
        "ENDING: CORPO PUPPET"
    ])
    g.running = False
    return None

def ending_purge(g):
    g.show_text([
        "You destroy the server. All engrams are lost. Lucy dies with them.",
        "Arasaka's past is gone, but so is any chance of redemption.",
        "You wander the wasteland. ENDING: ASHES"
    ])
    g.running = False
    return None

# --------------------- SCENE DISPATCHER ---------------------
scene_map = {
    "start_menu": scene_start_menu,
    "start": scene_start,
    "afterlife_hub": scene_afterlife_hub,
    "fixer_gigs": scene_fixer_gigs,
    "data_extraction": scene_data_extraction,
    "bartender": scene_bartender,
    "shop": scene_shop,
    "crew_hub": scene_crew_hub,
    "talk_maya": scene_talk_maya,
    "talk_jin": scene_talk_jin,
    "talk_lina": scene_talk_lina,
    "street": scene_street,
    "combat_zone": scene_combat_zone,
    "maya_recruit": scene_maya_recruit,
    "combat_zone_loot": scene_combat_zone_loot,
    "combat_zone_bad": scene_combat_zone_bad,
    "kabuki": scene_kabuki,
    "vendor_netrunner": scene_vendor_netrunner,
    "jin_crew": scene_jin_crew,
    "kabuki_search": scene_kabuki_search,
    "kabuki_hotdog": scene_kabuki_hotdog,
    "militech_prep": scene_militech_prep,
    "weapon_stash": scene_weapon_stash,
    "convoy_alone": scene_convoy_alone,
    "find_techie": scene_find_techie,
    "lina_crew": scene_lina_crew,
    "convoy": scene_convoy,
    "after_convoy": scene_after_convoy,
    "militech_agent": scene_militech_agent,
    "bar_break": scene_bar_break,
    "mysterious_woman": scene_mysterious_woman,
    "ghost_talk": scene_ghost_talk,
    "arasaka_tower": scene_arasaka_tower,
    "tower_side": scene_tower_side,
    "tower_entrance": scene_tower_entrance,
    "tower_hack": scene_tower_hack,
    "tower_fight": scene_tower_fight,
    "tower_vents": scene_tower_vents,
    "tower_fail": scene_tower_fail,
    "tower_sublevel": scene_tower_sublevel,
    "tower_destroy": scene_tower_destroy,
    "tower_search": scene_tower_search,
    "tower_ending": scene_tower_ending,
    "lucy_contact": scene_lucy_contact,
    "pacifica_den": scene_pacifica_den,
    "lucy_david": scene_lucy_david,
    "lucy_help": scene_lucy_help,
    "lucy_job": scene_lucy_job,
    "crew_lucy": scene_crew_lucy,
    "lucy_mission": scene_lucy_mission,
    "lucy_prepare": scene_lucy_prepare,
    "mikoshi_bunker": scene_mikoshi_bunker,
    "pacifica_side": scene_pacifica_side,
    "voodoo_side": scene_voodoo_side,
    "ending_legend": ending_legend,
    "ending_sellout": ending_sellout,
    "ending_purge": ending_purge,
}

def run_scene(g, name):
    if name in scene_map:
        return scene_map[name](g)
    else:
        g.show_text([f"Missing scene: {name}. Returning to Afterlife."])
        return "afterlife_hub"

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    game = Game()
    game.running = True
    while game.running:
        btn = wait_btn(0.01)
        if btn == "KEY1":
            game.open_inventory()
            continue
        elif btn == "KEY2":
            game.scene = "afterlife_hub"
            continue
        next_scene = run_scene(game, game.scene)
        if next_scene is None:
            break
        game.scene = next_scene
    GPIO.cleanup()
    LCD.LCD_Clear()

if __name__ == "__main__":
    main()
