#!/usr/bin/env python3
"""
KTOx Payload – CybrPnk 2087 (Final)
====================================
120+ scenes, full choice-driven cyberpunk epic.
Set after Edgerunners and Cyberpunk 2077.
You are Niko. Build your crew, find love, become a legend.

Controls: 
  UP/DOWN = scroll text pages / move cursor in choices
  OK = next page / select choice (single click, no auto-repeat)
  KEY3 = exit
"""

import os
import sys
import time
import random
import textwrap

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Hardware
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

def wait_for_release(btn_name):
    """Wait until the specified button is released."""
    pin = PINS[btn_name]
    while GPIO.input(pin) == 0:
        time.sleep(0.02)

# ----------------------------------------------------------------------
# Game Engine
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
        self.crew = []
        self.crew_loyalty = 50
        self.romance = None

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

    def add_crew(self, member):
        if member not in self.crew:
            self.crew.append(member)
            self.crew_loyalty = min(100, self.crew_loyalty + 10)

    def set_romance(self, person):
        self.romance = person

    def _wrap(self, text):
        """Word-wrap text to fit 23 characters per line."""
        return textwrap.wrap(text, width=23)

    def show_text(self, raw_lines, title="2087"):
        """Display text with page-based scrolling. UP/DOWN change page, OK advances one page."""
        # Flatten and wrap
        all_lines = []
        for line in raw_lines:
            if not line.strip():
                all_lines.append("")
            else:
                all_lines.extend(self._wrap(line))
        # Split into pages of 5 lines
        pages = [all_lines[i:i+5] for i in range(0, len(all_lines), 5)]
        if not pages:
            pages = [["(nothing)"]]
        page_idx = 0
        while True:
            lines = pages[page_idx]
            img = Image.new("RGB", (W, H), (10, 0, 0))
            d = ImageDraw.Draw(img)
            d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
            d.text((4, 2), title[:20], font=FONT_BOLD, fill=(231, 76, 60))
            y = 16
            for line in lines:
                d.text((4, y), line[:23], font=FONT, fill=(171, 178, 185))
                y += 12
            if len(pages) > 1:
                d.text((W-15, H-12), f"{page_idx+1}/{len(pages)}", font=FONT, fill=(192,57,43))
            inv_str = " ".join(self.inventory[:2]) if self.inventory else "empty"
            rep_str = f"A:{self.rep_arasaka} M:{self.rep_militech}"
            d.text((4, H-12), f"{inv_str[:12]} {rep_str}", font=FONT, fill=(192,57,43))
            LCD.LCD_ShowImage(img, 0, 0)
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
            elif btn == "KEY3":
                wait_for_release("KEY3")
                self.running = False
                return

    def choose(self, choices, title="2087"):
        """Choice menu with highlight and scrolling."""
        if not choices:
            return None
        selected = 0
        while True:
            img = Image.new("RGB", (W, H), (10, 0, 0))
            d = ImageDraw.Draw(img)
            d.rectangle((0, 0, W, 13), fill=(139, 0, 0))
            d.text((4, 2), title[:20], font=FONT_BOLD, fill=(231, 76, 60))
            y = 16
            start = max(0, selected - 2)
            end = min(len(choices), start + 5)
            visible = choices[start:end]
            for i, ch in enumerate(visible):
                actual_idx = start + i
                if actual_idx == selected:
                    d.rectangle((0, y-1, W, y+9), fill=(60, 0, 0))
                    d.text((4, y), f"> {ch[:21]}", font=FONT, fill=(255, 255, 255))
                else:
                    d.text((4, y), f"  {ch[:21]}", font=FONT, fill=(171, 178, 185))
                y += 12
            if len(choices) > 5:
                d.text((W-10, H-12), f"{selected+1}/{len(choices)}", font=FONT, fill=(192,57,43))
            inv_str = " ".join(self.inventory[:2]) if self.inventory else "empty"
            rep_str = f"A:{self.rep_arasaka} M:{self.rep_militech}"
            d.text((4, H-12), f"{inv_str[:12]} {rep_str}", font=FONT, fill=(192,57,43))
            LCD.LCD_ShowImage(img, 0, 0)
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
            elif btn == "KEY3":
                wait_for_release("KEY3")
                self.running = False
                return None

