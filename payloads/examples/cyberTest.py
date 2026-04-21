# #!/usr/bin/env python3
“””
KTOx Payload – CybrPnk2087 v2.0
author: wickednull

Full cyberpunk RPG — 10-act story, overhauled turn-based combat,
crew system, quickhacks, reputation, romance, multiple endings.

# Controls:
UP/DOWN   = scroll / move cursor
OK        = select / next page
KEY1      = inventory
KEY2      = return to Afterlife hub
KEY3      = exit

“””

import os, sys, time, random, textwrap, json

import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────────────

# Paths & Hardware

# ─────────────────────────────────────────────────────────────────────

LOOT_DIR  = “/root/KTOx/loot”
os.makedirs(LOOT_DIR, exist_ok=True)
SAVE_FILE = os.path.join(LOOT_DIR, “cyberpunk_save.json”)

PINS = {“UP”:6,“DOWN”:19,“LEFT”:5,“RIGHT”:26,“OK”:13,“KEY1”:21,“KEY2”:20,“KEY3”:16}
GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
W, H = 128, 128

def font(size=9):
try:    return ImageFont.truetype(”/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf”, size)
except: return ImageFont.load_default()

FONT      = font(9)
FONT_BOLD = font(10)
IMAGE     = Image.new(“RGB”, (W, H), (10, 0, 0))
DRAW      = ImageDraw.Draw(IMAGE)

# ─────────────────────────────────────────────────────────────────────

# Button helpers

# ─────────────────────────────────────────────────────────────────────

def wait_btn(timeout=0.1):
start = time.time()
while time.time() - start < timeout:
for name, pin in PINS.items():
if GPIO.input(pin) == 0:
time.sleep(0.05)
return name
time.sleep(0.02)
return None

def wait_for_release(btn):
pin = PINS[btn]
while GPIO.input(pin) == 0:
time.sleep(0.02)

# ─────────────────────────────────────────────────────────────────────

# Low-level UI

# ─────────────────────────────────────────────────────────────────────

def wrap_text(text, width=18):
return textwrap.wrap(text, width=width)

def display_text(lines, title=None):
DRAW.rectangle((0,0,W,H), fill=(10,0,0))
y = 2
if title:
DRAW.text((2,y), title.upper(), font=FONT_BOLD, fill=“CYAN”)
y += 12
DRAW.line((0,y-2,W,y-2), fill=“WHITE”)
for line in lines[:8]:
DRAW.text((2,y), line, font=FONT, fill=“WHITE”)
y += 11
LCD.LCD_ShowImage(IMAGE, 0, 0)

def menu_choice(options, title=“SELECT”):
idx = 0
while True:
lines = [title, “-”*18]
for i, opt in enumerate(options):
lines.append(f”{’> ’ if i==idx else ’  ’}{opt}”)
display_text(lines)
btn = wait_btn()
if   btn == “UP”:    idx = (idx-1) % len(options)
elif btn == “DOWN”:  idx = (idx+1) % len(options)
elif btn == “OK”:    wait_for_release(“OK”);   return idx
elif btn == “KEY2”:  return -1
elif btn == “KEY3”:  sys.exit(0)

def show_message(text, wait=True):
pages = []
for line in text.split(”\n”):
pages.extend(wrap_text(line))
page = 0
while page < len(pages):
display_text(pages[page:page+8], title=“INFO”)
btn = wait_btn()
if   btn == “OK”:   page += 8
elif btn == “KEY2”: return “hub”
elif btn == “KEY3”: sys.exit(0)
if wait:
wait_btn(timeout=2)

# ─────────────────────────────────────────────────────────────────────

# COMBAT SYSTEM  (v2 – crits, flee, morale, loot drops, boss moves)

# ─────────────────────────────────────────────────────────────────────

class Combatant:
def **init**(self, name, hp, attack, speed=10, defense=0,
abilities=None, boss=False, loot=None):
self.name       = name
self.max_hp     = hp
self.hp         = hp
self.attack     = attack
self.speed      = speed
self.defense    = defense
self.status     = None     # “Burn” | “Glitch” | “Stun”
self.status_turns = 0
self.abilities  = abilities or []   # list of (name, multiplier)
self.boss       = boss
self.loot       = loot or []        # list of item strings to award on death
self.morale     = 100               # 0-100; enemies flee below 15

```
def is_alive(self):
    return self.hp > 0

def take_damage(self, dmg, armor_pierce=False):
    reduction = 0 if armor_pierce else self.defense // 2
    actual    = max(1, dmg - reduction)
    self.hp   = max(0, self.hp - actual)
    return actual

def apply_status(self, status, turns):
    # Bosses resist status (50% chance)
    if self.boss and random.random() < 0.5:
        return False
    self.status       = status
    self.status_turns = turns
    return True

def end_turn_effects(self):
    """Apply DoT and decrement status counters. Returns log string."""
    if not self.status:
        return ""
    msg = ""
    if self.status == "Burn":
        dmg = random.randint(4, 8)
        self.hp = max(0, self.hp - dmg)
        msg = f"{self.name} burns -{dmg}HP!"
    elif self.status == "Stun":
        msg = f"{self.name} is stunned!"
    self.status_turns -= 1
    if self.status_turns <= 0:
        self.status = None
    return msg

def choose_ability(self):
    """Enemy uses ability if available (random 30% chance)."""
    if self.abilities and random.random() < 0.30:
        return random.choice(self.abilities)
    return None
```

def _build_player_combatants(game):
“”“Build Niko + crew as Combatant list.”””
weapon_bonus = 5 if game.equipped_weapon else 0
niko = Combatant(“Niko”, game.health, 15 + game.level + weapon_bonus, 12, defense=game.level)
crew_list = [niko]
stats = {
“Maya”: (70, 18, 14, 2, [(“Burst Fire”, 1.8)]),
“Jin”:  (60, 12, 18, 1, [(“ICE Spike”,  1.5)]),
“Lina”: (55, 10, 12, 3, [(“EMP Blast”,  1.0)]),  # EMP = 0 damage but stuns
}
for m in game.crew:
if m in stats:
hp, atk, spd, dfn, ab = stats[m]
crew_list.append(Combatant(m, hp, atk, spd, dfn, abilities=ab))
return crew_list

def _show_combat_hud(fighter, enemies, player_crew, game):
DRAW.rectangle((0,0,W,H), fill=(5,0,10))
DRAW.rectangle((0,0,W,13), fill=(80,0,0))
DRAW.text((4,2), “** COMBAT **”, font=FONT_BOLD, fill=(255,80,0))
y = 16
DRAW.text((4,y), f”Turn: {fighter.name}”, font=FONT, fill=(255,255,0)); y+=12
DRAW.line((0,y,W,y), fill=(40,0,40)); y+=3
DRAW.text((4,y), “ALLIES”, font=FONT, fill=(0,200,200)); y+=11
for p in player_crew:
bar_w = int(20 * p.hp / max(1, p.max_hp))
col   = (0,200,0) if p.hp > p.max_hp//2 else (200,100,0) if p.hp > p.max_hp//4 else (200,0,0)
DRAW.text((4,y), f”{p.name[:8]}”, font=FONT, fill=col)
DRAW.rectangle((60,y,80,y+7), fill=(40,0,0))
DRAW.rectangle((60,y,60+bar_w,y+7), fill=col)
DRAW.text((82,y), f”{p.hp}”, font=FONT, fill=(200,200,200))
if p.status:
DRAW.text((108,y), p.status[:3], font=FONT, fill=(255,200,0))
y += 11
DRAW.line((0,y,W,y), fill=(40,0,40)); y+=3
DRAW.text((4,y), “ENEMIES”, font=FONT, fill=(255,60,60)); y+=11
for e in [en for en in enemies if en.is_alive()]:
bar_w = int(20 * e.hp / max(1, e.max_hp))
DRAW.text((4,y), f”{e.name[:8]}”, font=FONT, fill=(200,50,50))
DRAW.rectangle((60,y,80,y+7), fill=(40,0,0))
DRAW.rectangle((60,y,60+bar_w,y+7), fill=(180,0,0))
DRAW.text((82,y), f”{e.hp}”, font=FONT, fill=(200,200,200))
if e.status:
DRAW.text((108,y), e.status[:3], font=FONT, fill=(255,200,0))
y += 11
DRAW.text((4,H-12), f”E:{game.energy} Lv:{game.level}”, font=FONT, fill=(100,100,100))
LCD.LCD_ShowImage(IMAGE, 0, 0)
time.sleep(0.3)

HACK_MENU = [
(“Short Circuit”, 20, “damage”,  20, False),
(“Weapon Glitch”,  30, “Glitch”,   2, False),
(“Overheat”,       40, “Burn”,     3, False),
(“Ping”,           15, “reveal”,   0, False),
(“System Shock”,   50, “Stun”,     1, True),   # armor pierce
]

def combat_encounter(player_crew, enemies_data, game,
flee_allowed=True, boss_music=False):
“””
Full combat loop.
enemies_data: list of dicts or tuples:
tuple  -> (name, hp, atk, spd=10, defense=0)
dict   -> {name, hp, attack, speed, defense, abilities, boss, loot}
Returns: True (victory) | False (defeat) | “hub” (fled/cancelled)
“””
def _make_enemy(e):
if isinstance(e, dict):
return Combatant(
e[“name”], e[“hp”], e[“attack”],
e.get(“speed”, 10), e.get(“defense”, 0),
e.get(“abilities”, []),
e.get(“boss”, False),
e.get(“loot”, [])
)
# tuple fallback
name, hp, atk = e[0], e[1], e[2]
spd  = e[3] if len(e) > 3 else 10
dfn  = e[4] if len(e) > 4 else 0
return Combatant(name, hp, atk, spd, dfn)

