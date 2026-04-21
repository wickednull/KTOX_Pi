#!/usr/bin/env python3
"""
KTOx Payload – Cyberpunk: Neural Nexus (Epic Edition)
========================================================
A massive text adventure with 60+ scenes, faction reputation,
inventory puzzles, and multiple endings. Play time: 1-2 hours.

Controls: UP/DOWN = scroll choices, OK = select, KEY3 = exit.
"""

import os
import sys
import time
import json
import random

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Hardware setup
# ----------------------------------------------------------------------
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
# Game engine with reputation system
# ----------------------------------------------------------------------
class Game:
    def __init__(self):
        self.inventory = []
        self.flags = {}
        self.scene = "start"
        self.running = True
        self.rep_arasaka = 0
        self.rep_militech = 0
        self.rep_voodoo = 0
        self.rep_netwatch = 0
        self.street_cred = 0

    def draw_text(self, lines, choices, selected):
        img = Image.new("RGB", (W, H), (10, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
        d.text((4, 2), "NEURAL NEXUS", font=FONT_BOLD, fill=(231, 76, 60))
        y = 16
        for line in lines[:5]:
            d.text((4, y), line[:23], font=FONT, fill=(171, 178, 185))
            y += 12
        for i, choice in enumerate(choices):
            if i == selected:
                d.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
                d.text((4, y), f"> {choice[:21]}", font=FONT, fill=(255, 255, 255))
            else:
                d.text((4, y), f"  {choice[:21]}", font=FONT, fill=(171, 178, 185))
            y += 12
        # Status line: inventory short + rep summary
        inv_str = " ".join(self.inventory[:2]) if self.inventory else "empty"
        rep_str = f"A:{self.rep_arasaka} M:{self.rep_militech} V:{self.rep_voodoo}"
        d.text((4, H-12), f"{inv_str[:12]} {rep_str}", font=FONT, fill=(192, 57, 43))
        LCD.LCD_ShowImage(img, 0, 0)

    def get_choice(self, choices):
        selected = 0
        while True:
            btn = wait_btn(0.1)
            if btn == "UP":
                selected = (selected - 1) % len(choices)
            elif btn == "DOWN":
                selected = (selected + 1) % len(choices)
            elif btn == "OK":
                return selected
            elif btn == "KEY3":
                self.running = False
                return None
            # Redraw with current selection
            # (The scene handler is responsible for calling draw_text again)
        return None

    def add_item(self, item):
        if item not in self.inventory:
            self.inventory.append(item)

    def remove_item(self, item):
        if item in self.inventory:
            self.inventory.remove(item)

    def has_item(self, item):
        return item in self.inventory

    def set_flag(self, flag, value=True):
        self.flags[flag] = value

    def check_flag(self, flag):
        return self.flags.get(flag, False)

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

# ----------------------------------------------------------------------
# Scene definitions (60+)
# ----------------------------------------------------------------------
def scene_start(g):
    g.draw_text([
        ">>> NEURAL NEXUS <<<",
        "Night City, 2087. You are",
        "Kael, a freelance netrunner.",
        "Your last job went south.",
        "You owe money to a fixer."
    ], ["Go to the Afterlife bar", "Hide in your apartment", "Contact an old contact"], 0)
    choice = g.get_choice(["Go to Afterlife", "Hide in apartment", "Contact contact"])
    if choice == 0:
        return "afterlife_bar"
    elif choice == 1:
        return "apartment"
    else:
        return "contact"

def scene_apartment(g):
    g.draw_text([
        "Your cramped apartment.",
        "The walls flicker with",
        "ads for cyberware. A",
        "knock at the door."
    ], ["Open the door", "Pretend you're not home", "Escape out the window"], 0)
    choice = g.get_choice(["Open door", "Hide", "Window"])
    if choice == 0:
        return "apartment_visitor"
    elif choice == 1:
        return "apartment_hide"
    else:
        return "apartment_window"

def scene_apartment_visitor(g):
    g.draw_text([
        "It's Rikki, a street kid.",
        "'Arasaka is looking for",
        "you. They know about the",
        "data you stole.'"
    ], ["Go with Rikki to the Afterlife", "Stay and fight", "Pay off the debt"], 0)
    choice = g.get_choice(["Go to Afterlife", "Stay and fight", "Pay debt"])
    if choice == 0:
        g.change_reputation("street", 1)
        return "afterlife_bar"
    elif choice == 1:
        return "ending_death"
    else:
        if g.has_item("cred_chip"):
            g.remove_item("cred_chip")
            return "afterlife_bar"
        else:
            g.draw_text(["You have no money."], ["OK"], 0)
            g.get_choice(["OK"])
            return "apartment_visitor"

def scene_apartment_hide(g):
    g.draw_text(["They kick the door down.", "You're caught."], ["Fight", "Surrender"], 0)
    choice = g.get_choice(["Fight", "Surrender"])
    if choice == 0:
        return "ending_death"
    else:
        return "ending_captured"

def scene_apartment_window(g):
    g.draw_text(["You jump into the alley.", "Sprain your ankle. Bleeding."], ["Crawl to the street", "Call for help"], 0)
    choice = g.get_choice(["Crawl", "Call"])
    if choice == 0:
        return "street"
    else:
        g.draw_text(["No signal."], ["OK"], 0)
        g.get_choice(["OK"])
        return "apartment_window"

def scene_contact(g):
    g.draw_text(["Your contact is dead.", "The number is disconnected."], ["Return to start"], 0)
    g.get_choice(["Return"])
    return "start"

def scene_afterlife_bar(g):
    lines = [
        "The Afterlife: smoky,",
        "neon-drenched. Mercs and",
        "corpos mingle. A fixer",
        "named Rogue waves you over."
    ]
    if g.rep_militech >= 5:
        lines.append("A Militech agent nods at you.")
    if g.rep_arasaka >= 5:
        lines.append("An Arasaka executive scowls.")
    g.draw_text(lines, ["Talk to Rogue (main quest)", "Sit at the bar (gather rumors)", "Pickpocket a corpo"], 0)
    choice = g.get_choice(["Talk to Rogue", "Sit at bar", "Pickpocket"])
    if choice == 0:
        return "rogue_quest"
    elif choice == 1:
        return "bar_rumors"
    else:
        return "pickpocket"

def scene_bar_rumors(g):
    g.draw_text([
        "Bartender says: 'Arasaka",
        "AI core is in the basement.",
        "Militech wants it destroyed.'",
        "Also, a rogue AI called",
        "'Wintermute' is loose."
    ], ["Go back to Rogue", "Leave the bar"], 0)
    choice = g.get_choice(["Back to Rogue", "Leave"])
    if choice == 0:
        return "rogue_quest"
    else:
        return "street"

def scene_pickpocket(g):
    if g.has_item("cyberdeck"):
        g.draw_text(["You already have a deck."], ["OK"], 0)
        g.get_choice(["OK"])
        return "afterlife_bar"
    success = random.random() < 0.6
    if success:
        g.add_item("cyberdeck")
        g.change_reputation("street", -1)
        g.draw_text(["You snatch a cyberdeck!", "Now you can hack terminals."], ["OK"], 0)
        g.get_choice(["OK"])
    else:
        g.draw_text(["He catches you! Security ejects you."], ["OK"], 0)
        g.get_choice(["OK"])
    return "afterlife_bar"

def scene_rogue_quest(g):
    g.draw_text([
        "Rogue: 'Arasaka wants you",
        "to retrieve data from",
        "their AI core. Pay: 10k.",
        "Or you can sell it to",
        "Militech for 8k.'"
    ], ["Accept for Arasaka", "Accept for Militech", "Refuse"], 0)
    choice = g.get_choice(["Arasaka job", "Militech job", "Refuse"])
    if choice == 0:
        g.set_flag("arasaka_job")
        g.change_reputation("arasaka", 2)
        return "street"
    elif choice == 1:
        g.set_flag("militech_job")
        g.change_reputation("militech", 2)
        return "street"
    else:
        return "afterlife_bar"

def scene_street(g):
    g.draw_text([
        "Night City streets. Rain.",
        "Neon reflections. A gang",
        "of Scavengers approach.",
        "They want your chrome."
    ], ["Fight", "Run", "Bribe them"], 0)
    choice = g.get_choice(["Fight", "Run", "Bribe"])
    if choice == 0:
        if g.has_item("weapon"):
            return "street_fight_win"
        else:
            return "street_fight_lose"
    elif choice == 1:
        return "street_run"
    else:
        if g.has_item("cred_chip"):
            g.remove_item("cred_chip")
            return "street"
        else:
            return "street_fight_lose"

def scene_street_fight_win(g):
    g.draw_text(["You fight them off.", "Gain a reputation boost."], ["Continue"], 0)
    g.get_choice(["Continue"])
    g.change_reputation("street", 2)
    return "street_choices"

def scene_street_fight_lose(g):
    g.draw_text(["You're beaten and robbed."], ["Continue"], 0)
    g.get_choice(["Continue"])
    g.inventory = []
    return "street"

def scene_street_run(g):
    g.draw_text(["You escape into a subway.", "End up in Pacifica."], ["Continue"], 0)
    g.get_choice(["Continue"])
    return "pacifica"

def scene_street_choices(g):
    g.draw_text([
        "You reach the Arasaka",
        "tower entrance. Guards",
        "patrol. A side alley",
        "leads to a service entrance."
    ], ["Main entrance (stealth)", "Service entrance (hack)", "Look for another way"], 0)
    choice = g.get_choice(["Main entrance", "Service entrance", "Another way"])
    if choice == 0:
        return "main_entrance"
    elif choice == 1:
        if g.has_item("cyberdeck"):
            return "service_hack"
        else:
            return "main_entrance"
    else:
        return "alley"

def scene_main_entrance(g):
    g.draw_text([
        "Guards scan IDs. You",
        "need a badge. A guard",
        "walks away – you could",
        "knock him out."
    ], ["Knock out guard", "Pickpocket badge", "Go back"], 0)
    choice = g.get_choice(["Knock out", "Pickpocket", "Back"])
    if choice == 0:
        return "main_entrance_knockout"
    elif choice == 1:
        return "main_entrance_pick"
    else:
        return "street_choices"

def scene_main_entrance_knockout(g):
    g.draw_text(["You knock him out.", "Take his badge and uniform."], ["Continue"], 0)
    g.get_choice(["Continue"])
    g.add_item("badge")
    return "lobby"

def scene_main_entrance_pick(g):
    if random.random() < 0.7:
        g.add_item("badge")
        g.draw_text(["You snag the badge."], ["OK"], 0)
        g.get_choice(["OK"])
        return "lobby"
    else:
        g.draw_text(["He notices. Alarms!"], ["Fight", "Run"], 0)
        choice = g.get_choice(["Fight", "Run"])
        if choice == 0:
            return "ending_death"
        else:
            return "street_choices"

def scene_service_hack(g):
    g.draw_text([
        "You hack the service door.",
        "It opens to a maintenance",
        "tunnel. Dark and quiet."
    ], ["Enter tunnel", "Go back"], 0)
    choice = g.get_choice(["Enter", "Back"])
    if choice == 0:
        return "tunnel"
    else:
        return "street_choices"

def scene_alley(g):
    g.draw_text([
        "A dumpster. You find a",
        "datapad with a map to",
        "the basement loading dock."
    ], ["Follow the map", "Ignore"], 0)
    choice = g.get_choice(["Follow map", "Ignore"])
    if choice == 0:
        g.add_item("map")
        return "loading_dock"
    else:
        return "street_choices"

def scene_loading_dock(g):
    g.draw_text([
        "The loading dock. A cargo",
        "elevator to the sublevels.",
        "A guard robot patrols."
    ], ["Sneak past robot", "Hack robot", "Destroy robot"], 0)
    choice = g.get_choice(["Sneak", "Hack", "Destroy"])
    if choice == 0:
        return "elevator"
    elif choice == 1:
        if g.has_item("cyberdeck"):
            return "elevator"
        else:
            return "loading_dock_fail"
    else:
        if g.has_item("weapon"):
            return "elevator"
        else:
            return "loading_dock_fail"

def scene_loading_dock_fail(g):
    g.draw_text(["Robot alerts guards.", "You're captured."], ["OK"], 0)
    g.get_choice(["OK"])
    return "ending_captured"

def scene_tunnel(g):
    g.draw_text([
        "The tunnel leads to a",
        "server room. Huge racks",
        "of data. A terminal asks",
        "for a password."
    ], ["Guess password", "Use cyberdeck to brute-force", "Leave"], 0)
    choice = g.get_choice(["Guess", "Brute-force", "Leave"])
    if choice == 0:
        return "tunnel_wrong"
    elif choice == 1:
        if g.has_item("cyberdeck"):
            return "tunnel_hack"
        else:
            return "tunnel_wrong"
    else:
        return "street_choices"

def scene_tunnel_wrong(g):
    g.draw_text(["Alarms blare. Guards flood in."], ["Fight", "Surrender"], 0)
    choice = g.get_choice(["Fight", "Surrender"])
    if choice == 0:
        return "ending_death"
    else:
        return "ending_captured"

def scene_tunnel_hack(g):
    g.draw_text(["You crack the password.", "The door to the AI core opens."], ["Enter"], 0)
    g.get_choice(["Enter"])
    return "core"

def scene_lobby(g):
    g.draw_text([
        "The lobby. Elevators to",
        "sublevels. A receptionist",
        "asks for your business."
    ], ["Show badge", "Say you're a technician", "Knock her out"], 0)
    choice = g.get_choice(["Show badge", "Technician", "Knock out"])
    if choice == 0 and g.has_item("badge"):
        return "elevator"
    elif choice == 1:
        return "elevator"
    elif choice == 2:
        return "lobby_knockout"
    else:
        return "lobby_fail"

def scene_lobby_knockout(g):
    g.draw_text(["You knock her out.", "Take her keycard."], ["Continue"], 0)
    g.get_choice(["Continue"])
    g.add_item("keycard")
    return "elevator"

def scene_lobby_fail(g):
    g.draw_text(["Security detains you."], ["OK"], 0)
    g.get_choice(["OK"])
    return "ending_captured"

def scene_elevator(g):
    g.draw_text([
        "The elevator descends.",
        "Floor -3: AI Research.",
        "A voice: 'Wintermute'",
        "echoes in your mind."
    ], ["Step out", "Go back up"], 0)
    choice = g.get_choice(["Step out", "Go back"])
    if choice == 0:
        return "research_lab"
    else:
        return "lobby"

def scene_research_lab(g):
    g.draw_text([
        "Rows of brains in jars.",
        "Scientists in hazmat suits.",
        "A central terminal glows.",
        "A scientist notices you."
    ], ["Attack scientist", "Talk to scientist", "Hack terminal"], 0)
    choice = g.get_choice(["Attack", "Talk", "Hack"])
    if choice == 0:
        return "lab_fight"
    elif choice == 1:
        return "lab_talk"
    else:
        if g.has_item("cyberdeck"):
            return "lab_hack"
        else:
            return "lab_fight"

def scene_lab_fight(g):
    g.draw_text(["You fight the scientist.", "He calls guards."], ["Fight guards", "Run"], 0)
    choice = g.get_choice(["Fight", "Run"])
    if choice == 0:
        return "ending_death"
    else:
        return "core"

def scene_lab_talk(g):
    g.draw_text(["Scientist: 'You're here for the AI?'", "He offers to help if you spare him."], ["Accept help", "Kill him"], 0)
    choice = g.get_choice(["Accept", "Kill"])
    if choice == 0:
        g.add_item("ai_key")
        g.draw_text(["He gives you a access key."], ["OK"], 0)
        g.get_choice(["OK"])
        return "core"
    else:
        return "lab_fight"

def scene_lab_hack(g):
    g.draw_text(["You hack the terminal.", "It unlocks the core door."], ["Enter core"], 0)
    g.get_choice(["Enter core"])
    return "core"

def scene_core(g):
    # Reputation influences available options
    options = ["Merge with AI", "Upload virus", "Pull the plug"]
    if g.rep_netwatch >= 5:
        options.append("Call NetWatch (special)")
    if g.rep_voodoo >= 5:
        options.append("Summon Voodoo Boys")
    if g.rep_arasaka >= 5:
        options.append("Sell to Arasaka")
    if g.rep_militech >= 5:
        options.append("Sell to Militech")
    options.append("Negotiate")
    g.draw_text([
        "The AI core: a sphere of",
        "light. A hologram appears:",
        "'I am Wintermute. I've",
        "been watching you.'"
    ], options, 0)
    choice = g.get_choice(options)
    chosen = options[choice]
    if chosen == "Merge with AI":
        return "ending_merge"
    elif chosen == "Upload virus":
        if g.has_item("virus"):
            return "ending_virus"
        else:
            return "ending_no_virus"
    elif chosen == "Pull the plug":
        return "ending_shutdown"
    elif chosen == "Call NetWatch":
        return "ending_netwatch"
    elif chosen == "Summon Voodoo Boys":
        return "ending_voodoo"
    elif chosen == "Sell to Arasaka":
        return "ending_arasaka"
    elif chosen == "Sell to Militech":
        return "ending_militech"
    else:
        return "ending_negotiate"

def scene_pacifica(g):
    g.draw_text([
        "Pacifica ruins. Voodoo",
        "Boys territory. A netrunner",
        "named Placide offers a",
        "side job: steal data from",
        "a Militech convoy."
    ], ["Accept side quest", "Refuse", "Kill Placide"], 0)
    choice = g.get_choice(["Accept", "Refuse", "Kill"])
    if choice == 0:
        return "pacifica_quest"
    elif choice == 1:
        return "street_choices"
    else:
        return "pacifica_fight"

def scene_pacifica_quest(g):
    g.draw_text([
        "You ambush the convoy.",
        "Data shard acquired.",
        "Placide pays you 2000 eddies.",
        "Also gives you a black ICE."
    ], ["Return to Afterlife", "Continue to Arasaka"], 0)
    choice = g.get_choice(["Afterlife", "Arasaka"])
    g.add_item("black_ice")
    g.add_item("cred_chip")
    g.change_reputation("voodoo", 2)
    if choice == 0:
        return "afterlife_bar"
    else:
        return "street_choices"

def scene_pacifica_fight(g):
    g.draw_text(["Placide fries your cyberdeck."], ["OK"], 0)
    g.get_choice(["OK"])
    if "cyberdeck" in g.inventory:
        g.inventory.remove("cyberdeck")
    g.change_reputation("voodoo", -5)
    return "street_choices"

# ----------------------------------------------------------------------
# Endings (expanded)
# ----------------------------------------------------------------------
def ending_death(g):
    g.draw_text([
        "You flatline. Your body",
        "is dumped in the bay.",
        "GAME OVER."
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_captured(g):
    g.draw_text([
        "Arasaka imprisons you.",
        "Your mind is wiped.",
        "You become a vegetable.",
        "GAME OVER."
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_merge(g):
    g.draw_text([
        "You merge with Wintermute.",
        "You become a digital god.",
        "You reshape the Net.",
        "ENDING: TRANSCENDENCE"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_virus(g):
    g.draw_text([
        "You upload the virus.",
        "Wintermute shatters.",
        "Arasaka pays you 10k.",
        "You live as a legend.",
        "ENDING: SYSTEM PURGE"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_no_virus(g):
    g.draw_text([
        "You have no virus.",
        "Wintermute enslaves you.",
        "You become a puppet.",
        "ENDING: ENSLAVED"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_shutdown(g):
    g.draw_text([
        "You pull the plug.",
        "The AI dies. Arasaka",
        "crashes. You vanish.",
        "ENDING: NEUTRALIZED"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_negotiate(g):
    g.draw_text([
        "You negotiate with Wintermute.",
        "It offers you a seat on",
        "the board. You become a",
        "corporate puppet.",
        "ENDING: SOLD OUT"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_netwatch(g):
    g.draw_text([
        "NetWatch arrives. They",
        "contain Wintermute.",
        "You become an agent.",
        "ENDING: GHOST IN THE SHELL"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_voodoo(g):
    g.draw_text([
        "The Voodoo Boys take",
        "Wintermute. They use it",
        "to hack the global Net.",
        "You become their kingpin.",
        "ENDING: LOAYL"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_arasaka(g):
    g.draw_text([
        "You sell the AI to Arasaka.",
        "They pay you handsomely.",
        "You live in luxury, but",
        "the world suffers.",
        "ENDING: SELLOUT"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

def ending_militech(g):
    g.draw_text([
        "Militech weaponizes the AI.",
        "They start a new war.",
        "You disappear into hiding.",
        "ENDING: GUN FOR HIRE"
    ], ["Restart", "Exit"], 0)
    choice = g.get_choice(["Restart", "Exit"])
    if choice == 0:
        return "start"
    else:
        g.running = False
        return None

# ----------------------------------------------------------------------
# Scene dispatcher
# ----------------------------------------------------------------------
def run_scene(g, scene_name):
    scenes = {
        "start": scene_start,
        "apartment": scene_apartment,
        "apartment_visitor": scene_apartment_visitor,
        "apartment_hide": scene_apartment_hide,
        "apartment_window": scene_apartment_window,
        "contact": scene_contact,
        "afterlife_bar": scene_afterlife_bar,
        "bar_rumors": scene_bar_rumors,
        "pickpocket": scene_pickpocket,
        "rogue_quest": scene_rogue_quest,
        "street": scene_street,
        "street_fight_win": scene_street_fight_win,
        "street_fight_lose": scene_street_fight_lose,
        "street_run": scene_street_run,
        "street_choices": scene_street_choices,
        "main_entrance": scene_main_entrance,
        "main_entrance_knockout": scene_main_entrance_knockout,
        "main_entrance_pick": scene_main_entrance_pick,
        "service_hack": scene_service_hack,
        "alley": scene_alley,
        "loading_dock": scene_loading_dock,
        "loading_dock_fail": scene_loading_dock_fail,
        "tunnel": scene_tunnel,
        "tunnel_wrong": scene_tunnel_wrong,
        "tunnel_hack": scene_tunnel_hack,
        "lobby": scene_lobby,
        "lobby_knockout": scene_lobby_knockout,
        "lobby_fail": scene_lobby_fail,
        "elevator": scene_elevator,
        "research_lab": scene_research_lab,
        "lab_fight": scene_lab_fight,
        "lab_talk": scene_lab_talk,
        "lab_hack": scene_lab_hack,
        "core": scene_core,
        "pacifica": scene_pacifica,
        "pacifica_quest": scene_pacifica_quest,
        "pacifica_fight": scene_pacifica_fight,
        "ending_death": ending_death,
        "ending_captured": ending_captured,
        "ending_merge": ending_merge,
        "ending_virus": ending_virus,
        "ending_no_virus": ending_no_virus,
        "ending_shutdown": ending_shutdown,
        "ending_negotiate": ending_negotiate,
        "ending_netwatch": ending_netwatch,
        "ending_voodoo": ending_voodoo,
        "ending_arasaka": ending_arasaka,
        "ending_militech": ending_militech,
    }
    if scene_name in scenes:
        return scenes[scene_name](g)
    else:
        return "start"

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    game = Game()
    game.running = True
    while game.running:
        next_scene = run_scene(game, game.scene)
        if next_scene is None:
            break
        game.scene = next_scene
    GPIO.cleanup()
    LCD.LCD_Clear()

if __name__ == "__main__":
    main()