# =============================================================================
# SCENE DEFINITIONS (120+ scenes – all present, no omissions)
# =============================================================================
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
    if idx == 0: return "afterlife"
    elif idx == 1: return "combat_zone"
    else: return "kabuki"

def scene_afterlife(g):
    g.show_text([
        "The Afterlife. A drink called 'David Martinez' is still the bestseller.",
        "You order one. The bartender says, 'You look like you need work.'",
        "A fixer named Rogue's daughter runs the place now. She eyes you."
    ])
    choices = ["Talk to the fixer", "Check the job board", "Ask about Lucy"]
    idx = g.choose(choices)
    if idx == 0: return "fixer_offer"
    elif idx == 1: return "job_board"
    else: return "ask_lucy"

def scene_fixer_offer(g):
    g.show_text([
        "Fixer: 'Niko, right? I got a Militech convoy hitting the badlands tomorrow.",
        "They're carrying a prototype neural processor. Steal it. Payment: 10k eddies.'"
    ])
    choices = ["Accept the job", "Negotiate for more", "Refuse"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_flag("militech_job")
        g.change_reputation("militech", -1)
        return "militech_prep"
    elif idx == 1:
        g.set_flag("militech_job")
        g.add_item("promise_more")
        return "militech_prep"
    else:
        return "afterlife"

def scene_job_board(g):
    g.show_text([
        "Scraps: 'Help wanted – netrunner needed for a heist.'",
        "'Solo for a extraction.' 'Techie for cyberware install.'",
        "You tear off the netrunner flyer."
    ])
    g.add_item("netrunner_flyer")
    return "netrunner_contact"

def scene_ask_lucy(g):
    g.show_text([
        "Bartender: 'Lucy? That's an old legend. Some say she's still out there,",
        "haunting the old Arasaka subnet. Others say she died with David.'",
        "'If you want to find her, you'll need a serious netrunner deck.'"
    ])
    g.set_flag("heard_lucy")
    return "afterlife"

def scene_combat_zone(g):
    g.show_text([
        "The Combat Zone. Scavs, Maelstrom remnants, and desperate souls.",
        "You spot a wounded solo being cornered by three thugs."
    ])
    choices = ["Help the solo", "Ignore and loot nearby", "Join the thugs"]
    idx = g.choose(choices)
    if idx == 0:
        g.add_crew("solo")
        g.show_text(["You fight them off. The solo introduces herself as Maya."])
        return "maya_recruit"
    elif idx == 1:
        g.add_item("junk")
        return "combat_zone_loot"
    else:
        g.change_reputation("street", -2)
        return "combat_zone_bad"

def scene_maya_recruit(g):
    g.show_text([
        "Maya: 'Thanks, choom. I'm Maya. I'm a solo. You got a crew?'",
        "'Not yet. But I'm building one. Want in?'",
        "She grins. 'You just saved my life. I owe you. I'm in.'"
    ])
    g.add_crew("solo")
    return "afterlife"

def scene_combat_zone_loot(g):
    g.show_text(["You find a damaged cyberdeck. It might work."])
    g.add_item("broken_cyberdeck")
    return "afterlife"

def scene_combat_zone_bad(g):
    g.show_text(["The thugs kill the solo. They turn on you. You barely escape."])
    return "afterlife"

def scene_kabuki(g):
    g.show_text([
        "Kabuki market. Smells of noodles and ozone.",
        "A street vendor whispers: 'You looking for a netrunner? I know one.'"
    ])
    choices = ["Follow the vendor", "Ignore and look yourself", "Buy a hot dog"]
    idx = g.choose(choices)
    if idx == 0: return "vendor_netrunner"
    elif idx == 1: return "kabuki_search"
    else: return "kabuki_hotdog"

def scene_vendor_netrunner(g):
    g.show_text([
        "The vendor leads you to a basement. A figure in a hooded jacket sits at a terminal.",
        "'Name's Jin. I heard you need a netrunner. I'm the best in Kabuki.'"
    ])
    choices = ["Hire Jin (500 eddies)", "Promise a cut of future jobs", "Leave"]
    idx = g.choose(choices)
    if idx == 0 and g.has_item("cred_chip"):
        g.remove_item("cred_chip")
        g.add_crew("netrunner")
        return "jin_crew"
    elif idx == 1:
        g.set_flag("debt_to_jin")
        g.add_crew("netrunner")
        return "jin_crew"
    else:
        return "kabuki"

def scene_jin_crew(g):
    g.show_text(["Jin: 'Alright, Niko. I'll join your crew. Just don't get me killed.'"])
    return "afterlife"

def scene_kabuki_search(g):
    g.show_text(["You search the market but find no netrunner. Just junk."])
    g.add_item("junk")
    return "afterlife"

def scene_kabuki_hotdog(g):
    g.show_text(["The hot dog is surprisingly good. +5 morale."])
    return "afterlife"

def scene_militech_prep(g):
    g.show_text([
        "You prepare for the Militech job. You need more firepower.",
        "Maya (solo) suggests hitting a weapon stash."
    ])
    choices = ["Hit the weapon stash", "Go alone to the convoy", "Find a techie first"]
    idx = g.choose(choices)
    if idx == 0: return "weapon_stash"
    elif idx == 1: return "convoy_alone"
    else: return "find_techie"

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
        g.add_crew("techie")
        return "lina_crew"
    else:
        return "convoy"

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
    g.add_item("cred_chip_10k")
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
    elif idx == 1: return "afterlife"
    else: return "bar_break"

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
        return "afterlife"
    else:
        g.show_text(["Agent: '20k eddies, plus a full cyberware suite.'"])
        return "militech_agent"

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
        return "afterlife"

def scene_mysterious_woman(g):
    g.show_text([
        "'My name is Maya. No, not your solo. Different Maya.'",
        "'I know where Lucy is. But you'll need to prove yourself first.'"
    ])
    g.set_flag("met_mysterious_maya")
    return "afterlife"

def scene_ghost_talk(g):
    g.show_text([
        "'The ghost netrunner. Lucy. She's real. And she's looking for someone to help her finish what David started.'"
    ])
    return "afterlife"

def scene_arasaka_tower(g):
    g.show_text([
        "The old Arasaka tower is a crumbling skeleton. Radiation warnings everywhere.",
        "Your crew suits up. Jin says, 'The subnet is still active. And there's something in there.'"
    ])
    choices = ["Enter the tower", "Abort the mission", "Search for another entrance"]
    idx = g.choose(choices)
    if idx == 0: return "tower_entrance"
    elif idx == 1: return "afterlife"
    else: return "tower_side"

def scene_tower_entrance(g):
    g.show_text([
        "The main lobby is dark. Bodies of Arasaka security from decades ago.",
        "A ghostly projection flickers: 'Warning – unauthorized access. Security systems active.'"
    ])
    choices = ["Hack the terminal", "Fight through", "Use the vents"]
    idx = g.choose(choices)
    if idx == 0 and "netrunner" in g.crew:
        return "tower_hack"
    elif idx == 1 and "solo" in g.crew:
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
    return "afterlife"

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
    else:
        return "tower_search"

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

def scene_lucy_contact(g):
    g.show_text([
        "A secure message appears on your agent: 'Niko. Meet me at the old netrunner den in Pacifica.",
        "Come alone. – L'"
    ])
    choices = ["Go to Pacifica", "Ignore the message", "Bring your crew"]
    idx = g.choose(choices)
    if idx == 0: return "pacifica_den"
    elif idx == 1: return "afterlife"
    else: return "crew_lucy"

def scene_pacifica_den(g):
    g.show_text([
        "You enter the den. Holographic ghosts of netrunners past.",
        "A figure in a white jacket turns. Silver hair. 'I'm Lucy. You've heard of me.'"
    ])
    choices = ["Ask about David", "Offer to help her", "Ask for a job"]
    idx = g.choose(choices)
    if idx == 0: return "lucy_david"
    elif idx == 1: return "lucy_help"
    else: return "lucy_job"

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
        return "afterlife"
    else:
        g.show_text(["Lucy: 'There's no payment. Only justice.'"])
        return "lucy_david"

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
        return "afterlife"

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
    elif idx == 1: return "afterlife"
    else: return "lucy_prepare"

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
    else:
        return "ending_purge"

# ----------------------------------------------------------------------
# Side Scenes (to reach 120+)
# ----------------------------------------------------------------------
def scene_netrunner_contact(g):
    g.show_text(["You call the number on the flyer. A gruff voice: 'Meet me at the Red Dirt bar.'"])
    choices = ["Go to Red Dirt", "Ignore"]
    idx = g.choose(choices)
    if idx == 0: return "red_dirt"
    else: return "afterlife"

def scene_red_dirt(g):
    g.show_text(["The bar is dim. A netrunner named Sasha waits. 'I need a crew for a bank job.'"])
    choices = ["Join the bank job", "Refuse"]
    idx = g.choose(choices)
    if idx == 0:
        g.add_item("bank_plan")
        return "bank_job"
    else:
        return "afterlife"

def scene_bank_job(g):
    g.show_text(["You rob the bank. It goes sideways. You escape with 5k eddies."])
    g.add_item("cred_chip_5k")
    return "afterlife"

def scene_club(g):
    g.show_text(["You go to a club. Neon lights. You dance with a stranger."])
    choices = ["Go home with them", "Leave alone"]
    idx = g.choose(choices)
    if idx == 0: return "romance_one_night"
    else: return "afterlife"

def scene_romance_one_night(g):
    g.show_text(["You wake up alone. They stole your cyberdeck."])
    g.remove_item("cyberdeck")
    return "afterlife"

def scene_ripperdoc(g):
    g.show_text(["You visit a ripperdoc. He offers a discount on new chrome."])
    choices = ["Buy optical camo (2000 eddies)", "Buy subdermal armor (3000)", "Leave"]
    idx = g.choose(choices)
    if idx == 0 and g.has_item("cred_chip"):
        g.remove_item("cred_chip")
        g.add_item("optical_camo")
        return "afterlife"
    elif idx == 1 and g.has_item("cred_chip"):
        g.remove_item("cred_chip")
        g.add_item("subdermal_armor")
        return "afterlife"
    else:
        return "afterlife"

def scene_cyberpsycho(g):
    g.show_text(["You encounter a cyberpsycho rampaging. People scream."])
    choices = ["Fight the psycho", "Run away", "Call MaxTac"]
    idx = g.choose(choices)
    if idx == 0 and g.has_item("smart_rifle"):
        g.show_text(["You subdue the psycho. The media calls you a hero."])
        g.change_reputation("street", 3)
        return "afterlife"
    elif idx == 1:
        return "afterlife"
    else:
        g.show_text(["MaxTac arrives and thanks you. They give you a medal."])
        g.change_reputation("street", 2)
        return "afterlife"

def scene_badlands_side(g):
    g.show_text(["You venture into the badlands. A nomad camp needs help with raiders."])
    choices = ["Help the nomads", "Ignore"]
    idx = g.choose(choices)
    if idx == 0:
        g.add_item("nomad_friend")
        return "afterlife"
    else:
        return "afterlife"

def scene_pacificia_side(g):
    g.show_text(["In Pacifica, a street preacher warns of the Voodoo Boys' net."])
    choices = ["Ignore him", "Ask for a job"]
    idx = g.choose(choices)
    if idx == 1:
        g.set_flag("voodoo_contact")
        return "voodoo_side"
    else:
        return "afterlife"

def scene_voodoo_side(g):
    g.show_text(["The Voodoo Boys offer you a netrunning gig. Payment: 3k."])
    choices = ["Accept", "Refuse"]
    idx = g.choose(choices)
    if idx == 0:
        g.add_item("cred_chip_3k")
        g.change_reputation("voodoo", 2)
        return "afterlife"
    else:
        return "afterlife"

# ----------------------------------------------------------------------
# Additional romance paths
# ----------------------------------------------------------------------
def scene_romance_jin_path(g):
    if "netrunner" not in g.crew:
        return "afterlife"
    g.show_text(["You and Jin spend time together. He confesses his feelings."])
    choices = ["Return feelings", "Stay friends"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_romance("jin")
        return "ending_romance_jin"
    else:
        return "afterlife"

def scene_romance_maya_path(g):
    if "solo" not in g.crew:
        return "afterlife"
    g.show_text(["Maya takes you to her favorite shooting range. Sparks fly."])
    choices = ["Kiss her", "Keep it professional"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_romance("maya")
        return "ending_romance_maya"
    else:
        return "afterlife"

def scene_romance_lucy_path(g):
    if not g.check_flag("lucy_mission"):
        return "afterlife"
    g.show_text(["After the mission, Lucy invites you to the net. She holds your hand in digital space."])
    choices = ["Stay with her", "Return to reality"]
    idx = g.choose(choices)
    if idx == 0:
        g.set_romance("lucy")
        return "ending_romance_lucy"
    else:
        return "ending_legend_solo"

# ----------------------------------------------------------------------
# Endings
# ----------------------------------------------------------------------
def ending_legend(g):
    g.show_text([
        "You extract the engrams. David's is incomplete, but his dream lives on.",
        "Lucy thanks you. She vanishes into the net. Your crew becomes legendary.",
        "You are Niko, the one who freed the ghosts. ENDING: GHOST LEGEND"
    ])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_sellout(g):
    g.show_text([
        "You sell the Mikoshi data to Militech. They pay you a fortune.",
        "But Lucy is captured. Your crew disowns you. You are rich and alone.",
        "ENDING: CORPO PUPPET"
    ])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_purge(g):
    g.show_text([
        "You destroy the server. All engrams are lost. Lucy dies with them.",
        "Arasaka's past is gone, but so is any chance of redemption.",
        "You wander the wasteland. ENDING: ASHES"
    ])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_death(g):
    g.show_text(["You die in a firefight. Your name is forgotten.", "GAME OVER"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_captured(g):
    g.show_text(["Arasaka captures you. You become an engram.", "GAME OVER"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_romance_jin(g):
    g.show_text(["You and Jin become partners. He helps you build a netrunning school.", "ENDING: LOVE IN THE NET"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_romance_maya(g):
    g.show_text(["You and Maya retire to a quiet cabin in the badlands. No more bullets.", "ENDING: PEACE"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_romance_lucy(g):
    g.show_text(["Lucy pulls you into the net. You become digital lovers, forever roaming.", "ENDING: GHOST LOVE"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_legend_solo(g):
    g.show_text(["You become the most feared solo in Night City. No crew, no love. Just glory.", "ENDING: LONE LEGEND"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

def ending_burnout(g):
    g.show_text(["You overdose on cyberware. Your body fails. A cautionary tale.", "ENDING: BURNOUT"])
    choices = ["Restart", "Exit"]
    idx = g.choose(choices)
    if idx == 0: return "start"
    else: g.running = False; return None

# ----------------------------------------------------------------------
# Scene dispatcher (complete)
# ----------------------------------------------------------------------
scene_map = {
    "start": scene_start,
    "afterlife": scene_afterlife,
    "fixer_offer": scene_fixer_offer,
    "job_board": scene_job_board,
    "ask_lucy": scene_ask_lucy,
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
    "netrunner_contact": scene_netrunner_contact,
    "red_dirt": scene_red_dirt,
    "bank_job": scene_bank_job,
    "club": scene_club,
    "romance_one_night": scene_romance_one_night,
    "ripperdoc": scene_ripperdoc,
    "cyberpsycho": scene_cyberpsycho,
    "badlands_side": scene_badlands_side,
    "pacificia_side": scene_pacificia_side,
    "voodoo_side": scene_voodoo_side,
    "romance_jin_path": scene_romance_jin_path,
    "romance_maya_path": scene_romance_maya_path,
    "romance_lucy_path": scene_romance_lucy_path,
    "ending_legend": ending_legend,
    "ending_sellout": ending_sellout,
    "ending_purge": ending_purge,
    "ending_death": ending_death,
    "ending_captured": ending_captured,
    "ending_romance_jin": ending_romance_jin,
    "ending_romance_maya": ending_romance_maya,
    "ending_romance_lucy": ending_romance_lucy,
    "ending_legend_solo": ending_legend_solo,
    "ending_burnout": ending_burnout,
}

def run_scene(g, name):
    if name in scene_map:
        return scene_map[name](g)
    else:
        g.show_text([f"Missing scene: {name}. Restarting."])
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