```
enemies      = [_make_enemy(e) for e in enemies_data]
all_fighters = sorted(player_crew + enemies, key=lambda x: x.speed, reverse=True)
turn_counter = 0

while any(e.is_alive() for e in enemies) and any(p.is_alive() for p in player_crew):
    living = [f for f in all_fighters if f.is_alive()]
    if not living:
        break
    fighter = living[turn_counter % len(living)]
    turn_counter += 1

    # Status effect check before acting
    if fighter.status == "Stun":
        msg = fighter.end_turn_effects()
        if msg: show_message(msg)
        continue
    if fighter.status == "Glitch" and fighter not in player_crew:
        show_message(f"{fighter.name} weapon glitches—misses!")
        msg = fighter.end_turn_effects()
        if msg: show_message(msg)
        continue

    # ── PLAYER TURN ───────────────────────────────────────────
    if fighter in player_crew:
        _show_combat_hud(fighter, enemies, player_crew, game)

        action_opts = ["Attack", "Quickhack", "Use Item", "Status", "Flee" if flee_allowed else "Skip"]
        action = menu_choice(action_opts, title=f"{fighter.name}")
        if action == -1:
            return "hub"

        # ── ATTACK ──
        if action == 0:
            alive_en = [e for e in enemies if e.is_alive()]
            if not alive_en:
                continue
            t_idx = menu_choice(
                [f"{e.name} {e.hp}/{e.max_hp}HP" for e in alive_en],
                "Attack who?"
            )
            if t_idx == -1:
                continue
            target = alive_en[t_idx]
            # Crit check (10% + 5% per level)
            crit_chance = 0.10 + game.level * 0.05
            crit        = random.random() < crit_chance
            dmg         = fighter.attack + random.randint(-2, 5)
            if crit:
                dmg = int(dmg * 1.75)
            actual = target.take_damage(dmg)
            crit_tag = " CRITICAL!" if crit else ""
            show_message(f"{fighter.name} hits {target.name}\nfor {actual} dmg!{crit_tag}")
            if not target.is_alive():
                show_message(f"{target.name} is down!")
                # Loot drop
                for item in target.loot:
                    game.add_item(item)
                    show_message(f"Looted: {item}")

        # ── QUICKHACK ──
        elif action == 1:
            if not game.has_item("cyberdeck"):
                show_message("No cyberdeck installed.")
                continue
            hack_labels = [f"{h[0]} ({h[1]}E)" for h in HACK_MENU]
            hack_labels.append("Cancel")
            h_idx = menu_choice(hack_labels, "QUICKHACK")
            if h_idx == -1 or h_idx >= len(HACK_MENU):
                continue
            name, cost, effect, val, pierce = HACK_MENU[h_idx]
            if game.energy < cost:
                show_message(f"Need {cost}E. Have {game.energy}E.")
                continue
            game.energy -= cost
            alive_en = [e for e in enemies if e.is_alive()]
            if not alive_en:
                continue
            # Target selection
            t_idx = menu_choice([f"{e.name}" for e in alive_en], f"{name}: target?")
            if t_idx == -1:
                continue
            target = alive_en[t_idx]
            if effect == "damage":
                actual = target.take_damage(val, armor_pierce=pierce)
                show_message(f"{name}! {target.name} takes {actual} dmg.")
                if not target.is_alive():
                    show_message(f"{target.name} fried!")
                    for item in target.loot:
                        game.add_item(item)
                        show_message(f"Looted: {item}")
            elif effect == "reveal":
                show_message(f"{target.name}: HP {target.hp}/{target.max_hp}\nAtk {target.attack} Def {target.defense}")
            else:
                applied = target.apply_status(effect, val)
                if applied:
                    show_message(f"{name} applied to {target.name}!")
                else:
                    show_message(f"{target.name} resisted {name}!")

        # ── USE ITEM ──
        elif action == 2:
            usable = [i for i in game.inventory if i in [
                "medkit","MaxDoc","Stim","synthetic_meat","real_burger","trauma_kit"
            ]]
            if not usable:
                show_message("No usable items.")
                continue
            i_idx = menu_choice(usable + ["Cancel"], "Use which?")
            if i_idx == -1 or i_idx >= len(usable):
                continue
            item = usable[i_idx]
            heal_map = {"medkit":50,"MaxDoc":35,"synthetic_meat":20,"real_burger":35,"trauma_kit":80}
            if item in heal_map:
                heal = heal_map[item]
                # Target: self or ally
                targets = [p for p in player_crew if p.is_alive()]
                t_idx   = menu_choice([f"{p.name} {p.hp}HP" for p in targets], "Heal who?")
                if t_idx == -1:
                    continue
                targets[t_idx].hp = min(targets[t_idx].max_hp, targets[t_idx].hp + heal)
                game.inventory.remove(item)
                show_message(f"+{heal} HP to {targets[t_idx].name}!")
            elif item == "Stim":
                fighter.attack += 6
                game.inventory.remove(item)
                show_message(f"{fighter.name} surging! +6 ATK.")

        # ── STATUS ──
        elif action == 3:
            info = (f"{fighter.name}\n"
                    f"HP: {fighter.hp}/{fighter.max_hp}\n"
                    f"ATK: {fighter.attack}  DEF: {fighter.defense}\n"
                    f"Status: {fighter.status or 'None'}")
            show_message(info)

        # ── FLEE ──
        elif action == 4:
            if not flee_allowed:
                show_message("No escape!")
                continue
            flee_chance = 0.40 + game.street_cred * 0.03
            if random.random() < flee_chance:
                show_message("You escape the fight!")
                return "hub"
            else:
                show_message("Blocked! Can't flee.")

    # ── ENEMY TURN ────────────────────────────────────────────
    else:
        targets = [p for p in player_crew if p.is_alive()]
        if not targets:
            return False

        # Low morale flee (non-boss)
        if not fighter.boss:
            fighter.morale -= random.randint(0, 8)
            if fighter.morale < 15:
                show_message(f"{fighter.name} breaks and flees!")
                fighter.hp = 0
                msg = fighter.end_turn_effects()
                if msg: show_message(msg)
                continue

        target = random.choice(targets)

        # Boss special moves
        if fighter.boss:
            ability = fighter.choose_ability()
            if ability:
                ab_name, ab_mult = ability
                if ab_name == "AoE":
                    for p in targets:
                        dmg    = int(fighter.attack * ab_mult) + random.randint(-3, 3)
                        actual = p.take_damage(dmg)
                        show_message(f"{fighter.name} AoE hits {p.name} for {actual}!")
                        if not p.is_alive():
                            show_message(f"{p.name} down!")
                else:
                    dmg    = int(fighter.attack * ab_mult) + random.randint(-3, 3)
                    actual = target.take_damage(dmg)
                    show_message(f"{fighter.name} uses {ab_name}!\n{target.name} takes {actual} dmg!")
                    if not target.is_alive():
                        show_message(f"{target.name} is down!")
                msg = fighter.end_turn_effects()
                if msg: show_message(msg)
                continue

        # Regular attack
        dmg    = fighter.attack + random.randint(-2, 3)
        actual = target.take_damage(dmg)
        show_message(f"{fighter.name} hits {target.name}\nfor {actual} dmg!")
        if not target.is_alive():
            show_message(f"{target.name} is down!")
            if target in player_crew:
                player_crew.remove(target)

    # End-of-turn status
    msg = fighter.end_turn_effects()
    if msg:
        show_message(msg)
    if not fighter.is_alive() and fighter in player_crew:
        player_crew.remove(fighter)

    # Victory / defeat check
    if not any(p.is_alive() for p in player_crew):
        return False
    if not any(e.is_alive() for e in enemies):
        base_xp = 40 + len(enemies_data) * 15
        bonus   = sum(20 for e in enemies if (isinstance(e,dict) and e.get("boss")))
        total   = base_xp + bonus
        game.xp += total
        show_message(f"VICTORY!\n+{total} XP")
        while game.xp >= game.xp_to_level():
            game.level_up()
        return True

return any(p.is_alive() for p in player_crew)
```

# ─────────────────────────────────────────────────────────────────────

# GAME ENGINE

# ─────────────────────────────────────────────────────────────────────

class Game:
def **init**(self):
self.inventory          = []
self.flags              = {}
self.scene              = “start_menu”
self.running            = True
self.rep_arasaka        = 0
self.rep_militech       = 0
self.rep_voodoo         = 0
self.rep_netwatch       = 0
self.street_cred        = 0
self.crew               = []
self.crew_loyalty       = 50
self.romance            = None
self.health             = 100
self.eddies             = 500
self.equipped_weapon    = None
self.equipped_cyberware = None
self.player_name        = “Niko”
self.xp                 = 0
self.level              = 1
self.energy             = 100
# Story state
self.story_act          = 0
self.heist_done         = False
self.met_lucy           = False
self.lucy_trust         = 0
self.keys_found         = []    # “militech_key”|“voodoo_key”|“arasaka_key”
self.chose_militech     = False
self.chose_voodoo       = False
self.saved_vector       = False
self.relic_choice       = None  # “free”|“sell”|“destroy”

```
# ── XP / Level ──────────────────────────────────────────────────
def xp_to_level(self):
    return 300 + self.level * 200

def level_up(self):
    self.xp    -= self.xp_to_level()
    self.level += 1
    self.health = self.max_health()
    self.energy = 100
    bonus = "STR" if self.level % 3 == 0 else "TECH" if self.level % 3 == 1 else "REF"
    show_message(f"LEVEL UP! → Lv {self.level}\n+{bonus} bonus\nMax HP: {self.health}")

def max_health(self):
    return 100 + self.level * 12

# ── Reputation ──────────────────────────────────────────────────
def change_rep(self, faction, delta):
    attr = {"arasaka":"rep_arasaka","militech":"rep_militech",
            "voodoo":"rep_voodoo","netwatch":"rep_netwatch","street":"street_cred"}
    if faction in attr:
        cur = getattr(self, attr[faction])
        setattr(self, attr[faction], max(-10, min(10, cur + delta)))

# ── Inventory ───────────────────────────────────────────────────
def add_item(self, item):
    self.inventory.append(item)

def remove_item(self, item):
    if item in self.inventory:
        self.inventory.remove(item)

def has_item(self, item):
    return item in self.inventory

# ── Flags ────────────────────────────────────────────────────────
def set_flag(self, f, v=True):
    self.flags[f] = v

def check_flag(self, f):
    return self.flags.get(f, False)

# ── Crew ─────────────────────────────────────────────────────────
def add_crew(self, member):
    if member not in self.crew:
        self.crew.append(member)
        self.crew_loyalty = min(100, self.crew_loyalty + 10)
        show_message(f"{member} joins your crew!")

# ── Items ────────────────────────────────────────────────────────
def use_item(self, item):
    consumables = {
        "synthetic_meat": (20, "Synthetic meat"),
        "real_burger":    (35, "Real burger"),
        "medkit":         (50, "Medkit"),
        "MaxDoc":         (35, "MaxDoc"),
        "trauma_kit":     (80, "Trauma kit"),
    }
    if item in consumables:
        heal, label = consumables[item]
        self.health = min(self.max_health(), self.health + heal)
        self.remove_item(item)
        return f"{label}: +{heal} HP."
    equip_map = {
        "smart_rifle":   ("weapon",   "Smart rifle equipped."),
        "thermal_katana":("weapon",   "Thermal katana equipped."),
        "mono_wire":     ("weapon",   "Monowire equipped."),
        "cyberdeck":     ("cyberware","Cyberdeck installed."),
        "optical_camo":  ("cyberware","Optical camo installed."),
        "subdermal_grip":("cyberware","Subdermal grip installed. +DEF."),
    }
    if item in equip_map:
        slot, msg = equip_map[item]
        if slot == "weapon":
            self.equipped_weapon    = item
        else:
            self.equipped_cyberware = item
        return msg
    return f"Can't use {item} here."

def open_inventory(self):
    while True:
        choice = menu_choice(
            ["USE ITEM","VIEW CREW","EQUIP","CHARACTER","BACK"],
            title="INVENTORY"
        )
        if choice in (-1, 4):
            return
        if choice == 0:
            if not self.inventory:
                show_message("Empty.")
                continue
            idx = menu_choice(self.inventory + ["Cancel"], "Use which?")
            if idx < len(self.inventory) and idx != -1:
                show_message(self.use_item(self.inventory[idx]))
        elif choice == 1:
            if not self.crew:
                show_message("No crew yet.")
            else:
                lines = [f"{m}" for m in self.crew]
                lines.append(f"Loyalty: {self.crew_loyalty}%")
                show_message("\n".join(lines))
        elif choice == 2:
            weapons = [w for w in self.inventory
                       if any(k in w for k in ["rifle","katana","pistol","smg","mono"])]
            if not weapons:
                show_message("No weapons.")
            else:
                idx = menu_choice(weapons + ["Cancel"], "Equip")
                if idx < len(weapons) and idx != -1:
                    self.equipped_weapon = weapons[idx]
                    show_message(f"Equipped {weapons[idx]}.")
        elif choice == 3:
            info = (f"Name: {self.player_name}\n"
                    f"Level: {self.level}  XP: {self.xp}/{self.xp_to_level()}\n"
                    f"HP: {self.health}/{self.max_health()}\n"
                    f"Energy: {self.energy}\n"
                    f"Eddies: {self.eddies}\n"
                    f"Weapon: {self.equipped_weapon or 'None'}\n"
                    f"Cyber: {self.equipped_cyberware or 'None'}\n"
                    f"Act: {self.story_act}/10")
            show_message(info)

# ── Save / Load ───────────────────────────────────────────────────
def save_game(self):
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(self.__dict__, f, indent=2)
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

# ── UI Wrappers ───────────────────────────────────────────────────
def _wrap(self, text):
    return textwrap.wrap(text, width=22)

def show_text(self, raw_lines, title="2087"):
    all_lines = []
    for line in raw_lines:
        if not line.strip():
            all_lines.append("")
        else:
            all_lines.extend(self._wrap(line))
    pages = [all_lines[i:i+5] for i in range(0, max(1,len(all_lines)), 5)]
    if not pages:
        pages = [["(nothing)"]]
    pidx = 0
    while True:
        DRAW.rectangle((0,0,W,H), fill=(10,0,0))
        DRAW.rectangle((0,0,W,13), fill=(120,0,0))
        DRAW.text((4,2), title[:20], font=FONT_BOLD, fill=(231,76,60))
        y = 16
        for line in pages[pidx]:
            DRAW.text((4,y), line[:22], font=FONT, fill=(171,178,185))
            y += 12
        if len(pages) > 1:
            DRAW.text((W-18,H-12), f"{pidx+1}/{len(pages)}", font=FONT, fill=(160,40,40))
        status = f"HP:{self.health} ${self.eddies} Lv{self.level}"
        DRAW.text((2,H-12), status[:22], font=FONT, fill=(140,30,30))
        LCD.LCD_ShowImage(IMAGE, 0, 0)
        btn = wait_btn(0.25)
        if btn == "UP":
            pidx = max(0, pidx-1);    wait_for_release("UP")
        elif btn == "DOWN":
            pidx = min(len(pages)-1, pidx+1); wait_for_release("DOWN")
        elif btn == "OK":
            if pidx < len(pages)-1:
                pidx += 1
            else:
                wait_for_release("OK"); return
            wait_for_release("OK")
        elif btn == "KEY2":
            wait_for_release("KEY2"); self.scene = "afterlife_hub"; return
        elif btn == "KEY3":
            wait_for_release("KEY3"); self.running = False; return

def choose(self, choices, title="2087"):
    if not choices:
        return None
    sel = 0
    while True:
        DRAW.rectangle((0,0,W,H), fill=(10,0,0))
        DRAW.rectangle((0,0,W,13), fill=(120,0,0))
        DRAW.text((4,2), title[:20], font=FONT_BOLD, fill=(231,76,60))
        y = 16
        start = max(0, sel-2)
        end   = min(len(choices), start+5)
        for i, ch in enumerate(choices[start:end]):
            ai = start + i
            if ai == sel:
                DRAW.rectangle((0,y-1,W,y+9), fill=(60,0,0))
                DRAW.text((4,y), f">{ch[:20]}", font=FONT, fill=(255,255,255))
            else:
                DRAW.text((4,y), f" {ch[:20]}", font=FONT, fill=(171,178,185))
            y += 12
        if len(choices) > 5:
            DRAW.text((W-18,H-12), f"{sel+1}/{len(choices)}", font=FONT, fill=(160,40,40))
        status = f"HP:{self.health} ${self.eddies} Lv{self.level}"
        DRAW.text((2,H-12), status[:22], font=FONT, fill=(140,30,30))
        LCD.LCD_ShowImage(IMAGE, 0, 0)
        btn = wait_btn(0.2)
        if btn == "UP":
            sel = max(0,sel-1);             wait_for_release("UP")
        elif btn == "DOWN":
            sel = min(len(choices)-1,sel+1); wait_for_release("DOWN")
        elif btn == "OK":
            wait_for_release("OK"); return sel
        elif btn == "KEY2":
            wait_for_release("KEY2"); self.scene = "afterlife_hub"; return -1
        elif btn == "KEY3":
            wait_for_release("KEY3"); self.running = False; return -2

def run_combat(self, enemies_data, flee_allowed=True):
    """Helper: build player crew, run combat, sync health. Returns True/False/'hub'."""
    crew = _build_player_combatants(self)
    result = combat_encounter(crew, enemies_data, self, flee_allowed=flee_allowed)
    # Sync Niko's HP back
    for c in crew:
        if c.name == "Niko":
            self.health = max(0, c.hp)
    return result
```

# ═══════════════════════════════════════════════════════════════════════

# SCENES

# ═══════════════════════════════════════════════════════════════════════

# ─── START MENU ─────────────────────────────────────────────────────

def scene_start_menu(g):
g.show_text([“CYBERPUNK 2087”,“Night City never dies.”,“v2.0 – wickednull”])
idx = g.choose([“New Game”,“Continue”,“About”])
if idx == 0:
g.**init**()
return “prologue”
elif idx == 1:
if g.load_game():
g.show_text([“Loaded.”, f”Returning to Act {g.story_act}.”])
return g.scene
g.show_text([“No save found.”,“Starting new game.”])
return “prologue”
elif idx == 2:
g.show_text([
“Cyberpunk 2087 v2.0”,
“Full RPG for Raspberry Pi Zero 2W”,
“10 acts, multiple endings.”,
“author: wickednull”,
])
return “start_menu”
return “start_menu”

# ─── PROLOGUE ───────────────────────────────────────────────────────

def scene_prologue(g):
g.show_text([
“PROLOGUE”,
“Night City, 2087.”,
“Arasaka collapsed in the coup of 2077. Militech filled the void.”,
“The corps rebuilt the city in their image: chrome and surveillance.”,
“You are NIKO. Twenty-three. No chrome. No corp. Just a debt.”,
“Fixer Rook keeps calling. Said it’s urgent.”,
“Your cracked neural port buzzes. Time to answer.”
], title=“PROLOGUE”)
idx = g.choose([“Go to Afterlife bar”,“Check your messages first”,“Ignore everything”])
if idx == 0:
return “afterlife_intro”
elif idx == 1:
return “messages_intro”
else:
g.show_text([
“You sit on a pile of scrap.”,
“An hour later, Rook shows up in person.”,
“‘Niko. GET UP. I’m not paying in patience.’”
])
return “afterlife_intro”

def scene_messages_intro(g):
g.show_text([
“MESSAGES”,
“Rook: ‘Afterlife. Now. 10k job.’”,
“Unknown: ‘You don’t know me. But I know you. – L’”,
“Bank: ‘You owe 800 eddies. Final notice.’”
], title=“MESSAGES”)
g.show_text([
“The mysterious message from ‘L’ is encrypted.”,
“Rook’s offer sounds real.”,
“The debt sounds worse.”
])
return “afterlife_intro”

# ─── ACT 1: THE HEIST ───────────────────────────────────────────────

def scene_afterlife_intro(g):
g.show_text([
“ACT 1 – THE HEIST”,
“The Afterlife. Neon signs flicker.”,
“‘David Martinez’ on the menu—a tribute to a legend.”,
“Rook leans over a table in the back.”,
“‘Finally. Militech is moving a prototype neural chip—Relic 2.0 prequel.’,”,
“‘Convoy route, tomorrow night. 10k eddies if you grab it.’”,
], title=“ACT 1”)
idx = g.choose([“Take the job”,“Ask about the chip”,“Negotiate price”,“Walk away”])
if idx == 0:
g.set_flag(“accepted_heist”)
return “heist_plan”
elif idx == 1:
g.show_text([
“Rook: ‘Prototype neural processor. Militech calls it the Ghost Relic.’”,
“‘Word is it can copy engrams without Arasaka’s method.’”,
“‘Don’t ask more. Take the job.’”
])
g.set_flag(“knows_chip_value”)
return “afterlife_intro”
elif idx == 2:
g.show_text([
“You push for 15k.”,
“Rook: ‘12k. Final offer. You’re not in a position to negotiate.’”,
“You take it.”
])
g.set_flag(“negotiated_pay”)
g.set_flag(“accepted_heist”)
return “heist_plan”
else:
g.show_text([
“You walk out. Your debt notice buzzes again.”,
“Two hours later you’re back.”,
“Rook: ‘Good. I knew you’d come around.’”
])
g.set_flag(“accepted_heist”)
return “heist_plan”

def scene_heist_plan(g):
g.show_text([
“You need a plan. The convoy has:”,
“- 4 guards”,
“- A Militech AV overhead”,
“- Scrambled comms”,
“Options: frontal assault, ambush, or find a netrunner to disable systems first.”
], title=“HEIST PLAN”)
idx = g.choose([“Recruit crew first”,“Assault convoy alone”,“Scout the route”,“Buy gear”])
if idx == 0:
return “crew_recruit_hub”
elif idx == 1:
return “heist_alone”
elif idx == 2:
g.show_text([
“You scout the highway overpass.”,
“You identify a choke point.”,
“Bonus: the AV has a blind spot when it banks west.”,
])
g.set_flag(“scouted_convoy”)
return “heist_plan”
else:
return “shop”

def scene_crew_recruit_hub(g):
g.show_text([
“Before the heist, you need people.”,
“You know of Maya—a solo in the Combat Zone.”,
“And Jin—a netrunner hiding in Kabuki.”
], title=“RECRUIT”)
idx = g.choose([“Find Maya (Combat Zone)”,“Find Jin (Kabuki)”,“Go straight to heist”])
if idx == 0: return “combat_zone”
elif idx == 1: return “kabuki”
else: return “heist_combat”

def scene_heist_alone(g):
g.show_text([
“You go in alone. Brutal. Efficient. Risky.”,
“Three Militech guards on the overpass.”,
“You have to move fast.”
], title=“HEIST: SOLO”)
result = g.run_combat([
(“Militech Guard”, 30, 9, 10, 1),
(“Militech Guard”, 30, 9, 10, 1),
(“Convoy Driver”,  20, 6,  8, 0),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“You’re cut down. Game over.”])
g.running = False
return None
g.add_item(“prototype_chip”)
g.eddies += 12000 if g.check_flag(“negotiated_pay”) else 10000
g.heist_done   = True
g.story_act    = 1
g.change_rep(“street”, 2)
return “after_heist”

def scene_heist_combat(g):
g.show_text([
“Your crew hits the convoy at the overpass.”,
“Jin kills the AV feed. Maya lays down suppressing fire.”,
“You punch through the middle.”
], title=“HEIST: CREW”)
scout_bonus = 5 if g.check_flag(“scouted_convoy”) else 0
enemies = [
(“Militech Guard”,    35, 10-scout_bonus, 10, 1),
(“Militech Guard”,    35, 10-scout_bonus, 10, 1),
(“Militech Sergeant”, 50, 13,             12, 2),
]
result = g.run_combat(enemies)
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Your crew is wiped. Game over.”])
g.running = False
return None
g.add_item(“prototype_chip”)
pay = 12000 if g.check_flag(“negotiated_pay”) else 10000
g.eddies     += pay
g.heist_done  = True
g.story_act   = 1
g.change_rep(“street”, 3)
return “after_heist”

def scene_after_heist(g):
g.show_text([
“ACT 1 COMPLETE”,
“Rook pays up. No questions.”,
“But as you leave, a Militech agent blocks the door.”,
“Vector: ‘Nice work, choom. We were watching.’”,
“‘Hand over the chip, work for us, or we bury you.’”,
“She holds up a badge. Colonel Ana Vector. Militech Intel.”
], title=“AFTERMATH”)
idx = g.choose([
“Work for Militech”,
“Refuse—keep the chip”,
“Hand it over (400 eddies back)”,
“Attack her”
])
if idx == 0:
g.chose_militech = True
g.change_rep(“militech”, 3)
g.set_flag(“vector_ally”)
g.show_text([“Vector: ‘Smart. First job: find out who leaked our route.’”])
return “act2_hub”
elif idx == 1:
g.change_rep(“militech”, -4)
g.set_flag(“militech_enemy”)
g.show_text([
“Vector: ‘Your funeral.’”,
“She leaves. But you know they’ll send someone else.”
])
return “act2_hub”
elif idx == 2:
g.eddies += 400
g.remove_item(“prototype_chip”)
g.show_text([
“You hand it over. Vector nods.”,
“‘Reasonable. We’ll be in touch.’”,
“The chip is gone. But you’re alive.”
])
g.change_rep(“militech”, 1)
return “act2_hub”
else:
g.show_text([“You lunge—Vector’s six guards appear from nowhere.”,
“You barely escape through the kitchen.”])
g.change_rep(“militech”, -5)
g.health = max(1, g.health - 30)
return “act2_hub”

# ─── ACT 2 ──────────────────────────────────────────────────────────

def scene_act2_hub(g):
g.story_act = max(g.story_act, 2)
g.show_text([
“ACT 2 – GHOST SIGNAL”,
“Night City hums with tension.”,
“Militech is tightening its grip on the net.”,
“And that encrypted message from ‘L’ is still in your agent.”,
“Jin decrypts it: ‘Pacifica, old netrunner den. Come alone.’”,
], title=“ACT 2”)
idx = g.choose([
“Go to Pacifica now”,
“Investigate Militech leak first”,
“Hit the Combat Zone for work”,
“Visit Afterlife hub”
])
if idx == 0: return “pacifica_first”
elif idx == 1: return “militech_leak”
elif idx == 2: return “combat_zone”
else: return “afterlife_hub”

def scene_pacifica_first(g):
g.show_text([
“Pacifica. Half-built towers. Sea-wind.”,
“The den: a basement of dead terminals.”,
“Then—a holographic figure. Silver hair. White jacket.”,
“‘I’m Lucy. I’ve been watching you since the convoy.’”,
“‘You’re different. You ask questions.’”,
“‘I need someone like that. Do you know what the Ghost Relic does?’”
], title=“LUCY”)
idx = g.choose([“Ask what she wants”,“Mention the prototype chip”,“Tell her you work alone”])
if idx == 0:
g.show_text([
“Lucy: ‘Militech and Arasaka both want the same thing—Mikoshi.’”,
“‘Arasaka’s soul trap. They still run it from the ruins.’”,
“‘I need to destroy it. And the Ghost Relic is the key.’”,
“‘Will you help me?’”
])
return “lucy_deal”
elif idx == 1:
g.show_text([
“Lucy’s eyes widen. ‘You have it? Don’t let anyone know.’”,
“‘That chip is a map to Mikoshi’s backdoor.’”,
“‘I need it. And I need you.’”
])
g.lucy_trust += 1
return “lucy_deal”
else:
g.show_text([
“Lucy: ‘That’s fine. But they’ll come for you regardless.’”,
“‘The chip you stole just painted a target on your back.’”,
“‘Help me, and I can keep you invisible.’”
])
return “lucy_deal”

def scene_lucy_deal(g):
g.show_text([
“Lucy lays out the plan:”,
“Three access keys to reach the Mikoshi core.”,
“1. Militech clearance code”,
“2. Voodoo Boys net ritual”,
“3. Arasaka biokey—from a living exec.”,
“‘Together, we can free every engram they’ve ever stolen.’”,
“She looks at you. ‘Are you in?’”
], title=“THE PLAN”)
idx = g.choose([“Yes—I’m in”,“Ask about David Martinez”,“Demand payment”,“Refuse”])
if idx == 0:
g.met_lucy    = True
g.lucy_trust += 1
g.story_act   = max(g.story_act, 3)
return “act3_key_hunt”
elif idx == 1:
g.show_text([
“Lucy’s expression softens. Then hardens.”,
“‘David was everything. He died for this city.’”,
“‘His engram is in Mikoshi. I want to give him rest.’”,
“She looks away. ‘Are you in?’”
])
g.lucy_trust += 1
return “lucy_deal”
elif idx == 2:
g.show_text([
“Lucy: ‘There’s no eddies here. Only a chance to do something real.’”,
“‘But if we succeed—you’ll have access to Arasaka’s vaults.’”,
“‘That’s worth more than Rook could ever pay you.’”
])
g.lucy_trust += 1
return “lucy_deal”
else:
g.show_text([
“Lucy: ‘Okay. But when they come for you—and they will—’”,
“‘don’t come looking for me.’”,
“She vanishes from the projector.”
])
return “afterlife_hub”

def scene_militech_leak(g):
g.show_text([
“Vector’s intel: someone inside Militech sold the convoy route.”,
“You track the leak to a low-level data analyst named Hiro.”,
“He’s hiding in a Kabuki capsule hotel.”
], title=“LEAK HUNT”)
idx = g.choose([“Confront Hiro”,“Tail him first”,“Report directly to Vector”])
if idx == 0:
return “hiro_confront”
elif idx == 1:
g.show_text([
“You watch Hiro for hours. He’s nervous. Buying passage tickets.”,
“He’s planning to run. You corner him at the metro station.”
])
return “hiro_confront”
else:
g.show_text([
“Vector thanks you. ‘We’ll handle it.’”,
“A day later, Hiro disappears from all records.”,
“+2000 eddies deposited to your account.”
])
g.eddies     += 2000
g.change_rep(“militech”, 1)
return “act2_hub”

def scene_hiro_confront(g):
g.show_text([
“Hiro: ‘Please—Voodoo Boys threatened my family.’”,
“‘I had no choice. They have eyes everywhere.’”,
“He hands you a data shard. ‘This is everything I gave them.’”
], title=“HIRO”)
idx = g.choose([
“Let him go—keep the shard”,
“Turn him in to Vector”,
“Help him escape Night City”
])
if idx == 0:
g.add_item(“voodoo_intel”)
g.show_text([
“Hiro runs. You have Voodoo Boys operational data.”,
“This could be worth a lot.”
])
g.change_rep(“street”, 1)
return “act2_hub”
elif idx == 1:
g.eddies += 3000
g.change_rep(“militech”, 2)
g.show_text([
“Vector is pleased. 3k eddies. No questions.”,
“You try not to think about Hiro.”
])
return “act2_hub”
else:
g.eddies -= 500
g.set_flag(“helped_hiro”)
g.change_rep(“street”, 2)
g.show_text([
“You burn 500 eddies on a false-flag passage ticket.”,
“Hiro vanishes. You feel… okay about that.”
])
return “act2_hub”

# ─── ACT 3: THREE KEYS ──────────────────────────────────────────────

def scene_act3_key_hunt(g):
g.show_text([
“ACT 3 – THREE KEYS”,
“Lucy’s access requirements:”,
f”1. Militech clearance {’[DONE]’ if ‘militech_key’ in g.keys_found else ‘[NEEDED]’}”,
f”2. Voodoo Boys ritual {’[DONE]’ if ‘voodoo_key’ in g.keys_found else ‘[NEEDED]’}”,
f”3. Arasaka biokey {’[DONE]’ if ‘arasaka_key’ in g.keys_found else ‘[NEEDED]’}”,
], title=“ACT 3”)
if len(g.keys_found) >= 3:
return “act4_night_city_burns”
idx = g.choose([
“Militech Clearance”,
“Voodoo Boys Ritual”,
“Arasaka Biokey”,
“Back to hub”
])
if idx == 0: return “key_militech”
elif idx == 1: return “key_voodoo”
elif idx == 2: return “key_arasaka”
else: return “afterlife_hub”

def scene_key_militech(g):
if “militech_key” in g.keys_found:
g.show_text([“Already obtained.”])
return “act3_key_hunt”
if g.chose_militech or g.check_flag(“vector_ally”):
g.show_text([
“Vector: ‘You want clearance? Earn it.’”,
“‘There’s a Voodoo Boys cache in Pacifica. Destroy it.’”,
], title=“VECTOR”)
idx = g.choose([“Accept”,“Refuse”])
if idx == 0:
return “militech_key_mission”
else:
g.show_text([“Vector: ‘Then we’re done here.’”])
return “act3_key_hunt”
else:
g.show_text([
“No Militech contacts. You’ll have to steal the clearance.”,
“A Militech relay station in Watson has what you need.”
], title=“RELAY HEIST”)
idx = g.choose([“Infiltrate the relay”,“Hack from outside (needs cyberdeck)”,“Buy it on the black market (5000 eddies)”])
if idx == 0:
return “relay_infiltrate”
elif idx == 1:
return “relay_hack”
else:
return “relay_buy”

def scene_relay_infiltrate(g):
g.show_text([“Watson relay. You go in hard.”, “Three guards. A turret.”])
result = g.run_combat([
(“Relay Guard”,  35, 10, 10, 1),
(“Relay Guard”,  35, 10, 10, 1),
{“name”:“Relay Turret”,“hp”:60,“attack”:16,“speed”:5,“defense”:4,
“abilities”:[(“Burst”,1.5)], “loot”:[“relay_parts”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Overwhelmed. Game over.”])
g.running = False
return None
g.keys_found.append(“militech_key”)
g.add_item(“militech_clearance”)
g.show_text([“Clearance code copied. Key 1 obtained!”])
return “act3_key_hunt”

def scene_relay_hack(g):
if not g.has_item(“cyberdeck”):
g.show_text([“You need a cyberdeck for this.”])
return “act3_key_hunt”
if g.energy < 40:
g.show_text([“Not enough energy. Rest first.”])
return “act3_key_hunt”
g.energy -= 40
success = random.random() < 0.65 + g.level * 0.05
if success:
g.keys_found.append(“militech_key”)
g.add_item(“militech_clearance”)
g.show_text([“Jin walks you through it. Clearance extracted! Key 1 obtained!”])
else:
g.show_text([“ICE catches you. You break the connection. Try again later.”])
g.health = max(1, g.health - 15)
return “act3_key_hunt”

def scene_relay_buy(g):
if g.eddies < 5000:
g.show_text([“Need 5000 eddies.”])
return “act3_key_hunt”
g.eddies -= 5000
g.keys_found.append(“militech_key”)
g.add_item(“militech_clearance”)
g.show_text([“Black market fixer delivers. Key 1 obtained!”])
return “act3_key_hunt”

def scene_militech_key_mission(g):
g.show_text([
“Voodoo Boys cache in Pacifica.”,
“Sable’s people won’t give it up without a fight.”
], title=“VOODOO CACHE”)
result = g.run_combat([
(“Voodoo Guard”,   40, 11, 11, 1),
(“Voodoo Netrunner”, 30, 14, 13, 0),
(“Voodoo Guard”,   40, 11, 11, 1),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Beaten back. Game over.”])
g.running = False
return None
g.keys_found.append(“militech_key”)
g.add_item(“militech_clearance”)
g.change_rep(“militech”, 1)
g.change_rep(“voodoo”, -2)
g.show_text([“Cache destroyed. Vector honors her word. Key 1 obtained!”])
return “act3_key_hunt”

def scene_key_voodoo(g):
if “voodoo_key” in g.keys_found:
g.show_text([“Already obtained.”])
return “act3_key_hunt”
g.show_text([
“The Voodoo Boys. Pacifica’s net-shamans.”,
“Their leader Sable demands you prove yourself first.”,
“‘Complete the NetWatch Purge. Kill three of their agents.’”,
“Or: ‘Bring me the Voodoo intel Hiro leaked.’”
], title=“SABLE”)
if g.has_item(“voodoo_intel”):
idx = g.choose([“Give her the intel”,“Do the NetWatch Purge”,“Negotiate directly”])
else:
idx = g.choose([“Do the NetWatch Purge”,“Negotiate directly”,“Leave”])
if idx == 0 and g.has_item(“voodoo_intel”):
g.remove_item(“voodoo_intel”)
g.keys_found.append(“voodoo_key”)
g.change_rep(“voodoo”, 3)
g.show_text([“Sable is impressed. ‘You play smart, choom.’”, “Key 2 obtained!”])
return “act3_key_hunt”
elif (idx == 0 and not g.has_item(“voodoo_intel”)) or idx == 0:
return “netwatch_purge”
elif idx == 1:
g.show_text([
“Sable laughs. ‘Negotiate? With what?’”,
“She crosses her arms. The room fills with guards.”,
])
return “voodoo_brawl”
else:
return “act3_key_hunt”

def scene_netwatch_purge(g):
g.show_text([
“Three NetWatch agents.”,
“You track them to a safehouse in Vista del Rey.”
], title=“PURGE”)
result = g.run_combat([
(“NetWatch Agent”,  45, 13, 12, 2),
(“NetWatch Agent”,  45, 13, 12, 2),
{“name”:“NW Captain”,“hp”:75,“attack”:18,“speed”:14,“defense”:4,
“abilities”:[(“EMP Burst”,1.3),(“Hack”,0.8)],
“loot”:[“netwatch_badge”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Taken down. Game over.”])
g.running = False
return None
g.keys_found.append(“voodoo_key”)
g.change_rep(“voodoo”, 2)
g.change_rep(“netwatch”, -3)
g.show_text([“Agents down. Sable honors the deal.”, “Key 2 obtained!”])
return “act3_key_hunt”

def scene_voodoo_brawl(g):
g.show_text([“They’re not letting you negotiate. Fight your way out.”])
result = g.run_combat([
(“Voodoo Guard”, 40, 11, 11, 1),
(“Voodoo Guard”, 40, 11, 11, 1),
(“Voodoo Guard”, 40, 11, 11, 1),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Overwhelmed. Game over.”])
g.running = False
return None
g.show_text([
“You fight out. Sable watches from the shadows.”,
“‘Respect. Come back when you have a real offer.’”
])
return “act3_key_hunt”

def scene_key_arasaka(g):
if “arasaka_key” in g.keys_found:
g.show_text([“Already obtained.”])
return “act3_key_hunt”
g.show_text([
“The Arasaka biokey.”,
“Only a living Arasaka executive carries one.”,
“Lucy has a lead: Exec Hanako Tanaka.”,
“She’s hiding in a safehouse in Corpo Plaza ruins.”,
“But she has a full security detail.”
], title=“TANAKA”)
idx = g.choose([“Storm the safehouse”,“Try diplomacy first”,“Set a trap”])
if idx == 0:
return “arasaka_storm”
elif idx == 1:
return “arasaka_diplomacy”
else:
return “arasaka_trap”

def scene_arasaka_storm(g):
g.show_text([“Heavy security. This is a full assault.”], title=“ASSAULT”)
result = g.run_combat([
(“Arasaka Guard”,  50, 14, 11, 3),
(“Arasaka Guard”,  50, 14, 11, 3),
(“Arasaka Cyber”,  70, 18, 13, 5),
{“name”:“Security Chief”,“hp”:90,“attack”:22,“speed”:12,“defense”:6,
“abilities”:[(“Suppressive”,1.4),(“Shield”,0.5)],
“boss”:True, “loot”:[“arasaka_keycard”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Torn apart. Game over.”])
g.running = False
return None
g.keys_found.append(“arasaka_key”)
g.add_item(“arasaka_biokey”)
g.change_rep(“arasaka”, -2)
g.show_text([“Security down. You extract the biokey.”, “Tanaka cooperates—barely.”, “Key 3 obtained!”])
return “act3_key_hunt”

def scene_arasaka_diplomacy(g):
g.show_text([
“You send a message: ‘I’m not Militech. I don’t want you dead.’”,
“‘Meet me. Unarmed. I’ll explain.’”,
“Two hours of silence. Then: ‘Come alone. One hour.’”
], title=“DIPLOMACY”)
idx = g.choose([“Go alone (trust her)”,“Go with hidden crew”,“Send Jin instead”])
if idx == 0:
g.show_text([
“Tanaka meets you. She’s terrified.”,
“‘Militech wants me dead. If you’re against them, maybe…’”,
“She provides the biokey. ‘Free the engrams. Free my father.’”,
])
g.lucy_trust += 1
g.set_flag(“tanaka_ally”)
g.keys_found.append(“arasaka_key”)
g.add_item(“arasaka_biokey”)
g.change_rep(“arasaka”, 1)
g.show_text([“Key 3 obtained! And Tanaka might help you later.”])
return “act3_key_hunt”
elif idx == 1:
g.show_text([
“She notices. ‘You came armed.’”,
“‘But you’re still here talking. Fine.’”,
“A tense exchange. She gives you the biokey.”
])
g.keys_found.append(“arasaka_key”)
g.add_item(“arasaka_biokey”)
g.show_text([“Key 3 obtained!”])
return “act3_key_hunt”
else:
g.show_text([
“Jin: ‘She won’t talk to me. Too scared.’”,
“‘But I grabbed her comms data. There’s a biokey backup in her luggage.’”,
])
return “arasaka_storm”

def scene_arasaka_trap(g):
g.show_text([
“You leak a false lead to draw her security away.”,
“Then you slip in with Jin while Maya covers the exit.”,
“It almost works.”
], title=“TRAP”)
result = g.run_combat([
(“Arasaka Guard”, 50, 14, 11, 3),
(“Arasaka Cyber”,  70, 18, 13, 5),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Trap backfires. Game over.”])
g.running = False
return None
g.keys_found.append(“arasaka_key”)
g.add_item(“arasaka_biokey”)
g.show_text([“Trap pays off. Biokey in hand.”, “Key 3 obtained!”])
return “act3_key_hunt”

# ─── ACT 4: NIGHT CITY BURNS ────────────────────────────────────────

def scene_act4_night_city_burns(g):
g.story_act = max(g.story_act, 4)
g.show_text([
“ACT 4 – NIGHT CITY BURNS”,
“All three keys secured.”,
“But Militech found out. They’re moving on Pacifica.”,
“Vector: ‘Stand down or we’ll level the district.’”,
“Sable: ‘We need to move. Tonight.’”,
“Your crew: ready. Lucy: waiting.”,
“But Rook calls—he’s been taken. Leverage.”
], title=“ACT 4”)
idx = g.choose([“Save Rook first”,“Ignore Rook—go to Lucy”,“Strike back at Militech”])
if idx == 0:
return “save_rook”
elif idx == 1:
g.show_text([“Rook’s on his own. You have bigger problems.”, “(You can’t go back on this choice.)”])
g.set_flag(“abandoned_rook”)
return “act4_assault”
else:
return “militech_ambush”

def scene_save_rook(g):
g.show_text([
“Militech holding facility. Industrial district.”,
“Rook’s inside. Twelve guards. No negotiating.”
], title=“RESCUE”)
result = g.run_combat([
(“Militech Guard”, 40, 11, 10, 2),
(“Militech Guard”, 40, 11, 10, 2),
(“Militech Elite”, 60, 16, 13, 4),
(“Militech Elite”, 60, 16, 13, 4),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Rook dies in custody. Game over.”])
g.running = False
return None
g.set_flag(“saved_rook”)
g.change_rep(“street”, 2)
g.show_text([
“Rook: ‘I owe you one, choom. Get out of here.’”,
“+3000 eddies and Rook’s loyalty.”
])
g.eddies += 3000
return “act4_assault”

def scene_militech_ambush(g):
g.show_text([
“You hit Vector’s forward base in Watson.”,
“Brutal fighting. But you send a message.”
], title=“AMBUSH”)
result = g.run_combat([
(“Militech Soldier”, 45, 13, 11, 3),
(“Militech Soldier”, 45, 13, 11, 3),
{“name”:“Vector’s Lieut”,“hp”:100,“attack”:20,“speed”:14,“defense”:6,
“abilities”:[(“Flashbang”,0.5),(“Tactical”,1.3)],
“loot”:[“vector_intel”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Outgunned. Game over.”])
g.running = False
return None
g.change_rep(“militech”, -3)
g.change_rep(“street”, 3)
g.show_text([“Message sent. Militech pulls back. For now.”])
return “act4_assault”

def scene_act4_assault(g):
g.show_text([
“The path to Mikoshi opens.”,
“Lucy: ‘The Blackwall relay is in the old Arasaka tower.’”,
“‘One more fight. Then we’re in.’”,
], title=“ACT 4 PUSH”)
return “arasaka_tower”

# ─── ARASAKA TOWER (Expanded) ────────────────────────────────────────

def scene_arasaka_tower(g):
g.show_text([
“THE TOWER”,
“Arasaka HQ ruins. Still radiating data.”,
“Automated defenses online. Decade-old ICE.”,
“Your crew splits up to cover more ground.”
], title=“TOWER”)
idx = g.choose([“Force through the lobby”,“Use the maintenance shaft”,“Jin hacks the security grid”])
if idx == 0: return “tower_lobby”
elif idx == 1: return “tower_shaft”
elif idx == 2: return “tower_hack_grid”
else: return “afterlife_hub”

def scene_tower_lobby(g):
g.show_text([“Automated defenses. Heavy.”], title=“LOBBY”)
result = g.run_combat([
(“Security Drone”,   45, 14, 15, 3),
(“Security Drone”,   45, 14, 15, 3),
(“Arasaka Hardsuit”, 90, 20, 10, 8),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Ground down. Game over.”])
g.running = False
return None
return “tower_sublevel”

def scene_tower_shaft(g):
g.show_text([
“Maintenance shaft. Tight. Dark.”,
“Two drones patrol the junction.”
], title=“SHAFT”)
result = g.run_combat([
(“Patrol Drone”, 35, 11, 16, 2),
(“Patrol Drone”, 35, 11, 16, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Trapped in the shaft. Game over.”])
g.running = False
return None
return “tower_sublevel”

def scene_tower_hack_grid(g):
if “Jin” not in g.crew:
g.show_text([“You need Jin for this.”])
return “arasaka_tower”
if g.energy < 30:
g.show_text([“Not enough energy.”])
return “arasaka_tower”
g.energy -= 30
g.show_text([
“Jin: ‘I’m in. Disabling turrets…’”,
“‘There’s something else in here. Something watching.’”,
“A Daemon latches onto Jin’s connection.”
])
result = g.run_combat([
{“name”:“Black ICE”,“hp”:60,“attack”:18,“speed”:17,“defense”:5,
“abilities”:[(“Dataspike”,1.6)], “loot”:[“ice_fragment”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Jin is flatlined. Game over.”])
g.running = False
return None
g.show_text([“Daemon beaten. Security grid down. You walk right in.”])
return “tower_sublevel”

def scene_tower_sublevel(g):
g.show_text([
“Sublevel -4. The core.”,
“A pulse of light—Lucy’s avatar.”,
“‘Here it is. The Blackwall relay to Mikoshi.’”,
“‘Jack in. I’ll guide you through.’”,
“But then—footsteps. Heavy ones.”
], title=“SUBLEVEL”)
return “tower_boss”

def scene_tower_boss(g):
g.show_text([
“The elevator opens.”,
“Adam Smasher. Or what’s left of him.”,
“Militech rebuilt him. He’s been waiting.”,
“‘You think you can touch Mikoshi?’”,
“‘I’ve been killing legends for twenty years.’”
], title=“SMASHER”)
idx = g.choose([“Fight him”,“Stall while Lucy hacks”,“Try to reason with him”])
if idx == 2:
g.show_text([“He laughs. It sounds like grinding gears.”,
“‘Reason? You’re a punchline.’”])
# All paths lead to the fight
result = g.run_combat([
{“name”:“Adam Smasher”,“hp”:220,“attack”:35,“speed”:11,“defense”:12,
“abilities”:[(“Missile Barrage”,2.0),(“AoE”,1.5),(“Gore Cannon”,1.8)],
“boss”:True, “loot”:[“smasher_core”]},
], flee_allowed=False)
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([
“Smasher tears through your crew.”,
“GAME OVER.”,
“Legends die here.”
])
g.running = False
return None
g.story_act = max(g.story_act, 5)
return “tower_ending”

def scene_tower_ending(g):
g.show_text([
“Smasher crumbles.”,
“Lucy: ‘I can’t believe that worked.’”,
“You: ‘It barely did.’”,
“Maya binds her wounds. Jin stares at Smasher’s remains.”,
“Lucy: ‘The Blackwall relay is open. Mikoshi is reachable.’”,
“‘But it’s inside the net. We’ll need to dive deep.’”
], title=“TOWER CLEAR”)
return “act5_blackwall”

# ─── ACT 5: THE BLACKWALL ────────────────────────────────────────────

def scene_act5_blackwall(g):
g.story_act = max(g.story_act, 5)
g.show_text([
“ACT 5 – THE BLACKWALL”,
“The Blackwall: a digital border between the net and rogue AIs.”,
“No one crosses and comes back the same.”,
“Lucy: ‘Mikoshi is on the other side.’”,
“‘The three keys will create a hole. Brief. We go through fast.’”,
“Jin: ‘If an AI locks onto us in there, we’re dead.’”,
“You: ‘Then we move fast.’”
], title=“ACT 5”)
idx = g.choose([“Dive in”,“Make final preparations”,“Talk to your crew”])
if idx == 0:
return “blackwall_dive”
elif idx == 1:
return “pre_blackwall_prep”
else:
return “crew_final_talk”

def scene_pre_blackwall_prep(g):
g.show_text([
“Before diving:”,
“You can rest (+50 HP), stock up at the shop, or upgrade crew.”
], title=“PREP”)
idx = g.choose([“Rest here (+50 HP)”,“Shop”,“Ready—let’s go”])
if idx == 0:
g.health = min(g.max_health(), g.health + 50)
g.energy = 100
g.show_text([“Rested. HP and energy restored.”])
elif idx == 1:
return “shop”
return “act5_blackwall”

def scene_crew_final_talk(g):
g.show_text([
“Maya: ‘After this, I’m getting out. Somewhere with no corps.’”,
“Jin: ‘I’ll be okay. I always am.’ (He doesn’t look sure.)”,
“Lina (if present): ‘Systems are green. Let’s end this.’”,
“Lucy: ‘Whatever happens in there—thank you.’”
], title=“CREW”)
g.lucy_trust += 1
return “act5_blackwall”

def scene_blackwall_dive(g):
g.show_text([
“You jack in.”,
“The world dissolves into cascading data.”,
“Lucy guides you through narrow corridors of light.”,
“Then—something notices you.”,
“A Rogue AI. Ancient. Hungry.”,
], title=“THE DIVE”)
result = g.run_combat([
{“name”:“Rogue AI Vanguard”,“hp”:80,“attack”:20,“speed”:18,“defense”:5,
“abilities”:[(“Dataspike”,1.5),(“Clone”,1.0)], “loot”:[“ai_fragment”]},
{“name”:“Blackwall Daemon”,“hp”:100,“attack”:25,“speed”:15,“defense”:8,
“abilities”:[(“Corrupt”,1.3),(“Swarm”,1.2)],
“boss”:True},
], flee_allowed=False)
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“Consumed by the Blackwall. Game over.”])
g.running = False
return None
g.story_act = max(g.story_act, 6)
return “mikoshi_approach”

# ─── ACT 6-9: MIKOSHI APPROACH AND CONFRONTATION ─────────────────────

def scene_mikoshi_approach(g):
g.story_act = max(g.story_act, 6)
g.show_text([
“ACT 6 – MIKOSHI”,
“Beyond the Blackwall: a vast digital cathedral.”,
“Rows upon rows of engrams. Thousands. Millions.”,
“Lucy: ‘This is it. Every soul Arasaka ever stole.’”,
“You see names. Dates. Faces frozen in light.”,
“‘David Martinez – Engram 4471. Active.’”,
“Lucy breaks. You give her a moment.”,
“Then the guardian awakens.”
], title=“MIKOSHI”)
return “mikoshi_guardian”

def scene_mikoshi_guardian(g):
g.show_text([
“An avatar of pure data rises.”,
“The Mikoshi Warden. Arasaka’s final defense.”,
“‘These engrams are property of Arasaka Corporation.’”,
“‘Leave or be archived.’”
], title=“THE WARDEN”)
idx = g.choose([“Fight the Warden”,“Hack past it (cyberdeck needed)”,“Talk—stall for Lucy”])
if idx == 1 and not g.has_item(“cyberdeck”):
g.show_text([“Need a cyberdeck.”])
return “mikoshi_guardian”
if idx == 1:
if g.energy >= 50:
g.energy -= 50
g.show_text([
“Jin and Lucy work together. The Warden fractures.”,
“You slip through the gap.”
])
g.story_act = max(g.story_act, 7)
return “mikoshi_core”
else:
g.show_text([“Not enough energy.”])
return “mikoshi_guardian”
elif idx == 2:
g.show_text([
“You: ‘These people had rights.’”,
“Warden: ‘Rights were voided upon contract signature.’”,
“Lucy (behind you): ‘Keep it busy!’”,
“Every second counts.”
])
# Fighting anyway
result = g.run_combat([
{“name”:“Mikoshi Warden”,“hp”:180,“attack”:28,“speed”:14,“defense”:10,
“abilities”:[(“Banish”,1.6),(“AoE”,1.3),(“Archive”,2.0)],
“boss”:True, “loot”:[“warden_data”]},
], flee_allowed=False)
if result == “hub”: return “afterlife_hub”
if not result:
g.show_text([“The Warden archives you all. Game over.”])
g.running = False
return None
g.story_act = max(g.story_act, 7)
return “mikoshi_core”

def scene_mikoshi_core(g):
g.story_act = max(g.story_act, 8)
g.show_text([
“ACT 7-9 – THE CORE”,
“Mikoshi’s center. Endless data-light.”,
“Lucy stands before the engram interface.”,
“‘We can release them all. Or…’”,
“Vector’s voice crackles through: ‘Niko. Hand over the core access.’”,
“‘Militech will manage the engrams properly.’”,
“Lucy: ‘Properly. She means sell them.’”,
“Tanaka (if ally): ‘Free them. Please.’”,
“You have all three keys. The choice is yours.”
], title=“THE CHOICE”)
g.story_act = max(g.story_act, 9)
return “final_choice”

def scene_final_choice(g):
g.story_act = max(g.story_act, 10)
lucy_bonus = “ (Lucy approves)” if g.lucy_trust >= 2 else “”
tanaka_bonus = “ (Tanaka urges this)” if g.check_flag(“tanaka_ally”) else “”
g.show_text([
“ACT 10 – THE FINAL CHOICE”,
“The engrams of ten thousand souls wait.”,
“David Martinez waits.”,
“What do you do?”
], title=“ACT 10”)
idx = g.choose([
f”FREE THEM ALL{lucy_bonus}{tanaka_bonus}”,
“SELL to Militech (Vector’s deal)”,
“DESTROY everything—no corp ever touches them”,
“TAKE ONE ENGRAM (merge with the net)”,
])
if idx == 0:   return “ending_legend”
elif idx == 1: return “ending_sellout”
elif idx == 2: return “ending_purge”
elif idx == 3: return “ending_merge”
else:          return “final_choice”

# ─── ENDINGS ────────────────────────────────────────────────────────

def scene_ending_legend(g):
g.show_text([
“ENDING: GHOST LEGEND”,
“”,
“You release the engrams.”,
“Ten thousand souls flood the net.”,
“David Martinez’s data dissolves—finally free.”,
“Lucy smiles. Truly. For the first time in years.”,
“‘Thank you, Niko.’”,
“She fades with the others—going where she always wanted.”,
“The net shimmers. Night City glows.”,
“Your crew stands in the ruins of the tower.”,
“Maya: ‘So… what now?’”,
“You: ‘No idea. But it’s ours to figure out.’”,
“”,
“You became what Night City needed.”,
“Not a corpo. Not a merc.”,
“A ghost who chose to be real.”,
], title=“LEGEND END”)
g.running = False
return None

def scene_ending_sellout(g):
g.show_text([
“ENDING: CORPO PUPPET”,
“”,
“You hand the core to Vector.”,
“Militech pays you 500,000 eddies.”,
“More than you’ve ever dreamed.”,
“Lucy screams. You don’t look back.”,
“She disappears—archived.”,
“Your crew won’t meet your eyes.”,
“Maya leaves that night.”,
“Jin follows.”,
“You’re rich.”,
“You’re alone.”,
“Night City doesn’t remember your name.”,
“Neither will you, eventually.”,
], title=“SELLOUT END”)
g.running = False
return None

def scene_ending_purge(g):
g.show_text([
“ENDING: ASHES”,
“”,
“You destroy the core.”,
“Every engram—gone.”,
“No corp will ever touch them.”,
“Lucy: ‘Even David?’”,
“You: ‘…Even David.’”,
“She closes her eyes.”,
“The explosion tears through the net.”,
“In the physical world—”,
“the Arasaka ruins go dark forever.”,
“You and Lucy walk out through the Badlands.”,
“Neither of you speaks.”,
“Some things can’t be undone.”,
“But neither can they be taken.”,
], title=“ASHES END”)
g.running = False
return None

def scene_ending_merge(g):
g.show_text([
“ENDING: DIGITAL GHOST”,
“”,
“You upload yourself.”,
“Your body slumps in the chair.”,
“Inside: infinite.”,
“You find David Martinez.”,
“He looks at you: ‘Choom. You made it.’”,
“You protect the engrams from inside.”,
“No key. No access. No corp.”,
“Just you and ten thousand souls”,
“drifting beyond the Blackwall.”,
“Night City looks different from out here.”,
“Smaller. Brighter.”,
“Beautiful.”,
], title=“GHOST END”)
g.running = False
return None

# ─────────────────────────────────────────────────────────────────────

# SIDE CONTENT (Original + expanded)

# ─────────────────────────────────────────────────────────────────────

def scene_afterlife_hub(g):
rep_str  = f”A:{g.rep_arasaka} M:{g.rep_militech} V:{g.rep_voodoo}”
crew_str = “, “.join(g.crew) if g.crew else “None”
g.show_text([
“THE AFTERLIFE”,
f”HP: {g.health}/{g.max_health()}  Eddies: {g.eddies}”,
f”Level: {g.level}  XP: {g.xp}/{g.xp_to_level()}”,
f”Act: {g.story_act}/10”,
f”Rep: {rep_str}”,
f”Crew: {crew_str}”,
], title=“HUB”)
act_label = f”Continue Act {g.story_act}” if g.story_act > 0 else “Start Story”
idx = g.choose([
act_label,
“Side Jobs (Fixer)”,
“Bartender”,
“Shop”,
“Crew”,
“Save Game”,
“Hit the Street”,
])
if idx == 0:
return _story_continue(g)
elif idx == 1: return “fixer_gigs”
elif idx == 2: return “bartender”
elif idx == 3: return “shop”
elif idx == 4: return “crew_hub”
elif idx == 5:
ok = g.save_game()
g.show_text([“Game saved!” if ok else “Save failed.”])
return “afterlife_hub”
elif idx == 6: return “street”
return “afterlife_hub”

def _story_continue(g):
“”“Route player to the right act scene.”””
act_map = {
0: “prologue”,
1: “after_heist”,
2: “act2_hub”,
3: “act3_key_hunt”,
4: “act4_night_city_burns”,
5: “act5_blackwall”,
6: “mikoshi_approach”,
7: “mikoshi_core”,
8: “mikoshi_core”,
9: “final_choice”,
10: “final_choice”,
}
return act_map.get(g.story_act, “prologue”)

def scene_street(g):
if random.random() < 0.25 and (g.rep_arasaka < -4 or g.rep_militech < -4):
show_message(“Assassins! They found you!”)
result = g.run_combat([
(“Corpo Assassin”, 55, 15, 14, 3),
(“Corpo Assassin”, 55, 15, 14, 3),
])
if result == “hub”: return “afterlife_hub”
if result:
show_message(“You survived. Barely.”)
else:
g.running = False
return None
g.show_text([
“Night City streets. Rain. Neon.”,
“Where to?”
], title=“STREETS”)
idx = g.choose([
“Afterlife”,
“Combat Zone”,
“Kabuki Market”,
“Pacifica”,
“Watson District”
])
if idx == 0: return “afterlife_hub”
elif idx == 1: return “combat_zone”
elif idx == 2: return “kabuki”
elif idx == 3: return “pacifica_side”
elif idx == 4: return “watson_district”
return “afterlife_hub”

def scene_watson_district(g):
g.show_text([
“Watson. Industrial grime.”,
“A new fixer contact—Yuki—waves you over.”,
“‘Got a job. Gang war. Need a mediator or a shooter.’”
], title=“WATSON”)
idx = g.choose([“Mediate the gang war”,“Shoot your way through”,“Ignore, look around”])
if idx == 0:
success = random.random() < 0.5 + g.street_cred * 0.05
if success:
g.eddies += 1500
g.change_rep(“street”, 2)
g.show_text([“War averted. +1500 eddies.”])
else:
g.show_text([“Negotiation failed. They start shooting.”])
g.health = max(1, g.health - 20)
elif idx == 1:
result = g.run_combat([
(“Gang Banger”, 30, 9, 10, 0),
(“Gang Banger”, 30, 9, 10, 0),
(“Gang Leader”,  55, 14, 12, 2, [(“Intimidate”, 1.0)]),
])
if result is True:
g.eddies += 2000
g.change_rep(“street”, 1)
g.show_text([”+2000 eddies.”])
elif result is False:
g.running = False
return None
else:
roll = random.choice([“medkit”,“junk”,“cyberdeck”,“synthetic_meat”])
g.add_item(roll)
g.show_text([f”You find: {roll}”])
return “afterlife_hub”

def scene_combat_zone(g):
g.show_text([
“Combat Zone. Scavs. Wraiths. Desperate people.”,
“You spot a solo cornered by three thugs.”,
“She’s bleeding. Holding them off with a broken bottle.”
], title=“COMBAT ZONE”)
idx = g.choose([“Help her”,“Loot nearby”,“Join the thugs (–rep)”])
if idx == 0:
result = g.run_combat([
(“Thug”,        28, 8, 9, 0),
(“Thug”,        28, 8, 9, 0),
(“Thug Leader”, 42, 11, 11, 1),
])
if result == “hub”: return “afterlife_hub”
if result:
if “Maya” not in g.crew:
g.add_crew(“Maya”)
g.show_text([
“She catches her breath.”,
“‘Name’s Maya. I owe you one.’”,
“‘I’m a solo. Looking for a crew.’”,
“‘Interested?’”,
])
return “maya_recruit”
else:
g.show_text([“You save a stranger. They nod and disappear.”])
g.change_rep(“street”, 1)
else:
g.running = False
return None
elif idx == 1:
loot = random.choice([“medkit”,“junk”,“synthetic_meat”,“MaxDoc”,“scrap_eddies”])
if loot == “scrap_eddies”:
g.eddies += 150
g.show_text([“You find 150 loose eddies in a crate.”])
else:
g.add_item(loot)
g.show_text([f”Found: {loot}”])
else:
g.change_rep(“street”, -2)
g.show_text([“The thugs take the solo down. They look at you with suspicion.”, “You get nothing.”])
return “afterlife_hub”

def scene_maya_recruit(g):
idx = g.choose([“Take her on as crew”,“Offer her a single job”,“Politely decline”])
if idx == 0:
g.show_text([“Maya: ‘Smart choice. You won’t regret it.’”])
elif idx == 1:
g.show_text([“Maya: ‘One job. Sure. Let’s see how you work.’”])
else:
g.show_text([“Maya: ‘Your loss, choom.’”])
g.crew.remove(“Maya”) if “Maya” in g.crew else None
return “afterlife_hub”

def scene_kabuki(g):
g.show_text([
“Kabuki Market. Steam. Spices. Neon.”,
“A vendor whispers: ‘Looking for a netrunner?’”,
“You also notice a black-market cyberware stall.”
], title=“KABUKI”)
idx = g.choose([
“Follow the vendor (find Jin)”,
“Check the cyberware stall”,
“Buy noodles”,
“Just walk around”
])
if idx == 0: return “vendor_netrunner”
elif idx == 1: return “kabuki_cyberware”
elif idx == 2:
g.show_text([“Best noodles in Night City. +5 morale and +10 HP.”])
g.health = min(g.max_health(), g.health + 10)
return “afterlife_hub”
else:
roll = random.choice([“junk”,“synthetic_meat”,“nothing”])
if roll == “nothing”:
g.show_text([“Nothing interesting today.”])
else:
g.add_item(roll)
g.show_text([f”Found on the ground: {roll}”])
return “afterlife_hub”

def scene_kabuki_cyberware(g):
g.show_text([
“Black market stall. Questionable but functional.”,
“Cyberdeck (1800), Optical Camo (1200), Subdermal Grip (800)”
], title=“CYBERWARE”)
idx = g.choose([“Cyberdeck (1800)”,“Optical Camo (1200)”,“Subdermal Grip (800)”,“Leave”])
prices = [1800, 1200, 800]
items  = [“cyberdeck”,“optical_camo”,“subdermal_grip”]
if idx < 3:
cost = prices[idx]
item = items[idx]
if g.eddies >= cost:
g.eddies -= cost
g.add_item(item)
g.show_text([f”Bought {item}.”])
else:
g.show_text([“Not enough eddies.”])
return “afterlife_hub”

def scene_vendor_netrunner(g):
g.show_text([
“The vendor leads you to a basement.”,
“A hooded figure. Dim terminal glow.”,
“‘Jin. Best netrunner in Kabuki.’”,
“‘Heard you need help. What’s the job?’”
], title=“JIN”)
if “Jin” in g.crew:
g.show_text([“Jin’s already with you. He waves awkwardly.”])
return “afterlife_hub”
idx = g.choose([“Hire Jin (500 eddies)”,“Promise future cut”,“Leave”])
if idx == 0:
if g.eddies >= 500:
g.eddies -= 500
g.add_crew(“Jin”)
g.show_text([“Jin: ‘Alright, choom. Don’t get me killed.’”])
else:
g.show_text([“Not enough eddies.”])
elif idx == 1:
g.set_flag(“debt_jin”)
g.add_crew(“Jin”)
g.show_text([“Jin: ‘Fine. But I remember debts.’”])
return “afterlife_hub”

def scene_fixer_gigs(g):
g.show_text([
“Fixer: ‘Work? Always.’,”,
“1. Data extraction from a gang hideout”,
“2. Protect a corpo exec overnight”,
“3. Find a missing ripperdoc”
], title=“SIDE JOBS”)
idx = g.choose([“Data Extraction”,“Corpo Guard”,“Find the Ripperdoc”,“Skip”])
if idx == 0: return “gig_data_extraction”
elif idx == 1: return “gig_corpo_guard”
elif idx == 2: return “gig_ripperdoc”
else: return “afterlife_hub”

def scene_gig_data_extraction(g):
g.show_text([“Gang hideout. Three guards. You need the data shard.”, “Stealth or force?”], title=“DATA GIG”)
idx = g.choose([“Stealth (optical camo needed)”,“Force through”,“Hack the door (cyberdeck)”])
if idx == 0:
if g.has_item(“optical_camo”) or g.equipped_cyberware == “optical_camo”:
g.eddies += 2000
g.change_rep(“street”, 2)
g.show_text([“Ghost operation. In and out. +2000 eddies.”])
else:
g.show_text([“No camo. You have to fight.”])
return “gig_data_fight”
elif idx == 1:
return “gig_data_fight”
else:
if g.has_item(“cyberdeck”):
g.eddies += 2000
g.show_text([“Hacked the lock. Clean extraction. +2000 eddies.”])
else:
g.show_text([“No cyberdeck.”])
return “gig_data_fight”
return “afterlife_hub”

def scene_gig_data_fight(g):
result = g.run_combat([
(“Gang Member”, 30, 9, 10, 0),
(“Gang Member”, 30, 9, 10, 0),
(“Gang Enforcer”, 50, 13, 11, 2),
])
if result == “hub”: return “afterlife_hub”
if result:
g.eddies += 2000
g.change_rep(“street”, 1)
g.show_text([“Data secured. +2000 eddies.”])
else:
g.show_text([“Mission failed. Game over.”])
g.running = False
return None
return “afterlife_hub”

def scene_gig_corpo_guard(g):
g.show_text([
“Protect Exec Yama overnight.”,
“Three attempts on his life expected.”,
“You stay alert.”
], title=“GUARD GIG”)
result = g.run_combat([
{“name”:“Assassin”,  “hp”:50,“attack”:14,“speed”:16,“defense”:3, “loot”:[“thermal_katana”]},
{“name”:“Assassin”,  “hp”:50,“attack”:14,“speed”:16,“defense”:3},
{“name”:“Hitsquad”,  “hp”:70,“attack”:18,“speed”:13,“defense”:4,
“abilities”:[(“Coordinated Strike”,1.4)]},
])
if result == “hub”: return “afterlife_hub”
if result:
g.eddies += 3500
g.change_rep(“street”, 2)
g.show_text([“Yama survived. +3500 eddies.”])
else:
g.show_text([“Yama is killed. Game over.”])
g.running = False
return None
return “afterlife_hub”

def scene_gig_ripperdoc(g):
g.show_text([
“Ripperdoc Vik was taken by Scavs.”,
“You track him to a building in Arroyo.”
], title=“RIPPERDOC”)
result = g.run_combat([
(“Scav”,         30, 8,  9, 0),
(“Scav”,         30, 8,  9, 0),
(“Scav Leader”,  55, 13, 12, 2, [(“Shiv Storm”,1.3)]),
])
if result == “hub”: return “afterlife_hub”
if result:
g.eddies += 1500
g.show_text([
“Vik is alive. ‘Thank you.’”,
“He upgrades your body for free.”,
“+1 DEF, +20 max HP.”
])
g.health = min(g.max_health() + 20, g.health + 20)
g.change_rep(“street”, 2)
else:
g.show_text([“Vik doesn’t make it. Game over.”])
g.running = False
return None
return “afterlife_hub”

def scene_bartender(g):
g.show_text([
“Bartender Claire pours without looking up.”,
“‘What’ll it be? Got food too.’”,
“She slides a menu.”
], title=“BARTENDER”)
idx = g.choose([
“Synthetic meat (20 eddies, +20HP)”,
“Real burger (50 eddies, +35HP)”,
“Trauma kit (200 eddies, +80HP)”,
“Just talk”,
“Leave”
])
if idx == 0:
if g.eddies >= 20:
g.eddies -= 20
g.health = min(g.max_health(), g.health + 20)
g.show_text([“Synthetic meat. Tastes like chemicals. +20 HP.”])
else:
g.show_text([“Not enough.”])
elif idx == 1:
if g.eddies >= 50:
g.eddies -= 50
g.health = min(g.max_health(), g.health + 35)
g.show_text([“A real burger. Actually amazing. +35 HP.”])
else:
g.show_text([“Not enough.”])
elif idx == 2:
if g.eddies >= 200:
g.eddies -= 200
g.add_item(“trauma_kit”)
g.show_text([“Trauma kit. For when it gets bad.”])
else:
g.show_text([“Not enough.”])
elif idx == 3:
rumor = random.choice([
“Claire: ‘Heard Militech’s pushing into Pacifica. Bad news.’”,
“Claire: ‘Someone saw a ghost in the net. Real ghost. Silver hair.’”,
“Claire: ‘Smasher’s been rebuilt again. Third time.’”,
“Claire: ‘The Voodoo Boys are planning something big.’”,
“Claire: ‘NetWatch is losing control of the Blackwall.’”,
])
g.show_text([rumor])
return “afterlife_hub”

def scene_shop(g):
g.show_text([“The fixer’s private shop.”, “Military surplus. No questions.”], title=“SHOP”)
items = [
(“Smart Rifle”,     2000, “smart_rifle”),
(“Thermal Katana”,  1800, “thermal_katana”),
(“Mono Wire”,        900, “mono_wire”),
(“Cyberdeck”,       1800, “cyberdeck”),
(“Optical Camo”,    1200, “optical_camo”),
(“Medkit”,           100, “medkit”),
(“MaxDoc”,           150, “MaxDoc”),
(“Stim”,             200, “Stim”),
]
labels = [f”{name} ({price})” for name, price, _ in items] + [“Leave”]
idx = g.choose(labels, title=“SHOP”)
if idx < len(items):
name, price, item_id = items[idx]
if g.eddies >= price:
g.eddies -= price
g.add_item(item_id)
g.show_text([f”Bought: {name}.”])
else:
g.show_text([f”Need {price} eddies.”])
return “afterlife_hub”

def scene_crew_hub(g):
if not g.crew:
g.show_text([“No crew yet.”, “Find Maya in the Combat Zone,”, “Jin in Kabuki.”])
return “afterlife_hub”
g.show_text([
f”Crew: {’, ’.join(g.crew)}”,
f”Loyalty: {g.crew_loyalty}%”,
“Select a crew member to talk.”
], title=“CREW”)
choices = g.crew + [“Back”]
idx = g.choose(choices)
if idx == -1 or idx == len(g.crew):
return “afterlife_hub”
member = g.crew[idx]
return f”talk_{member.lower()}”

def scene_talk_maya(g):
g.show_text([
“Maya: ‘You’re alright, Niko.’”,
“‘Not many people would’ve stopped for me.’”,
“She looks out at the city.”,
“‘After all this—I want to find somewhere quiet.’”
], title=“MAYA”)
idx = g.choose([”‘Come with me, then.’”,”‘You’ve earned it.’”,“Just listen”])
if idx == 0:
if g.romance != “maya”:
g.romance = “maya”
g.show_text([“Maya meets your eyes.”, “‘Yeah. Okay. Together.’”])
g.crew_loyalty = min(100, g.crew_loyalty + 15)
elif idx == 1:
g.show_text([“Maya nods. ‘Thanks, choom.’”])
g.crew_loyalty = min(100, g.crew_loyalty + 5)
return “afterlife_hub”

def scene_talk_jin(g):
g.show_text([
“Jin: ‘Niko. You know what I like about you?’”,
“‘You don’t pretend the net isn’t dangerous.’”,
“‘Most people who hire netrunners think it’s like turning on a light.’”,
“‘It’s not. It’s like breathing underwater.’”
], title=“JIN”)
idx = g.choose([”‘You’re the best I’ve seen.’”,“Ask about the Blackwall”,“Just nod”])
if idx == 0:
g.show_text([“Jin: ‘Flattery gets you everywhere. And you owe me a drink.’”])
g.crew_loyalty = min(100, g.crew_loyalty + 5)
elif idx == 1:
g.show_text([
“Jin: ‘The Blackwall? I’ve touched it twice.’”,
“‘Both times, something touched back.’”,
“‘Don’t go in without me.’”
])
return “afterlife_hub”

def scene_talk_lina(g):
g.show_text([
“Lina wipes grease off her hands.”,
“‘Gear’s prepped. You’re running at… seventy percent.’”,
“‘Want me to fix that?’”
], title=“LINA”)
idx = g.choose([“Install cyberware”,“Tune weapons (free, +2 ATK next fight)”,“Just chat”])
if idx == 0:
cyberware = [c for c in g.inventory if c in [“cyberdeck”,“optical_camo”,“subdermal_grip”]]
if cyberware:
ci = g.choose(cyberware, “Install which?”)
if ci != -1:
g.equipped_cyberware = cyberware[ci]
g.show_text([f”Lina installs {cyberware[ci]}.”])
else:
g.show_text([“Nothing to install.”])
elif idx == 1:
g.set_flag(“tuned_weapons”)
g.show_text([“Lina tunes your gear. ‘Should hit harder next fight.’”])
return “afterlife_hub”

def scene_pacifica_side(g):
g.show_text([
“Pacifica. Half-constructed towers. Feral synths.”,
“The Voodoo Boys run things here.”,
“A preacher on the corner: ‘The net is God. Beware the Blackwall.’”,
], title=“PACIFICA”)
idx = g.choose([
“Talk to Voodoo contact”,
“Explore the ruins”,
“Visit the beach (rest)”,
“Back”
])
if idx == 0: return “voodoo_side”
elif idx == 1: return “pacifica_ruins”
elif idx == 2:
g.show_text([“The sea doesn’t care about Night City.”, “+30 HP restored.”])
g.health = min(g.max_health(), g.health + 30)
g.energy = 100
return “afterlife_hub”

def scene_voodoo_side(g):
g.show_text([
“Voodoo Boys contact: ‘You’re not from here.’”,
“‘We have work. A NetWatch relay uplink. Destroy it.’”,
“‘Payment: 3000 eddies and our respect.’”
], title=“VOODOO JOB”)
idx = g.choose([“Accept”,“Decline”,“Ask about Sable”])
if idx == 0:
result = g.run_combat([
(“NetWatch Tech”,   30, 8, 10, 0),
(“NetWatch Guard”,  45, 13, 12, 2),
])
if result == “hub”: return “afterlife_hub”
if result:
g.eddies += 3000
g.change_rep(“voodoo”, 2)
g.change_rep(“netwatch”, -2)
g.show_text([“Uplink destroyed. 3000 eddies.”])
else:
g.show_text([“Mission failed.”])
elif idx == 2:
g.show_text([
“Contact: ‘Sable sees everything.’”,
“‘If she wanted you dead, you’d know.’”,
“‘She’s watching. That means she’s interested.’”
])
return “afterlife_hub”

def scene_pacifica_ruins(g):
g.show_text([“Exploring the half-built towers.”], title=“RUINS”)
roll = random.random()
if roll < 0.3:
g.show_text([“You find a stash: medkit and 500 eddies.”])
g.add_item(“medkit”)
g.eddies += 500
elif roll < 0.6:
g.show_text([“Scavs ambush you!”])
result = g.run_combat([
(“Scav”, 30, 8, 9, 0),
(“Scav”, 30, 8, 9, 0),
])
if result is False:
g.show_text([“Overwhelmed. Game over.”])
g.running = False
return None
else:
g.show_text([“An old netrunner den. Dead terminals. A single note:”, “‘We were here. We mattered. – L’”])
g.lucy_trust += 1
return “afterlife_hub”

# ─── SCENE MAP ───────────────────────────────────────────────────────

SCENE_MAP = {
# Menus
“start_menu”:           scene_start_menu,
# Acts
“prologue”:             scene_prologue,
“messages_intro”:       scene_messages_intro,
“afterlife_intro”:      scene_afterlife_intro,
“heist_plan”:           scene_heist_plan,
“crew_recruit_hub”:     scene_crew_recruit_hub,
“heist_alone”:          scene_heist_alone,
“heist_combat”:         scene_heist_combat,
“after_heist”:          scene_after_heist,
“act2_hub”:             scene_act2_hub,
“pacifica_first”:       scene_pacifica_first,
“lucy_deal”:            scene_lucy_deal,
“militech_leak”:        scene_militech_leak,
“hiro_confront”:        scene_hiro_confront,
“act3_key_hunt”:        scene_act3_key_hunt,
“key_militech”:         scene_key_militech,
“relay_infiltrate”:     scene_relay_infiltrate,
“relay_hack”:           scene_relay_hack,
“relay_buy”:            scene_relay_buy,
“militech_key_mission”: scene_militech_key_mission,
“key_voodoo”:           scene_key_voodoo,
“netwatch_purge”:       scene_netwatch_purge,
“voodoo_brawl”:         scene_voodoo_brawl,
“key_arasaka”:          scene_key_arasaka,
“arasaka_storm”:        scene_arasaka_storm,
“arasaka_diplomacy”:    scene_arasaka_diplomacy,
“arasaka_trap”:         scene_arasaka_trap,
“act4_night_city_burns”:scene_act4_night_city_burns,
“save_rook”:            scene_save_rook,
“militech_ambush”:      scene_militech_ambush,
“act4_assault”:         scene_act4_assault,
“arasaka_tower”:        scene_arasaka_tower,
“tower_lobby”:          scene_tower_lobby,
“tower_shaft”:          scene_tower_shaft,
“tower_hack_grid”:      scene_tower_hack_grid,
“tower_sublevel”:       scene_tower_sublevel,
“tower_boss”:           scene_tower_boss,
“tower_ending”:         scene_tower_ending,
“act5_blackwall”:       scene_act5_blackwall,
“pre_blackwall_prep”:   scene_pre_blackwall_prep,
“crew_final_talk”:      scene_crew_final_talk,
“blackwall_dive”:       scene_blackwall_dive,
“mikoshi_approach”:     scene_mikoshi_approach,
“mikoshi_guardian”:     scene_mikoshi_guardian,
“mikoshi_core”:         scene_mikoshi_core,
“final_choice”:         scene_final_choice,
# Endings
“ending_legend”:        scene_ending_legend,
“ending_sellout”:       scene_ending_sellout,
“ending_purge”:         scene_ending_purge,
“ending_merge”:         scene_ending_merge,
# Hub + Side
“afterlife_hub”:        scene_afterlife_hub,
“street”:               scene_street,
“watson_district”:      scene_watson_district,
“combat_zone”:          scene_combat_zone,
“maya_recruit”:         scene_maya_recruit,
“kabuki”:               scene_kabuki,
“kabuki_cyberware”:     scene_kabuki_cyberware,
“vendor_netrunner”:     scene_vendor_netrunner,
“fixer_gigs”:           scene_fixer_gigs,
“gig_data_extraction”:  scene_gig_data_extraction,
“gig_data_fight”:       scene_gig_data_fight,
“gig_corpo_guard”:      scene_gig_corpo_guard,
“gig_ripperdoc”:        scene_gig_ripperdoc,
“bartender”:            scene_bartender,
“shop”:                 scene_shop,
“shop_heist”:           scene_shop,
“crew_hub”:             scene_crew_hub,
“talk_maya”:            scene_talk_maya,
“talk_jin”:             scene_talk_jin,
“talk_lina”:            scene_talk_lina,
“pacifica_side”:        scene_pacifica_side,
“voodoo_side”:          scene_voodoo_side,
“pacifica_ruins”:       scene_pacifica_ruins,
# Stubs routing to act2
“act2_militech”:        scene_act2_hub,
“act2_underground”:     scene_act2_hub,
“act2_double”:          scene_act2_hub,
“act2_investigation”:   scene_pacifica_first,
“act2_prep”:            scene_shop,
}

def run_scene(g, name):
fn = SCENE_MAP.get(name)
if fn:
return fn(g)
g.show_text([f”Unknown scene: {name}”, “Returning to hub.”])
return “afterlife_hub”

# ─────────────────────────────────────────────────────────────────────

# MAIN LOOP

# ─────────────────────────────────────────────────────────────────────

def main():
game = Game()
while game.running:
btn = wait_btn(0.01)
if btn == “KEY1”:
game.open_inventory()
continue
elif btn == “KEY2”:
game.scene = “afterlife_hub”
continue
next_scene = run_scene(game, game.scene)
if next_scene is None:
break
game.scene = next_scene
GPIO.cleanup()
LCD.LCD_Clear()

if **name** == “**main**”:
main()
