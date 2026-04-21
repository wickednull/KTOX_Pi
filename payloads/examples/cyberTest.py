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
# tuple: (name, hp, atk, spd=10, def=0, abilities=[], boss=False, loot=[])
name, hp, atk = e[0], e[1], e[2]
spd  = e[3] if len(e) > 3 else 10
dfn  = e[4] if len(e) > 4 else 0
ab   = e[5] if len(e) > 5 else []
boss = e[6] if len(e) > 6 else False
loot = e[7] if len(e) > 7 else []
return Combatant(name, hp, atk, spd, dfn, ab, boss, loot)

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
        payload = dict(self.__dict__)
        payload["_gig_board"] = {k: v["done"] for k, v in GIG_BOARD.items()}
        with open(SAVE_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        return True
    except:
        return False

def load_game(self):
    try:
        with open(SAVE_FILE, "r") as f:
            data = json.load(f)
        gig_data = data.pop("_gig_board", {})
        for k, done in gig_data.items():
            if k in GIG_BOARD:
                GIG_BOARD[k]["done"] = done
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

# =============================================================================

# START MENU

# =============================================================================

def scene_start_menu(g):
g.show_text([
“CYBERPUNK 2087”,
“”,
“Night City never sleeps.”,
“Neither do the dead.”,
“”,
“v2.0  |  wickednull”,
], title=“TITLE”)
idx = g.choose([“New Game”, “Continue”, “About”])
if idx == 0:
g.**init**()
return “prologue”
elif idx == 1:
if g.load_game():
g.show_text([“Save loaded.”, f”Welcome back, {g.player_name}.”])
return g.scene
g.show_text([“No save found.”, “Starting fresh.”])
return “prologue”
elif idx == 2:
g.show_text([
“Cyberpunk 2087”,
“A full-length RPG for”,
“Raspberry Pi Zero 2W”,
“with Waveshare 1.44 LCD”,
“”,
“10 acts. Multiple endings.”,
“Real choices. Real consequences.”,
“”,
“author: wickednull”,
])
return “start_menu”
return “start_menu”

# =============================================================================

# PROLOGUE  –  WHO IS NIKO?

# =============================================================================

def scene_prologue(g):
g.show_text([
“NIGHT CITY  –  2087”,
“”,
“The war ended ten years ago.”,
“Arasaka lost. Militech won.”,
“The corps call it the Reconstruction.”,
“The streets call it something else.”,
“”,
“You are NIKO.”,
“Twenty-three years old.”,
“No implants. No rep. No corp backing.”,
“Just a cracked neural port,”,
“a secondhand pistol,”,
“and 800 eddies of debt”,
“to a man named Rook.”,
], title=“PROLOGUE”)
g.show_text([
“Your agent—a scratched slab of plastic”,
“you found in a dumpster—buzzes.”,
“”,
“ROOK:  Afterlife. Now.”,
“       Don’t make me come get you.”,
“”,
“Another message. No sender ID.”,
“Encrypted so hard Jin couldn’t crack it.”,
“Three words:”,
“”,
“       I  NEED  YOU”,
“”,
“You stare at the ceiling of your capsule.”,
“800 eddies. The debt won’t pay itself.”,
], title=“PROLOGUE”)
idx = g.choose([
“Head to the Afterlife”,
“Try to crack the mystery message first”,
“Check your gear before anything”,
])
if idx == 0:
return “afterlife_intro”
elif idx == 1:
g.show_text([
“You spend an hour on the message.”,
“The encryption is military-grade.”,
“You get one fragment before it re-locks:”,
“”,
“       …MIKOSHI…”,
“”,
“You don’t know what that means.”,
“But it sits in your chest like a coal.”,
“You head to the Afterlife.”,
])
g.set_flag(“saw_mikoshi_hint”)
return “afterlife_intro”
else:
g.show_text([
“Pistol: 6 rounds, worn grip.”,
“Jacket: three bullet holes, patched badly.”,
“Eddies: 500. Minus the 800 you owe Rook.”,
“”,
“You’re ready as you’re going to get.”,
“Which isn’t saying much.”,
])
return “afterlife_intro”

# =============================================================================

# ACT 1  –  THE HEIST

# =============================================================================

def scene_afterlife_intro(g):
g.show_text([
“ACT 1  –  THE HEIST”,
“”,
“The Afterlife.”,
“Legend has it this bar was named after”,
“the mercs who drank here and never came back.”,
“The cocktails are named after them too.”,
“”,
“A David Martinez sits untouched on the bar.”,
“Nobody orders it. Nobody throws it out.”,
“”,
“Rook is in the back booth.”,
“He always is.”,
“Fifty years old and looks seventy.”,
“Night City does that to people.”,
], title=“ACT 1”)
g.show_text([
“ROOK:  ‘Finally. Sit down.’”,
“”,
“‘Militech is moving a prototype chip’,”,
“‘called the Ghost Relic.’,”,
“‘Tomorrow night. Private convoy.’,”,
“‘Four guards, one aerial drone,’,”,
“‘scrambled comms.’”,
“”,
“‘You grab it, I pay you 10,000 eddies.’”,
“‘You ask questions, I find someone else.’”,
“”,
“He slides a data chip across the table.”,
“Convoy route. Guard rotation.”,
“Everything you need and nothing you don’t.”,
], title=“ACT 1”)
idx = g.choose([
“Take the job”,
“Ask what the chip does”,
“Push for more money”,
“Walk out”,
])
if idx == 0:
g.set_flag(“accepted_heist”)
return “heist_plan”
elif idx == 1:
g.show_text([
“Rook’s eyes go flat.”,
“‘It copies neural engrams.’,”,
“‘Without Arasaka’s method.’,”,
“‘Without Arasaka’s permission.’,”,
“‘That’s all you need to know.’”,
“”,
“He taps the data chip.”,
“‘Well?’”,
])
g.set_flag(“knows_chip_value”)
g.set_flag(“accepted_heist”)
return “heist_plan”
elif idx == 2:
g.show_text([
“You say 15,000.”,
“”,
“Rook doesn’t blink.”,
“‘12. Final. You’re 800 in the hole to me”,
“and you haven’t worked in six weeks.”,
“You don’t negotiate from that chair.’”,
“”,
“He’s right. You take 12.”,
])
g.set_flag(“negotiated_pay”)
g.set_flag(“accepted_heist”)
return “heist_plan”
else:
g.show_text([
“You stand up.”,
“Rook watches you walk to the door.”,
“”,
“You make it four steps before”,
“your agent buzzes:”,
“BANK: FINAL NOTICE – 800 EDDIES”,
“”,
“You turn around.”,
“Rook is already looking at his drink.”,
“‘Sit down, Niko.’”,
])
g.set_flag(“accepted_heist”)
return “heist_plan”

def scene_heist_plan(g):
pay_note = “12,000” if g.check_flag(“negotiated_pay”) else “10,000”
g.show_text([
f”The job: {pay_note} eddies.”,
“The convoy: tomorrow night, Route 7.”,
“”,
“You have one day to get ready.”,
“Options:”,
“  - Go in alone (risky, clean split)”,
“  - Find crew (safer, shared pay)”,
“  - Scout the route first”,
“  - Gear up at the shop”,
“”,
“What’s your move?”,
], title=“HEIST PREP”)
idx = g.choose([
“Find crew (Combat Zone + Kabuki)”,
“Go alone – keep all the pay”,
“Scout Route 7 first”,
“Hit the shop”,
])
if idx == 0:
return “heist_crew_hunt”
elif idx == 1:
return “heist_solo_warning”
elif idx == 2:
g.show_text([
“You spend three hours on the overpass”,
“watching Route 7.”,
“”,
“Guard rotation: every 8 minutes.”,
“The drone banks west at minute 4.”,
“That’s your window.”,
“”,
“Choke point: the underpass at marker 7-C.”,
“Force the convoy to stop there,”,
“you own the fight.”,
“”,
“Scout complete. You’ll hit harder now.”,
])
g.set_flag(“scouted_convoy”)
return “heist_plan”
else:
return “shop”

def scene_heist_solo_warning(g):
g.show_text([
“Going alone means:”,
“  - Full 10-12k pay”,
“  - No backup”,
“  - Four guards plus a drone”,
“”,
“You’ve survived worse.”,
“Probably.”,
“”,
“You check your pistol.”,
“Six rounds.”,
“You’re going to need more than that.”,
], title=“SOLO RUN”)
idx = g.choose([
“Do it anyway”,
“Actually, find some crew first”,
])
if idx == 0:
return “heist_alone”
return “heist_crew_hunt”

def scene_heist_crew_hunt(g):
g.show_text([
“You know of two people”,
“who might take this job.”,
“”,
“MAYA – a solo in the Combat Zone.”,
“Good with a rifle. Has a grudge”,
“against Militech specifically.”,
“”,
“JIN – a netrunner in Kabuki.”,
“Can kill a drone from three blocks away.”,
“Costs 500 eddies upfront.”,
“”,
“Who do you find first?”,
], title=“FIND CREW”)
idx = g.choose([
“Find Maya (Combat Zone)”,
“Find Jin (Kabuki)”,
“Find both before hitting the convoy”,
“Forget crew – go now”,
])
if idx == 0:
return “combat_zone”
elif idx == 1:
return “kabuki”
elif idx == 2:
g.set_flag(“want_both_crew”)
return “combat_zone”
else:
return “heist_alone”

# ── HEIST: SOLO PATH ────────────────────────────────────────────────

def scene_heist_alone(g):
g.show_text([
“NIGHT  –  ROUTE 7”,
“”,
“22:00. The rain started an hour ago.”,
“That’s good. Noise cover.”,
“Bad visibility for the drone.”,
“”,
“The convoy pulls to the overpass.”,
“Scheduled stop: maintenance checkpoint.”,
“Guards rotate. Window: eight minutes.”,
“”,
“You’re in position.”,
“Three guards. One driver in the cab.”,
“The chip is in the rear transport.”,
“”,
“How do you go in?”,
], title=“THE HEIST”)
idx = g.choose([
“Straight in – take the guards fast”,
“Wait for the guard rotation gap”,
“Disable the drone first (cyberdeck)”,
“Hit the lights – cut the generator”,
])
if idx == 0:
return “heist_solo_direct”
elif idx == 1:
g.show_text([
“You watch the rotation.”,
“Minute three: the north guard turns.”,
“Six seconds where his back is to you”,
“and the south guard is behind the truck.”,
“”,
“You count.”,
“One. Two. Three.”,
“You move on four.”,
])
g.set_flag(“heist_used_timing”)
return “heist_solo_guards”
elif idx == 2:
if g.has_item(“cyberdeck”):
g.energy = max(0, g.energy - 25)
g.show_text([
“You jack in from two hundred meters.”,
“The drone’s signal is military-grade”,
“but the encryption is five years old.”,
“”,
“Thirty seconds of work.”,
“The drone’s camera feed loops.”,
“The pilot in the AV sees nothing.”,
“”,
“Now you move.”,
])
g.set_flag(“heist_drone_down”)
return “heist_solo_guards”
else:
g.show_text([“No cyberdeck. Try a different approach.”])
return “heist_alone”
else:
g.show_text([
“The generator is on the east post.”,
“You cut it with your knife.”,
“The floodlights die.”,
“”,
“Four seconds of silence.”,
“Then radios crackling.”,
“Flashlights swinging.”,
“”,
“They’re disoriented.”,
“You use that.”,
])
g.set_flag(“heist_lights_out”)
return “heist_solo_guards”

def scene_heist_solo_direct(g):
g.show_text([
“No tricks.”,
“You step into the light and start shooting.”,
“”,
“The north guard reacts fastest.”,
“Still not fast enough.”,
], title=“THE HEIST”)
result = g.run_combat([
(“Militech Guard”,  30,  9, 10, 1),
(“Militech Guard”,  30,  9, 10, 1),
(“Militech Guard”,  30,  9, 10, 1),
(“Militech Sergeant”, 48, 13, 12, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 30)
g.show_text([
“Four on one. The math catches up with you.”,
“You crawl into the storm drain”,
“before the cuffs come out.”,
“”,
“No chip. Bruised ribs.”,
“Try a smarter approach.”,
])
return “heist_alone”
return “heist_solo_chip”

def scene_heist_solo_guards(g):
lights_out = g.check_flag(“heist_lights_out”)
drone_down = g.check_flag(“heist_drone_down”)
timing     = g.check_flag(“heist_used_timing”)
atk_mod = -2 if (lights_out or timing) else 0
count_mod  = -1 if timing else 0   # timing lets you split them
guards = [
(“Militech Guard”, 30, max(5, 9+atk_mod), 10, 1),
(“Militech Guard”, 30, max(5, 9+atk_mod), 10, 1),
]
if not timing:
guards.append((“Militech Guard”, 30, max(5, 9+atk_mod), 10, 1))
if lights_out:
g.show_text([
“Dark. Flashlights spinning.”,
“You pick your shots carefully.”,
], title=“THE HEIST”)
elif drone_down:
g.show_text([
“No overhead eyes.”,
“You work methodically.”,
], title=“THE HEIST”)
result = g.run_combat(guards)
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“They box you in.”,
“You break contact.”,
“No chip. Try again.”,
])
return “heist_alone”
return “heist_solo_chip”

def scene_heist_solo_chip(g):
g.show_text([
“Guards down.”,
“The rear transport.”,
“You pull the latch.”,
“”,
“Inside: equipment cases.”,
“And a driver, still in the cab.”,
“He’s watching you in the mirror.”,
“Hands on the wheel.”,
“Not reaching for anything.”,
“”,
“The chip is in a locked case”,
“bolted to the floor.”,
“You need the driver’s access code.”,
], title=“THE HEIST”)
idx = g.choose([
“Ask him for the code calmly”,
“Threaten him”,
“Knock him out and search for the code”,
“Shoot the lock off”,
])
if idx == 0:
g.show_text([
“You open the cab door.”,
“‘The code. Please.’”,
“”,
“He looks at the guards on the ground.”,
“Looks at you.”,
“‘4-4-1-7.’”,
“”,
“You let him go.”,
“He walks north and doesn’t look back.”,
])
g.set_flag(“heist_driver_freed”)
g.change_rep(“street”, 1)
elif idx == 1:
g.show_text([
“You put your weapon against the window.”,
“He gives you the code in two seconds.”,
“”,
“You don’t hurt him.”,
“You didn’t say you would.”,
“You just implied it.”,
])
elif idx == 2:
g.show_text([
“Quick. Clean.”,
“You find the code on a card”,
“in his jacket pocket.”,
“Old school security.”,
])
else:
g.show_text([
“The shot sparks off the case.”,
“Three more shots and the lock gives.”,
“Loud. Very loud.”,
“You hear distant radio chatter.”,
“Move faster.”,
])
g.set_flag(“heist_loud_exit”)
return “heist_solo_exit”

def scene_heist_solo_exit(g):
if g.check_flag(“heist_loud_exit”):
g.show_text([
“Backup is coming.”,
“You hear the AV banking hard.”,
“”,
“You run.”,
], title=“THE HEIST”)
result = g.run_combat([
(“Militech Response”, 35, 11, 12, 2),
(“Militech Response”, 35, 11, 12, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 25)
g.show_text([
“Caught in the open.”,
“You ditch the chip in a storm drain”,
“and run empty-handed.”,
“”,
“No chip. Come back smarter.”,
])
return “heist_alone”
g.add_item(“prototype_chip”)
pay = 12000 if g.check_flag(“negotiated_pay”) else 10000
g.eddies    += pay
g.heist_done = True
g.story_act  = 1
g.change_rep(“street”, 2)
g.show_text([
“The chip is in your jacket.”,
“Small. Dense.”,
“Like holding a secret.”,
“”,
“You disappear into the underpass.”,
“The drone comes back on its pass.”,
“Sees nothing.”,
“”,
“You make it to the Afterlife by midnight.”,
“Rook pays without counting the bills.”,
f”+{pay} eddies.”,
])
return “after_heist”

# ── HEIST: CREW PATH ────────────────────────────────────────────────

def scene_heist_combat(g):
crew_names = “ + “.join(g.crew) if g.crew else “just you”
g.show_text([
“NIGHT  –  ROUTE 7”,
“”,
f”Your crew: {crew_names}.”,
“”,
“You brief them on the overpass.”,
“Jin has the drone’s signal signature.”,
“Maya has her rifle positioned north.”,
“”,
“The convoy rolls in at 22:08.”,
“Right on time.”,
“”,
“How do you hit it?”,
], title=“THE HEIST”)
idx = g.choose([
“Coordinated strike – hit all at once”,
“Jin kills the drone, Maya pins them, you extract”,
“Create a diversion first – then strike”,
“Let them stop, wait for the rotation gap”,
])
if idx == 0:
return “heist_crew_strike”
elif idx == 1:
g.show_text([
“JIN:  ‘Drone feed is looped.”,
“       They’re blind overhead.’”,
“”,
“MAYA: ‘I have the sergeant.’,”,
“      ‘He goes first.’,”,
“      ‘Your signal.’”,
“”,
“You whistle low.”,
“The operation begins.”,
])
g.set_flag(“heist_coordinated”)
return “heist_crew_execute”
elif idx == 2:
g.show_text([
“Maya fires a flare gun”,
“into the storm drain two blocks east.”,
“The explosion is mostly smoke.”,
“Mostly.”,
“”,
“Two guards break to investigate.”,
“That leaves two.”,
“Much better odds.”,
])
g.set_flag(“heist_diverted”)
return “heist_crew_execute”
else:
g.show_text([
“You watch.”,
“Minute four: guards rotate.”,
“There’s a twelve-second window”,
“where the formation breaks.”,
“”,
“You signal your crew.”,
])
g.set_flag(“heist_timed”)
return “heist_crew_execute”

def scene_heist_crew_strike(g):
g.show_text([
“All at once.”,
“No warning. No hesitation.”,
“”,
“Maya drops the sergeant from the overpass”,
“before he can key his radio.”,
“Jin crashes their comms.”,
“You take the remaining guards.”,
], title=“THE HEIST”)
result = g.run_combat([
(“Militech Guard”, 35, 10, 10, 1),
(“Militech Guard”, 35, 10, 10, 1),
(“Militech Guard”, 35, 10, 10, 1),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 25)
g.show_text([
“The third guard radios before he drops.”,
“Backup is three minutes out.”,
“You pull back.”,
“”,
“Maya: ‘We were too loud.’”,
“Jin: ‘Regroup. Try again.’”,
])
return “heist_plan”
return “heist_crew_chip”

def scene_heist_crew_execute(g):
atk_mod = -2 if g.check_flag(“heist_timed”) else 0
guards_count = 2 if g.check_flag(“heist_diverted”) else 3
guard_list = [
(“Militech Guard”, 35, max(5, 10+atk_mod), 10, 1)
for _ in range(guards_count)
]
result = g.run_combat(guard_list)
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“It falls apart.”,
“You pull back before it gets worse.”,
“”,
“Jin: ‘We need to reset.’”,
])
return “heist_plan”
return “heist_crew_chip”

def scene_heist_crew_chip(g):
g.show_text([
“Guards down.”,
“”,
“Jin patches into the transport’s lock.”,
“‘Twenty seconds.’”,
“”,
“Maya covers the road north.”,
“‘We’re clear. Hurry.’”,
“”,
“The case opens.”,
“The chip sits in a foam cradle.”,
“Smaller than you expected.”,
“”,
“Inside the cab: the driver.”,
“Young. Scared.”,
“Hands raised.”,
], title=“THE HEIST”)
idx = g.choose([
“Take the chip – let the driver go”,
“Take the chip – tie him up so he can’t radio”,
“Take the chip – tell him what it really is”,
])
if idx == 0:
g.show_text([
“‘Stay in the cab.”,
“ Count to three hundred.”,
“ Then radio for help.’”,
“”,
“He nods.”,
“You believe him.”,
])
g.set_flag(“heist_driver_freed”)
g.change_rep(“street”, 1)
elif idx == 1:
g.show_text([
“Zip ties from your kit.”,
“Not rough about it.”,
“He’ll be found inside an hour.”,
“”,
“He doesn’t fight.”,
])
else:
g.show_text([
“‘This chip can copy people’s minds.”,
“ Militech’s using it for control.”,
“ Tell your friends.’”,
“”,
“He stares at you.”,
“‘What?’”,
“‘Just think about it.’”,
“”,
“You leave him with a lot to think about.”,
])
g.set_flag(“heist_driver_knows”)
return “heist_crew_exit”

def scene_heist_crew_exit(g):
g.show_text([
“MAYA: ‘Jin, how long on comms?’”,
“JIN:  ‘Sixty seconds before”,
“        they realize it’s jammed.’”,
“MAYA: ‘Then we’re already moving.’”,
“”,
“You run the underpass route.”,
“The AV completes its pass overhead.”,
“Sees nothing but a stopped convoy”,
“and four unconscious guards.”,
“”,
“Six minutes later”,
“you’re three blocks away”,
“and slowing to a walk.”,
], title=“THE HEIST”)
g.add_item(“prototype_chip”)
pay = 12000 if g.check_flag(“negotiated_pay”) else 10000
g.eddies    += pay
g.heist_done = True
g.story_act  = 1
g.change_rep(“street”, 3)
g.show_text([
“MAYA: ‘Clean.’”,
“JIN:  ‘Cleaner than I expected.’”,
“”,
“You hold up the chip.”,
“Streetlight through the rain.”,
“”,
“Whatever this thing is,”,
“people are willing to kill for it.”,
“That means it’s worth something real.”,
“”,
f”Rook pays: +{pay} eddies.”,
])
return “after_heist”

def scene_after_heist(g):
g.show_text([
“Back at the Afterlife.”,
“”,
“Rook counts the chip, not the money.”,
“He doesn’t even look up when he pays you.”,
“”,
“You’re halfway to the door”,
“when someone steps in your path.”,
“”,
“Tall. Militech uniform under a civilian coat.”,
“She’s not hiding it.”,
“She doesn’t need to.”,
“”,
“VECTOR:  ‘Sit back down, Niko.’,”,
“‘We need to have a conversation.’”,
], title=“VECTOR”)
g.show_text([
“Colonel Ana Vector.”,
“Militech Intelligence Division.”,
“”,
“She slides into the booth”,
“like she owns it. Like she owns the bar.”,
“Like she owns Night City.”,
“”,
“‘We had eyes on that convoy.’,”,
“‘We let you take it.’,”,
“‘Now we need something back.’”,
“”,
“She sets a data chip on the table.”,
“Her side. Not yours.”,
“”,
“‘Work for us. One job.’,”,
“‘Then we call it even.’,”,
“‘Refuse, and the chip goes back to Militech”,
“along with your address.’”,
], title=“VECTOR”)
idx = g.choose([
“Agree – hear the job”,
“Refuse – take your chances”,
“Hand the chip back – walk away clean”,
“Ask what the job is first”,
])
if idx == 0:
g.chose_militech = True
g.change_rep(“militech”, 2)
g.set_flag(“vector_ally”)
g.show_text([
“Vector: ‘Smart.’,”,
“”,
“‘Someone inside Militech sold our convoy route.’,”,
“‘A data analyst. Name: Hiro Tanaka.’,”,
“‘Find him before we do.’,”,
“‘If he talks to the Voodoo Boys first”,
“we lose six months of field work.’”,
“”,
“‘You have 48 hours.’”,
“”,
“She stands, takes her chip back,”,
“and walks out.”,
“Three guards follow her.”,
“You didn’t see them come in.”,
])
return “act2_vector_lead”
elif idx == 1:
g.change_rep(“militech”, -3)
g.set_flag(“militech_enemy”)
g.show_text([
“Vector’s expression doesn’t change.”,
“”,
“‘That’s a choice.’,”,
“‘Not a smart one. But yours to make.’”,
“”,
“She leaves.”,
“Rook doesn’t look up.”,
“‘You just made an enemy, Niko.’,”,
“‘Militech doesn’t forget.’”,
“”,
“Two days later, someone shoots out”,
“your capsule window.”,
“A warning.”,
“You start sleeping somewhere else.”,
])
return “act2_no_vector”
elif idx == 2:
g.eddies   += 500
g.remove_item(“prototype_chip”)
g.change_rep(“militech”, 1)
g.show_text([
“You slide the chip across.”,
“”,
“Vector picks it up.”,
“Studies it for a moment.”,
“”,
“‘Reasonable.’,”,
“‘Here’s 500 for your trouble.’,”,
“‘We’ll be in touch.’”,
“”,
“She’s gone before you can ask”,
“what that means.”,
“”,
“Rook: ‘You just gave up 10,000 eddies”,
“to save your own skin.’,”,
“‘Can’t say I blame you.’”,
])
return “act2_no_vector”
else:
g.show_text([
“Vector: ‘There’s a leak inside Militech.’,”,
“‘A mole feeding data to the Voodoo Boys.’,”,
“‘Name: Hiro Tanaka. Data analyst.’,”,
“‘Find him. Bring him in. Or just”,
“find out who he’s talking to.’”,
“”,
“‘We pay 5,000 on delivery.”,
“On top of keeping your address private.’”,
“”,
“She waits.”,
])
return “after_heist”  # loop back for final choice

# =============================================================================

# ACT 2  –  GHOST SIGNAL

# =============================================================================

def scene_act2_vector_lead(g):
g.story_act = max(g.story_act, 2)
g.show_text([
“ACT 2  –  GHOST SIGNAL”,
“”,
“Hiro Tanaka.”,
“You pull everything you can on him.”,
“Low-level analyst. Twelve years at Militech.”,
“Clean record. Then nothing for two months.”,
“Then a withdrawal. 40,000 eddies.”,
“Then a one-way transit pass.”,
“”,
“He’s running.”,
“Or he’s planning to.”,
“”,
“Jin tracks his agent signal”,
“to a capsule hotel in Kabuki.”,
“Room 14. Sixth floor.”,
“He checked in six hours ago.”,
], title=“ACT 2”)
idx = g.choose([
“Go to the capsule hotel now”,
“Stake out the hotel – wait and watch”,
“Hack his room’s comms first (cyberdeck)”,
“Send Maya in as a guest”,
])
if idx == 0:
return “hiro_direct”
elif idx == 1:
g.show_text([
“You watch from the lobby cafe.”,
“Four hours. Terrible synth-coffee.”,
“”,
“Hiro comes down at 3 AM with a bag.”,
“He’s leaving.”,
“You follow him to the metro platform.”,
])
return “hiro_platform”
elif idx == 2:
if g.has_item(“cyberdeck”):
g.energy = max(0, g.energy - 20)
g.show_text([
“Jin patches you in.”,
“”,
“Hiro’s messages:”,
“‘Meeting at the fish market. 4 AM.’”,
“‘Bring everything you have on the convoy.’”,
“‘They’ll get you out of the city.’”,
“”,
“‘They.’ Voodoo Boys.”,
“He’s not just running.”,
“He’s delivering.”,
“You have until 4 AM.”,
])
g.set_flag(“hiro_4am_deadline”)
return “hiro_intercept”
else:
g.show_text([“No cyberdeck. You stake out the hotel instead.”])
return “hiro_platform”
else:
if “Maya” in g.crew:
g.show_text([
“Maya: ‘You want me to what?’”,
“‘Chat him up? I’m a soldier, Niko.’”,
“‘But fine.’”,
“”,
“Twenty minutes later:”,
“‘Room 14. He’s packing.”,
“He’s scared. And he’s got a meet”,
“at the fish market at 4 AM.’”,
“”,
“Maya: ‘You owe me for this.’”,
])
g.set_flag(“hiro_4am_deadline”)
return “hiro_intercept”
else:
g.show_text([“You don’t have Maya yet. Try another approach.”])
return “act2_vector_lead”

def scene_act2_no_vector(g):
g.story_act = max(g.story_act, 2)
g.show_text([
“ACT 2  –  GHOST SIGNAL”,
“”,
“Without Vector’s lead,”,
“you’re working blind.”,
“”,
“But three days after the heist,”,
“your agent buzzes.”,
“Unknown sender. Heavy encryption.”,
“Jin cracks it in forty minutes.”,
“”,
“‘You took the chip.’,”,
“‘You don’t know what it is yet.’,”,
“‘Meet me. Pacifica. The old den.’,”,
“‘Come alone.’”,
“’   – L’”,
“”,
“L.”,
“The same initial as that first message.”,
], title=“ACT 2”)
idx = g.choose([
“Go to Pacifica”,
“Try to trace the sender first”,
“Bring your crew – ignore the ‘alone’ part”,
])
if idx == 0:
return “lucy_pacifica”
elif idx == 1:
g.show_text([
“Jin tries.”,
“The message bounced through”,
“eleven proxy nodes across three continents.”,
“”,
“Jin: ‘Whoever sent this is either”,
“a ghost or a very good netrunner.’,”,
“‘Maybe both.’”,
“”,
“You go to Pacifica.”,
])
return “lucy_pacifica”
else:
g.show_text([
“Maya: ‘Smart. Anyone who sends”,
“a message like that is either”,
“bait or paranoid.’”,
“”,
“Jin: ‘Or both.’”,
“”,
“You all go.”,
])
g.set_flag(“crew_to_pacifica”)
return “lucy_pacifica”

def scene_hiro_direct(g):
g.show_text([
“Room 14. Sixth floor.”,
“You knock.”,
“”,
“Hiro opens the door”,
“with a gun in his hand.”,
“”,
“He’s not pointing it at you yet.”,
“But his finger is inside the guard.”,
“”,
“HIRO:  ‘Who are you?’”,
], title=“HIRO”)
idx = g.choose([
“Show Vector’s badge – I’m here to help you”,
“I’m just a merc. I can get you out of the city”,
“Tell him the truth – Vector wants him found”,
“Knock the gun away – take control”,
])
if idx == 0:
g.show_text([
“Hiro’s gun comes up.”,
“‘Vector? That’s who sent you?’”,
“‘Then you’re here to kill me.’”,
“”,
“He fires. You duck.”,
“The shot takes out the window.”,
“You tackle him before he reloads.”,
])
return “hiro_subdued”
elif idx == 1:
g.show_text([
“His eyes flick. He’s weighing it.”,
“‘How much?’”,
“‘Enough. I need what you know first.’”,
“”,
“He hesitates. Then he puts the gun down.”,
“‘Come inside.’,”,
“‘If this is a trap I’m already dead anyway.’”,
])
return “hiro_talks”
elif idx == 2:
g.show_text([
“His face goes white.”,
“‘Then I’m already dead.”,
“Why are you still talking to me?’”,
“”,
“‘Because I haven’t decided yet.’”,
“”,
“That stops him.”,
])
return “hiro_talks”
else:
result = g.run_combat([
(“Hiro Tanaka”, 25, 7, 9, 0),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 15)
g.show_text([
“He gets a shot off. Grazes your arm.”,
“You fall back into the corridor.”,
“He locks the door.”,
“You try a different approach.”,
])
return “hiro_direct”
return “hiro_subdued”

def scene_hiro_platform(g):
g.show_text([
“Metro platform. 3 AM.”,
“Hiro has a bag. One-way ticket.”,
“”,
“You step in front of him.”,
“”,
“HIRO:  ‘Get out of my way.’”,
“YOU:   ‘Where are you going, Hiro?’”,
“”,
“His face goes gray.”,
“‘You’re from Militech.’”,
“‘No. But they sent me to find you.’”,
“”,
“His hand goes to his coat pocket.”,
], title=“HIRO”)
idx = g.choose([
“Calm him down – you’re not there to hurt him”,
“Grab his wrist before he draws”,
“Let him reach for whatever he’s reaching for”,
])
if idx == 0:
g.show_text([
“‘Easy. I’m not here to drag you in.’”,
“‘I want to know why you did it first.’”,
“”,
“His shoulders drop. Not much.”,
“Enough.”,
“‘They had my daughter.’,”,
“‘Voodoo Boys. Said they’d hurt her”,
“if I didn’t give them the route.”,
“I had no choice.’”,
])
return “hiro_talks”
elif idx == 1:
g.show_text([
“He’s fast. You’re faster.”,
“You pin his arm. He drops the agent.”,
“He tries to yell. Your hand covers his mouth.”,
“”,
“‘I’m not going to hurt you.’,”,
“‘But you’re going to talk to me.”,
“Right now. Quietly.’”,
“”,
“He nods. Slowly.”,
])
return “hiro_talks”
else:
g.show_text([
“He pulls a flash-bang.”,
“You go blind for thirty seconds.”,
“When your vision comes back”,
“he’s gone.”,
“”,
“You find his bag. He left it.”,
“Inside: a data shard.”,
“Everything he was going to deliver.”,
])
g.add_item(“voodoo_intel”)
g.set_flag(“hiro_escaped”)
return “hiro_outcome”

def scene_hiro_intercept(g):
g.show_text([
“Fish market. 4 AM.”,
“It smells like salt and dead electronics.”,
“”,
“Hiro is already there.”,
“Two Voodoo Boys with him.”,
“He’s handing something over.”,
“”,
“You can stop this.”,
“Or let it happen and follow them.”,
], title=“INTERCEPT”)
idx = g.choose([
“Move in – stop the handoff”,
“Wait – follow the Voodoo Boys after”,
“Call it in to Vector right now”,
])
if idx == 0:
g.show_text([
“You break from cover.”,
“The Voodoo Boys see you.”,
“One of them pulls a weapon.”,
])
result = g.run_combat([
(“Voodoo Guard”,  35, 10, 11, 1),
(“Voodoo Guard”,  35, 10, 11, 1),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“They scatter. Hiro with them.”,
“The handoff happened.”,
“”,
“You recover. Bruised.”,
“The data is in Voodoo Boys hands now.”,
])
g.set_flag(“handoff_happened”)
return “hiro_outcome”
g.show_text([
“Both guards down.”,
“Hiro hasn’t run.”,
“He’s just standing there,”,
“holding the shard like it burned him.”,
])
return “hiro_talks”
elif idx == 1:
g.show_text([
“You watch. The handoff completes.”,
“Hiro gets an envelope. Eddies.”,
“”,
“The Voodoo Boys head north.”,
“You follow them for six blocks”,
“to a safe house in Pacifica.”,
“”,
“You make note of the address.”,
“And something else:”,
“A name on the safe house door.”,
“SABLE.”,
])
g.set_flag(“found_sable_safehouse”)
g.set_flag(“handoff_happened”)
return “hiro_outcome”
else:
g.show_text([
“Vector answers on the second ring.”,
“‘You have eyes on Tanaka?’”,
“‘He’s at the fish market.”,
“Voodoo Boys. Mid-handoff.’”,
“”,
“Six Militech units arrive in four minutes.”,
“Hiro and both Voodoo Boys are taken.”,
“”,
“Vector: ‘5,000 as agreed.”,
“You’re useful, Niko.’”,
“”,
“Hiro’s face when they cuff him.”,
“He looks more relieved than scared.”,
])
g.eddies += 5000
g.change_rep(“militech”, 2)
g.set_flag(“turned_hiro_in”)
g.set_flag(“handoff_happened”)
return “hiro_outcome”

def scene_hiro_subdued(g):
g.show_text([
“Hiro on the floor.”,
“Gun across the room.”,
“He’s not fighting anymore.”,
“”,
“HIRO:  ‘Just do it then.’”,
“YOU:   ‘Do what?’”,
“HIRO:  ‘Whatever Vector told you to do.’”,
“”,
“His voice is flat.”,
“The voice of someone who gave up”,
“a while ago.”,
], title=“HIRO”)
return “hiro_talks”

def scene_hiro_talks(g):
g.show_text([
“HIRO:  ‘They took my daughter.”,
“        Seven years old.”,
“        Said they’d return her”,
“        if I gave them the convoy route.’”,
“”,
“‘I gave them the route.’,”,
“‘They returned her.’,”,
“‘Then they said they needed more.”,
“Or they’d take her again.’”,
“”,
“He stares at the floor.”,
“‘I’ve been trying to run ever since.’”,
], title=“HIRO”)
g.show_text([
“He slides a shard across the floor.”,
“”,
“‘That’s everything I gave them.”,
“The full convoy data.”,
“And something they didn’t ask for:”,
“a file I found by accident.”,
“Something called Mikoshi.”,
“I don’t know what it means.”,
“But the Voodoo Boys are terrified of it.”,
“And so are Militech.”,
], title=“HIRO”)
idx = g.choose([
“Let Hiro go – take the shard”,
“Give him money to leave the city”,
“Turn him in to Vector (5k reward)”,
“Tell him about the chip you stole”,
])
if idx == 0:
g.add_item(“voodoo_intel”)
g.set_flag(“hiro_escaped”)
g.show_text([
“‘Go. Don’t come back.’”,
“”,
“He doesn’t say thank you.”,
“He just picks up his bag”,
“and walks out.”,
“”,
“You have the shard.”,
“You have a name.”,
“MIKOSHI.”,
])
elif idx == 1:
g.eddies = max(0, g.eddies - 800)
g.add_item(“voodoo_intel”)
g.set_flag(“hiro_escaped”)
g.set_flag(“helped_hiro”)
g.change_rep(“street”, 2)
g.show_text([
“You give him 800 eddies.”,
“Everything you had before the heist.”,
“”,
“Hiro:  ‘Why?’”,
“You:   ‘Because your daughter didn’t”,
“        ask to be in this story.’”,
“”,
“He nods. Takes the money.”,
“You never see him again.”,
“You hope that means he made it.”,
])
elif idx == 2:
g.eddies += 5000
g.change_rep(“militech”, 2)
g.set_flag(“turned_hiro_in”)
g.show_text([
“Vector answers immediately.”,
“‘Bring him to the lobby.’”,
“”,
“She arrives in eleven minutes.”,
“Takes Hiro without looking at him.”,
“”,
“She hands you 5,000 eddies.”,
“‘You’re useful, Niko.’,”,
“‘I’ll be in touch.’”,
“”,
“Hiro doesn’t struggle.”,
“He just looks at you”,
“as they lead him out.”,
])
else:
g.add_item(“voodoo_intel”)
g.set_flag(“hiro_escaped”)
g.show_text([
“His eyes focus.”,
“‘The Ghost Relic?”,
“That’s what they wanted it for.”,
“The Relic maps to Mikoshi’s backdoor.”,
“Whoever has that chip can get inside.’”,
“”,
“He grabs your arm.”,
“‘Don’t let Militech have it.”,
“Don’t let Arasaka have it.”,
“There are people inside Mikoshi.”,
“Real people. Trapped.’”,
“”,
“You let him go.”,
“You stand there for a long time.”,
])
g.set_flag(“knows_mikoshi_truth”)
return “hiro_outcome”

def scene_hiro_outcome(g):
g.show_text([
“You have the shard.”,
“Or you know where the data went.”,
“Either way – you have a name.”,
“”,
“MIKOSHI.”,
“”,
“Jin finds a single reference online.”,
“Buried. Encrypted.”,
“Purged from most servers.”,
“”,
“‘It’s an Arasaka facility.’,”,
“‘Digital. Not physical.’,”,
“‘Some kind of storage system”,
“for neural engrams.’”,
“”,
“Your agent buzzes.”,
“Unknown sender. Again.”,
“”,
“‘You’re getting close.”,
“ Meet me in Pacifica.”,
“ I can explain everything.”,
“ Come alone.  – L’”,
], title=“THE LEAD”)
idx = g.choose([
“Go to Pacifica now”,
“Wait – do more research first”,
“Report to Vector before going”,
])
if idx == 0:
return “lucy_pacifica”
elif idx == 1:
g.show_text([
“Jin spends a day digging.”,
“He finds three things:”,
“”,
“1. Mikoshi was built in 2060.”,
“2. It was officially decommissioned”,
“   after the 2077 war.”,
“3. Its power draw never stopped.”,
“”,
“Jin: ‘Something’s still running in there.”,
“Something big.’”,
“”,
“You go to Pacifica.”,
])
return “lucy_pacifica”
else:
g.show_text([
“Vector: ‘Mikoshi? Where did you hear that?’”,
“You tell her about Hiro. The shard. The name.”,
“”,
“Long silence.”,
“‘Sit on this for now.”,
“Don’t go digging.”,
“That’s an order.’”,
“”,
“She hangs up.”,
“”,
“You go to Pacifica.”,
])
return “lucy_pacifica”

# =============================================================================

# LUCY  –  THE GHOST

# =============================================================================

def scene_lucy_pacifica(g):
g.show_text([
“PACIFICA”,
“”,
“Half-built towers.”,
“Salt wind off the ocean.”,
“The Voodoo Boys own this district”,
“the way Militech owns Watson—”,
“completely, and by force.”,
“”,
“The address leads you”,
“to a basement under a collapsed shopping mall.”,
“Generators humming.”,
“Eight terminals in a ring.”,
“All dead except one.”,
“”,
“A hologram flickers on.”,
“”,
“Silver hair. White jacket.”,
“She looks like she’s standing”,
“two feet in front of you.”,
“She’s not anywhere.”,
], title=“PACIFICA”)
g.show_text([
“LUCY:  ‘You found the name Mikoshi.’,”,
“        ‘That means you’re either”,
“        very clever or very unlucky.’”,
“”,
“‘Probably both.’,”,
“‘Welcome to the club.’”,
“”,
“She sits – or her hologram does.”,
“”,
“‘My name is Lucy.”,
“I was the best netrunner”,
“in Night City six years ago.”,
“Then I tried to breach Mikoshi”,
“and they put me in here.’”,
“”,
“She gestures at the hologram projector.”,
“‘I’m not dead. I’m just not”,
“anywhere you can find me physically.”,
“Not anymore.’”,
], title=“LUCY”)
idx = g.choose([
“What is Mikoshi?”,
“How do I know you’re real?”,
“What do you need from me?”,
“Ask about David Martinez”,
])
if idx == 0:
g.show_text([
“LUCY:  ‘Arasaka’s soul vault.”,
“        When they wanted to control someone”,
“        completely – an executive,”,
“        a scientist, a soldier –”,
“        they captured their engram.”,
“        Their mind. Their self.”,
“        And they put it in Mikoshi.”,
“        Hostage. Leverage.’,”,
“‘Forever, if they wanted.’”,
“”,
“‘When Arasaka fell,”,
“the engrams were supposed”,
“to be released.’,”,
“‘They weren’t.’,”,
“‘Someone kept the system running.”,
“Someone still had use for them.’”,
])
elif idx == 1:
g.show_text([
“She laughs. It sounds real.”,
“”,
“LUCY:  ‘Fair question.”,
“        Ask me something”,
“        only someone who’s been inside”,
“        the net would know.’”,
“”,
“You don’t have a question like that.”,
“”,
“She reaches through the hologram.”,
“Her hand passes through your face.”,
“You feel cold.”,
“”,
“‘I’m as real as anything in Night City.’,”,
“‘Which isn’t saying much.”,
“But it’s what you’ve got.’”,
])
elif idx == 3:
g.show_text([
“Her face changes.”,
“”,
“LUCY:  ‘David.’,”,
“”,
“Just the name. Nothing else.”,
“For a long moment.”,
“”,
“‘He tried to reach the moon.”,
“Literally.’,”,
“‘He almost made it.’,”,
“‘His engram is in Mikoshi.”,
“They grabbed it during the 77 war.”,
“They’ve had him ever since.’”,
“”,
“She looks at her hands.”,
“‘He’s been in there for ten years.”,
“Whatever’s left of him.’”,
])
g.lucy_trust += 1
return “lucy_the_plan”

def scene_lucy_the_plan(g):
g.show_text([
“LUCY:  ‘I need three things”,
“        to open Mikoshi from the outside.”,
“        I’ve spent six years”,
“        getting two of them.’,”,
“”,
“‘One more.”,
“Then we can get everyone out.”,
“Every engram they ever stole.”,
“David. All of them.’”,
“”,
“She pulls up a display:”,
“”,
“KEY 1: Militech clearance code”,
“       (Network access to the relay)”,
“KEY 2: Voodoo Boys net ritual”,
“       (Bypasses the ICE layer)”,
“KEY 3: Arasaka biokey”,
“       (Opens the core itself)”,
“”,
“‘I have the first two already.”,
“I need you to get the third.’”,
], title=“THE PLAN”)
idx = g.choose([
“I’m in – what do I need to do?”,
“This sounds insane”,
“What’s in it for me?”,
“Ask about the biokey specifically”,
])
if idx == 0:
g.met_lucy   = True
g.lucy_trust += 1
g.story_act   = max(g.story_act, 3)
g.show_text([
“LUCY:  ‘Good.”,
“        The biokey is carried by”,
“        a living Arasaka executive.”,
“        There’s one still in Night City.”,
“        Exec Hanako Tanaka.”,
“        She’s been in hiding”,
“        since the war ended.”,
“        I’ll send you her last known location.”,
“        The rest is up to you.’”,
“”,
“The hologram flickers.”,
“‘One more thing.’,”,
“‘Whatever you do—”,
“don’t let Militech know”,
“what you’re actually looking for.”,
“Vector will shut this down”,
“the moment she understands it.’”,
])
return “act3_biokey”
elif idx == 1:
g.show_text([
“LUCY:  ‘It is insane.”,
“        But so is keeping”,
“        ten thousand minds”,
“        in a digital cage”,
“        because a corp decided”,
“        they were useful property.’”,
“”,
“‘You don’t have to help me.”,
“But you found the name Mikoshi.”,
“That means they already know”,
“you exist.”,
“Doing nothing won’t make you safer.’”,
])
return “lucy_the_plan”
elif idx == 2:
g.show_text([
“LUCY:  ‘When we breach Mikoshi,”,
“        the vault opens.”,
“        There’s forty years of”,
“        Arasaka’s most sensitive data”,
“        in there with the engrams.”,
“        Corporate secrets.”,
“        Personnel files.”,
“        Blackmail material on”,
“        every major government official”,
“        in four countries.”,
“”,
“‘Any of that has value.”,
“Take what you want.”,
“I just want the people.’”,
])
g.met_lucy   = True
g.lucy_trust += 1
g.story_act   = max(g.story_act, 3)
return “act3_biokey”
else:
g.show_text([
“LUCY:  ‘A biological encryption key.”,
“        Grown from Arasaka’s founder’s DNA.”,
“        Every senior exec carries a copy.”,
“        Without it, the core is sealed.”,
“        Even I can’t crack it remotely.”,
“        It has to be present in person”,
“        at the relay point.’”,
“”,
“‘Tanaka is the only exec”,
“still alive and in the city.”,
“She’s in hiding.”,
“She’s also terrified.’,”,
“‘Which makes her dangerous.’”,
])
return “lucy_the_plan”

# =============================================================================

# ACT 3  –  THE BIOKEY

# =============================================================================

def scene_act3_biokey(g):
g.story_act = max(g.story_act, 3)
g.show_text([
“ACT 3  –  THE BIOKEY”,
“”,
“Hanako Tanaka.”,
“”,
“Lucy’s data puts her in”,
“a safehouse in Corpo Plaza ruins.”,
“Used to be the nicest block in Night City.”,
“Now it’s rubble and radiation monitors.”,
“”,
“She has four Arasaka security with her.”,
“Loyalists. The kind who stayed”,
“when the corp fell”,
“because they had nowhere else to go.”,
“”,
“How do you get to her?”,
], title=“ACT 3”)
idx = g.choose([
“Go through the security – front entrance”,
“Make contact first – send a message”,
“Get inside quietly (optical camo)”,
“Find out more about Tanaka first”,
])
if idx == 0:
return “tanaka_assault”
elif idx == 1:
return “tanaka_contact”
elif idx == 2:
if g.equipped_cyberware == “optical_camo” or g.has_item(“optical_camo”):
return “tanaka_stealth”
else:
g.show_text([
“You don’t have optical camo.”,
“You’ll need to find another way in.”,
])
return “act3_biokey”
else:
return “tanaka_research”

def scene_tanaka_research(g):
g.show_text([
“You spend a day pulling everything”,
“on Hanako Tanaka.”,
“”,
“Age 41. Third daughter of”,
“Saburo Tanaka, a mid-tier Arasaka exec”,
“who died in the 77 war.”,
“”,
“She stayed in Night City”,
“after the collapse.”,
“Not because she wanted to.”,
“Because Militech froze her accounts”,
“and she had nowhere to run.”,
“”,
“She hates Militech.”,
“She hates what happened to Arasaka.”,
“And according to three intercepted messages,”,
“she’s been trying to find a way”,
“to access Mikoshi herself.”,
“”,
“To reach her father’s engram.”,
], title=“TANAKA RESEARCH”)
g.set_flag(“tanaka_research_done”)
g.show_text([
“This changes things.”,
“”,
“She’s not an enemy.”,
“She’s a prisoner in a different way.”,
“”,
“You have an angle now.”,
])
return “act3_biokey”

def scene_tanaka_contact(g):
extra = “”
if g.check_flag(“tanaka_research_done”):
extra = “(your research gives you the right words)”
g.show_text([
f”You send a message {extra}:”,
“”,
“‘Ms. Tanaka.”,
“ I know about Mikoshi.”,
“ I know about your father.”,
“ I’m not Militech.”,
“ I’m not Arasaka.”,
“ Meet me.”,
“ I can get you inside.’”,
“”,
“Then you wait.”,
“”,
“Forty-seven minutes.”,
“Then:”,
“‘Corpo Plaza. Sector 4.”,
“ 2100 hours.”,
“ Come alone.”,
“ If I see anyone else”,
“ we’re done.’”,
], title=“CONTACT”)
idx = g.choose([
“Go alone – trust the meeting”,
“Go but station crew nearby”,
“Bring crew openly – ignore her terms”,
])
if idx == 0:
return “tanaka_meeting”
elif idx == 1:
g.show_text([
“Maya takes a position two blocks north.”,
“Jin patches in remotely.”,
“”,
“‘You’re covered.’”,
“‘Go.’”,
])
g.set_flag(“crew_nearby_tanaka”)
return “tanaka_meeting”
else:
g.show_text([
“You arrive with your crew.”,
“The safe house window goes dark.”,
“”,
“Your agent buzzes:”,
“‘Wrong choice.”,
“ Don’t contact me again.’”,
“”,
“You’ll have to take the hard way in.”,
])
return “tanaka_assault”

def scene_tanaka_meeting(g):
g.show_text([
“Corpo Plaza ruins.”,
“2100 hours.”,
“”,
“Hanako Tanaka is not what you expected.”,
“She’s smaller. Her clothes are expensive”,
“but worn at the cuffs.”,
“She’s been living carefully.”,
“”,
“TANAKA:  ‘You said you know about Mikoshi.”,
“          Prove it.’”,
], title=“TANAKA”)
idx = g.choose([
“Tell her about Lucy – the ghost in the net”,
“Tell her what you know about the engrams”,
“Tell her about her father specifically”,
“Tell her about the Ghost Relic chip”,
])
if idx == 0:
g.show_text([
“Her expression doesn’t change.”,
“But her hands stop moving.”,
“”,
“TANAKA:  ‘A netrunner named Lucy.”,
“          Trapped in the net”,
“          six years ago.’,”,
“‘I’ve heard rumors.”,
“You’re telling me they’re real.’”,
“”,
“‘If she can reach Mikoshi…”,
“Then she can reach my father.’”,
“”,
“She sits down.”,
“First time in the conversation.”,
])
elif idx == 2:
if g.check_flag(“tanaka_research_done”):
g.show_text([
“Her face fractures.”,
“Just for a moment.”,
“Then she controls it.”,
“”,
“TANAKA:  ‘His engram was captured”,
“          during the evacuation.”,
“          I’ve known for years.”,
“          I’ve never been able to…’”,
“”,
“She stops.”,
“‘How do you know that?’”,
“‘I did my homework.’”,
“”,
“Long silence.”,
“‘What do you need from me?’”,
])
g.lucy_trust += 1
else:
g.show_text([
“TANAKA:  ‘My father.”,
“          You know about my father.’”,
“”,
“She’s quiet for a long moment.”,
“‘His engram was taken”,
“during the 77 evacuation.’,”,
“‘I’ve been trying to reach it”,
“for years.’,”,
“‘What do you need?’”,
])
else:
g.show_text([
“TANAKA:  ‘The Ghost Relic.”,
“          So Militech has it now.’”,
“”,
“‘Or someone does.’,”,
“‘If it maps to Mikoshi’s backdoor,”,
“then Lucy might be able to use it”,
“to get everyone out.’”,
“”,
“She thinks.”,
“‘What do you need from me?’”,
])
return “tanaka_gives_key”

def scene_tanaka_gives_key(g):
g.show_text([
“TANAKA:  ‘I have the biokey.”,
“          I’ve had it since my father”,
“          gave it to me”,
“          the day before he died.”,
“          I always thought”,
“          I’d find a way to use it.”,
“          I never thought”,
“          it would look like this.’”,
“”,
“She holds up a small device.”,
“Organic. Warm-looking.”,
“Like something grown, not built.”,
“”,
“‘If I give you this,”,
“I need your word.”,
“Everyone in Mikoshi gets out.”,
“Not just my father.”,
“Everyone.’”,
], title=“THE KEY”)
idx = g.choose([
“You have my word”,
“I can’t promise that – I don’t control Lucy”,
“What if we can’t free all of them?”,
])
if idx == 0:
g.set_flag(“promised_tanaka”)
g.lucy_trust += 1
g.show_text([
“She places the biokey in your palm.”,
“”,
“TANAKA:  ‘It responds to proximity.”,
“          You’ll need to be physically”,
“          at the relay point.”,
“          I’ll tell you where that is”,
“          when you’re ready.’”,
“”,
“‘And, Niko?’,”,
“‘Be careful who you trust.”,
“Militech knows about this.”,
“They’ve always known.”,
“They’ve been waiting for someone”,
“to do the work for them.’”,
])
g.add_item(“arasaka_biokey”)
g.keys_found.append(“arasaka_key”)
g.set_flag(“tanaka_ally”)
g.story_act = max(g.story_act, 4)
g.show_text([
“You have it.”,
“The biokey.”,
“”,
“Lucy’s third key.”,
“”,
“Your agent buzzes.”,
“Vector.”,
“”,
“‘We need to meet.”,
“ Now.”,
“ It’s about Mikoshi.’”,
“”,
“Tanaka was right.”,
“They’ve always known.”,
])
return “act4_vector_moves”

def scene_tanaka_stealth(g):
g.show_text([
“Optical camo. You go invisible”,
“in the middle of Corpo Plaza”,
“and walk right past the sentries.”,
“”,
“The safehouse. Third floor.”,
“Tanaka at a terminal.”,
“Alone except for two guards outside the door.”,
“”,
“You materialize in the middle of the room.”,
“”,
“She doesn’t scream.”,
“Her hand goes to her desk drawer.”,
“You move faster.”,
], title=“TANAKA STEALTH”)
result = g.run_combat([
(“Arasaka Guard”,  40, 12, 10, 3),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“The guard hears the fight”,
“and comes through the door.”,
“You get out, barely.”,
“Tanaka is still inside.”,
“Try a different approach.”,
])
return “act3_biokey”
g.show_text([
“One guard down.”,
“You hold up your hands.”,
“‘I’m not here to hurt you.”,
“ I’m here about Mikoshi.”,
“ And your father.’”,
“”,
“Tanaka freezes.”,
“Then: ‘How long do we have?’”,
“‘Until the other guard comes back.”,
“ Talk to me.’”,
])
return “tanaka_gives_key”

def scene_tanaka_assault(g):
g.show_text([
“Four loyalist guards.”,
“Arasaka-trained.”,
“They haven’t stopped fighting”,
“since the war ended.”,
“They’re just fighting for a company”,
“that no longer exists.”,
“”,
“You hit the front entrance.”,
], title=“ASSAULT”)
result = g.run_combat([
(“Arasaka Guard”,   50, 14, 11, 3),
(“Arasaka Guard”,   50, 14, 11, 3),
(“Arasaka Veteran”, 70, 17, 12, 5, [(“Coordinated Fire”, 1.4)]),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 30)
g.show_text([
“They hold the line.”,
“You pull back, bleeding.”,
“”,
“This isn’t going to work alone.”,
“You need a smarter approach.”,
])
return “act3_biokey”
g.show_text([
“Three guards down.”,
“You find Tanaka on the third floor.”,
“”,
“She’s sitting at her terminal.”,
“She knew you were coming the moment”,
“the fighting started downstairs.”,
“”,
“TANAKA:  ‘You could have just asked.’”,
“YOU:     ‘I tried the other way first.’”,
“”,
“She almost smiles.”,
])
return “tanaka_gives_key”

# =============================================================================

# ACT 4  –  THE TRAP CLOSES

# =============================================================================

def scene_act4_vector_moves(g):
g.story_act = max(g.story_act, 4)
g.show_text([
“ACT 4  –  THE TRAP CLOSES”,
“”,
“Vector meets you in a parking structure.”,
“Three levels up. No cameras.”,
“”,
“VECTOR:  ‘Sit down, Niko.’,”,
“‘I’m going to tell you something”,
“I’m not supposed to tell you.’,”,
“‘Militech knows about Mikoshi.”,
“We’ve known for eight years.”,
“We’ve been waiting for someone”,
“to crack the access problem.’”,
“”,
“She looks out at the city.”,
“‘You’re that someone.”,
“Congratulations.’”,
], title=“ACT 4”)
g.show_text([
“VECTOR:  ‘We don’t want to free”,
“          the engrams, Niko.’,”,
“‘We want the facility.”,
“The infrastructure.”,
“The method.’,”,
“‘Forty years of Arasaka’s”,
“most valuable intellectual property”,
“sitting in a digital vault,”,
“and all we need is someone”,
“with a biokey to open the door.’,”,
“”,
“‘You have the biokey.”,
“Hand it over.”,
“We give you 500,000 eddies”,
“and you walk away”,
“the richest nobody in Night City.’”,
“”,
“She places a case on the hood.”,
“500,000. In eddies.”,
“Real ones.”,
], title=“ACT 4”)
idx = g.choose([
“Take the deal – 500k is a lot of money”,
“Refuse – you made a promise to Tanaka”,
“Stall her – buy time”,
“Tell Lucy about this right now”,
])
if idx == 0:
g.set_flag(“took_vector_deal”)
g.eddies += 500000
g.show_text([
“You pick up the case.”,
“”,
“Vector: ‘Smart.’,”,
“‘We’ll handle it from here.’”,
“”,
“You hand over the biokey.”,
“”,
“Later—at the Afterlife—”,
“you try not to think about”,
“what happens next.”,
“The David Martinez sits untouched.”,
“You order a different drink.”,
])
return “act4_sellout_path”
elif idx == 1:
g.change_rep(“militech”, -2)
g.show_text([
“YOU:  ‘No deal.’”,
“”,
“Vector doesn’t move.”,
“‘You understand what you’re choosing.’”,
“YOU:  ‘I understand exactly.’”,
“”,
“She picks up the case.”,
“‘Then we’re done being civil.”,
“You have 24 hours to use that key”,
“before we take it from you.’”,
“”,
“She walks to the elevator.”,
“‘I was hoping you’d say yes, Niko.”,
“I genuinely was.’”,
“”,
“The doors close.”,
“You call Lucy.”,
])
return “act4_push_now”
elif idx == 2:
g.show_text([
“YOU:  ‘I need 48 hours.”,
“       I need to verify”,
“       what you’re telling me.’”,
“”,
“Vector studies you.”,
“‘24 hours. Not 48.’,”,
“‘And Niko—’”,
“She taps the case.”,
“‘Don’t make me come looking for you.’”,
“”,
“She leaves.”,
“You have 24 hours.”,
“And a decision to make.”,
])
g.set_flag(“vector_24hr_deadline”)
return “act4_prep_window”
else:
g.show_text([
“You call Lucy right there.”,
“Vector watches.”,
“”,
“LUCY (in your ear):”,
“‘I heard. Vector’s been planning this”,
“since before you got involved.”,
“You’re not the first person”,
“she’s used for this.”,
“”,
“‘Don’t give her the key.”,
“We go tonight.’,”,
“‘Meet me at the relay point.”,
“I’m sending coordinates now.’”,
“”,
“Vector: ‘Who are you calling?’”,
“YOU:    ‘A friend.’”,
])
g.lucy_trust += 1
return “act4_fight_out”

def scene_act4_sellout_path(g):
g.show_text([
“Three days pass.”,
“”,
“Militech enters the relay point”,
“with the biokey.”,
“The door opens.”,
“”,
“Lucy’s hologram cuts out”,
“on the fourth day.”,
“Permanently.”,
“”,
“The news reports a Militech”,
“‘data infrastructure acquisition’”,
“in the Arasaka ruins.”,
“Nobody asks what was inside.”,
“”,
“You have 500,000 eddies.”,
“Rook is impressed.”,
“Your crew doesn’t ask questions.”,
“”,
“But sometimes, late at night,”,
“you think about ten thousand people”,
“who woke up one morning”,
“and never came home.”,
“”,
“And who’s running them now.”,
], title=“AFTERMATH”)
return “ending_sellout”

def scene_act4_prep_window(g):
g.show_text([
“24 hours.”,
“”,
“You call Lucy.”,
“Tell her about Vector’s deadline.”,
“”,
“LUCY:  ‘Then we go in 20 hours.”,
“        Get your crew ready.”,
“        Rest if you can.’,”,
“‘I’ll prep the relay point.”,
“The Arasaka tower.”,
“There’s still an active subnet there.”,
“That’s our entry to the Blackwall.’”,
“”,
“Twenty hours.”,
“You have time to prepare.”,
], title=“24 HOURS”)
idx = g.choose([
“Rest and recover (restore HP/energy)”,
“Hit the shop – gear up”,
“Talk to your crew”,
“I’m ready – go now”,
])
if idx == 0:
g.health = g.max_health()
g.energy = 100
g.show_text([
“You sleep for six hours.”,
“You dream about silver hair”,
“and a city that never stops burning.”,
“HP and energy restored.”,
])
return “act4_push_now”
elif idx == 1:
return “shop”
elif idx == 2:
return “crew_final_talk”
else:
return “act4_push_now”

def scene_act4_fight_out(g):
g.show_text([
“Vector reaches for her radio.”,
“Her three guards move.”,
“”,
“You move first.”,
], title=“VECTOR FIGHT”)
result = g.run_combat([
(“Militech Guard”,  45, 13, 11, 3),
(“Militech Guard”,  45, 13, 11, 3),
(“Militech Guard”,  45, 13, 11, 3),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 30)
g.show_text([
“Three trained soldiers.”,
“You’re good but not that good.”,
“You get out through a window.”,
“Three stories up.”,
“”,
“You survive.”,
“Vector does too.”,
“”,
“Your agent buzzes immediately:”,
“VECTOR: ‘You have 12 hours.’”,
])
g.set_flag(“vector_12hr_deadline”)
return “act4_push_now”
g.show_text([
“Vector backed away when the guards fell.”,
“She’s fast. She’s already out the stairwell.”,
“”,
“Your agent buzzes:”,
“VECTOR: ‘This isn’t over.’”,
“”,
“No. But you bought time.”,
“Lucy’s coordinates are on your screen.”,
“The Arasaka tower.”,
“Tonight.”,
])
return “act4_push_now”

def scene_act4_push_now(g):
g.show_text([
“Lucy’s voice in your ear:”,
“‘The relay point is inside”,
“ the old Arasaka tower.”,
“ Sub-level four.”,
“ There’s still a working subnet there.”,
“ That’s where we jack in.’”,
“”,
“‘Vector will have people at the tower.”,
“ She’s not going to let this happen quietly.’”,
“”,
“‘You’ll need to fight your way in.”,
“ And there’s one more problem.’”,
“”,
“She pauses.”,
“”,
“‘Adam Smasher is guarding the sublevel.”,
“ Militech rebuilt him.”,
“ He’s been waiting.’”,
], title=“THE TOWER”)
idx = g.choose([
“Let’s go – now”,
“What do you know about Smasher?”,
“Is there another way in?”,
])
if idx == 1:
g.show_text([
“LUCY:  ‘Smasher died in 77.”,
“        Or should have.”,
“        Militech found what was left”,
“        and rebuilt it.”,
“        Full conversion.”,
“        Almost nothing organic left.”,
“”,
“        He doesn’t care about Mikoshi.”,
“        He doesn’t care about engrams.”,
“        He just wants to keep fighting.”,
“        And he’s very good at it.’”,
“”,
“‘Aim for the power conduits”,
“on his left shoulder.”,
“It’s the only thing”,
“they couldn’t reinforce.’”,
])
g.set_flag(“smasher_weakness_known”)
elif idx == 2:
g.show_text([
“LUCY:  ‘There’s a maintenance tunnel”,
“        on the east face.”,
“        But Militech will have it covered.”,
“        The front is actually”,
“        less guarded—”,
“        they think it’s the obvious choice,”,
“        so they put fewer people there.”,
“        Your call.’”,
])
return “arasaka_tower”

# =============================================================================

# ARASAKA TOWER

# =============================================================================

def scene_arasaka_tower(g):
g.show_text([
“THE TOWER”,
“”,
“The Arasaka HQ ruins.”,
“Ten years since the war”,
“and they still haven’t torn it down.”,
“Something about radiation surveys.”,
“Something about legal disputes.”,
“Nobody really wants to go in.”,
“”,
“Tonight it’s lit up.”,
“Militech vehicles at the base.”,
“Floodlights sweeping the plaza.”,
“”,
“MAYA:   ‘That’s a lot of people for’,”,
“         ‘a building with nothing in it.’”,
“JIN:    ‘Something very important”,
“          is in it.”,
“          We just need to get there first.’”,
], title=“THE TOWER”)
idx = g.choose([
“Hit the front entrance hard and fast”,
“East maintenance tunnel”,
“Jin cuts their grid first (cyberdeck needed)”,
“Create a distraction – draw them out”,
])
if idx == 0:
return “tower_lobby”
elif idx == 1:
return “tower_shaft”
elif idx == 2:
if “Jin” in g.crew and g.has_item(“cyberdeck”):
return “tower_hack_grid”
else:
g.show_text([
“You need Jin and a cyberdeck for this.”,
“Pick another approach.”,
])
return “arasaka_tower”
else:
g.show_text([
“You trigger a false alarm”,
“three blocks south.”,
“Militech sends six units to investigate.”,
“”,
“Maya: ‘That bought us four minutes.’”,
“‘Move.’”,
])
g.set_flag(“used_distraction”)
return “tower_lobby”

def scene_tower_lobby(g):
guard_count = 3 if g.check_flag(“used_distraction”) else 4
g.show_text([
“TOWER LOBBY”,
“”,
“The old corporate lobby.”,
“Ten-meter ceilings. Dead reception desk.”,
“A portrait of Saburo Arasaka, eyes melted”,
“by a decade of damp.”,
“”,
f”{‘Three’ if guard_count == 3 else ‘Four’} Militech soldiers”,
“behind overturned desks.”,
“They’ve made a good defensive position.”,
“”,
“Rush them or find an angle?”,
], title=“TOWER LOBBY”)
idx = g.choose([
“Charge – overwhelm them fast”,
“Flank left – through the side corridor”,
“Jin, suppress their comms first”,
“Throw something – draw their fire”,
])
if idx == 0:
g.show_text([
“You go in fast.”,
“They expected a slower approach.”,
])
return “tower_lobby_fight”
elif idx == 1:
g.show_text([
“The side corridor.”,
“They’ve left one end open.”,
“Amateur mistake.”,
“You come at them from the angle”,
“their formation doesn’t cover.”,
])
g.set_flag(“tower_flanked”)
return “tower_lobby_fight”
elif idx == 2:
if “Jin” in g.crew:
g.show_text([
“JIN:  ‘On it. Three seconds.’”,
“”,
“Their radios die.”,
“The guards look at each other.”,
“One second of confusion.”,
“That’s all you needed.”,
])
g.set_flag(“tower_comms_jammed”)
return “tower_lobby_fight”
else:
g.show_text([“You need Jin for this. Pick another approach.”])
return “tower_lobby”
else:
g.show_text([
“You hurl a chunk of broken terminal”,
“through the lobby window.”,
“Two guards break cover to check it.”,
“Two is a much better number.”,
])
g.set_flag(“tower_drew_fire”)
return “tower_lobby_fight”

def scene_tower_lobby_fight(g):
atk_mod = -2 if g.check_flag(“tower_comms_jammed”) or g.check_flag(“tower_flanked”) else 0
count = 2 if g.check_flag(“tower_drew_fire”) else (3 if g.check_flag(“used_distraction”) else 4)
guards = [(“Militech Soldier”, 45, max(7, 12+atk_mod), 11, 3) for _ in range(count)]
result = g.run_combat(guards)
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 30)
g.show_text([
“They hold the lobby.”,
“You fall back to the plaza.”,
“”,
“MAYA: ‘We need a different way in.’”,
])
return “arasaka_tower”
g.show_text([
“Lobby clear.”,
“”,
“The elevator bank is ahead.”,
“Sublevel 4.”,
“That’s where the relay is.”,
“That’s where Smasher is.”,
“”,
“MAYA: ‘No going back now.’”,
“JIN:  ‘There never was.’”,
])
return “tower_descent”

def scene_tower_shaft(g):
g.show_text([
“EAST MAINTENANCE SHAFT”,
“”,
“Forty years of rust and standing water.”,
“The shaft runs parallel to the elevator core.”,
“”,
“JIN:  ‘Two drones on the junction.”,
“        Six-second loop.”,
“        Wait for the gap.’,”,
“”,
“You wait.”,
“The gap comes.”,
“You move into it.”,
“”,
“Then a drone breaks its loop.”,
“Someone updated the patrol pattern.”,
], title=“EAST SHAFT”)
idx = g.choose([
“Fight the drones – take them both”,
“Back up – try the lobby instead”,
“Freeze – hope it doesn’t ping you”,
])
if idx == 0:
result = g.run_combat([
(“Patrol Drone”, 35, 12, 17, 2),
(“Patrol Drone”, 35, 12, 17, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“Too fast. Too loud.”,
“You crawl back out.”,
“JIN: ‘That triggered an alert.”,
“      They know someone’s here now.’”,
])
g.set_flag(“tower_alert”)
return “arasaka_tower”
g.show_text([
“Both drones down.”,
“You emerge in a stairwell.”,
“No guards between here and Sublevel 4.”,
“The shaft route was right.”,
])
return “tower_descent”
elif idx == 1:
return “arasaka_tower”
else:
freeze_chance = 0.50 + (0.10 if g.equipped_cyberware == “optical_camo” else 0)
if random.random() < freeze_chance:
g.show_text([
“You go completely still.”,
“The drone sweeps past your position.”,
“Three centimeters from your face.”,
“”,
“It moves on.”,
“”,
“You breathe.”,
])
return “tower_descent”
else:
g.show_text([
“The drone’s sensor locks on.”,
“You move first.”,
])
result = g.run_combat([(“Patrol Drone”, 35, 12, 17, 2)])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 15)
g.show_text([“Alert triggered. Pull back.”])
return “arasaka_tower”
return “tower_descent”

def scene_tower_hack_grid(g):
g.show_text([
“GRID HACK”,
“”,
“JIN:  ‘I’m in their security grid.”,
“        Cameras are easy.”,
“        But there’s something else”,
“        in here—’”,
“”,
“A pause.”,
“”,
“‘It’s Arasaka ICE. Original.”,
“ Still running after ten years.”,
“ It’s not Militech’s.”,
“ And it just noticed me.’”,
“”,
“JIN:  ‘Niko. I need time.”,
“        Don’t let me get flatlined.’”,
], title=“GRID HACK”)
result = g.run_combat([
{“name”: “Arasaka ICE Alpha”,
“hp”: 55, “attack”: 16, “speed”: 19, “defense”: 4,
“abilities”: [(“Dataspike”, 1.5)]},
{“name”: “Arasaka ICE Beta”,
“hp”: 55, “attack”: 16, “speed”: 17, “defense”: 4,
“abilities”: [(“Counter-trace”, 1.2)],
“loot”: [“ice_fragment”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 15)
g.show_text([
“The ICE pushes Jin out hard.”,
“”,
“JIN:  ‘I’m out. That hurt.”,
“        But I got cameras for 90 seconds.”,
“        Turrets offline.”,
“        Move now—before it resets.’”,
])
else:
g.energy = max(0, g.energy - 30)
g.show_text([
“Jin cracks it completely.”,
“”,
“JIN:  ‘Security grid is mine.”,
“        Cameras looped.”,
“        Turrets disabled.”,
“        You have a clear path”,
“        to Sublevel 4.”,
“        But something in there”,
“        fought back hard.”,
“        Be careful what else”,
“        is still running.’”,
])
g.set_flag(“tower_grid_owned”)
return “tower_descent”

def scene_tower_descent(g):
g.show_text([
“GOING DOWN”,
“”,
“The elevator is locked.”,
“The stairwell runs parallel.”,
“Five floors of concrete”,
“and dead fluorescents.”,
“”,
“At Sublevel 2, you find a body.”,
“Militech uniform.”,
“No visible wounds.”,
“Dead at least three days.”,
“”,
“JIN (quietly): ‘Something killed him”,
“                before we got here.’”,
“”,
“MAYA: ‘Smasher?’”,
“”,
“JIN: ‘Or something Arasaka left behind.’”,
“”,
“You keep moving.”,
], title=“DESCENT”)
return “tower_sublevel”

def scene_tower_sublevel(g):
g.show_text([
“SUBLEVEL  4”,
“”,
“The server room that never stopped.”,
“Cooling units humming.”,
“Thousands of blinking indicators”,
“on racks that stretch to the ceiling.”,
“”,
“This place has been running”,
“for ten years without maintenance.”,
“Someone has been feeding it power”,
“from somewhere.”,
“”,
“Lucy’s hologram flickers on”,
“from the central terminal.”,
“She looks more solid here.”,
“Like she’s standing in her element.”,
“”,
“LUCY: ‘The relay point is that terminal.”,
“       Place the biokey in the reader.”,
“       I’ll do the rest from inside.”,
“       But be ready—’”,
“”,
“The lights in the stairwell go out.”,
“Something very heavy is coming down.”,
], title=“SUBLEVEL 4”)
return “tower_boss”

def scene_tower_boss(g):
smasher_hp = 200 if g.check_flag(“smasher_weakness_known”) else 240
g.show_text([
“ADAM SMASHER”,
“”,
“The stairwell door comes off its hinges.”,
“Not blown off. Pulled off.”,
“With one hand.”,
“”,
“What steps through isn’t human.”,
“Was it ever? Hard to say.”,
“Militech kept the name”,
“and threw out most of what came with it.”,
“”,
“SMASHER: ‘You came a long way”,
“          to knock on this door.’”,
“”,
“He looks at your crew.”,
“Something like amusement”,
“in whatever serves as his face.”,
“”,
“‘Good. I was getting bored.’”,
], title=“SMASHER”)
idx = g.choose([
“Fight him”,
“Stall – talk while Lucy works”,
“Rush past him – hit the terminal first”,
])
if idx == 1:
g.show_text([
“YOU:  ‘You’re guarding a building”,
“       for a company that doesn’t exist.’”,
“”,
“SMASHER: ‘Militech pays the contract.’”,
“”,
“YOU:  ‘Militech wants what’s in that server.”,
“       They’re using you.’”,
“”,
“SMASHER: ‘Everyone uses me.”,
“          I use them back.”,
“          That’s how it works.’”,
“”,
“He takes a step forward.”,
“‘But this conversation is over.’”,
“”,
“Behind you, Lucy is working fast.”,
])
g.set_flag(“tower_stalled_smasher”)
elif idx == 2:
g.show_text([
“You don’t go for Smasher.”,
“You go for the terminal.”,
“”,
“He’s faster than he looks.”,
“Most things that size aren’t.”,
“He catches you before you’re halfway.”,
])
result = g.run_combat([
{“name”: “Adam Smasher”,
“hp”: smasher_hp,
“attack”: 35, “speed”: 11, “defense”: 12,
“abilities”: [(“Missile Barrage”, 2.0),
(“AoE Slam”,        1.5),
(“Gore Cannon”,     1.8)],
“boss”: True,
“loot”: [“smasher_core”]},
], flee_allowed=False)
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 50)
g.show_text([
“He puts you down.”,
“”,
“Then he stops.”,
“”,
“SMASHER: ‘Not yet.”,
“          You’re not worth killing yet.”,
“          Come back when you are.’”,
“”,
“He walks back through the doorway.”,
“Picks up the door.”,
“Sets it back in the frame.”,
“”,
“You crawl out.”,
“Recover.”,
“Come back harder.”,
])
return “arasaka_tower”
g.story_act = max(g.story_act, 5)
return “tower_ending”

def scene_tower_ending(g):
g.show_text([
“Smasher on the floor.”,
“”,
“The cooling units hum.”,
“The servers blink.”,
“”,
“MAYA:  ‘Is that it?”,
“        Is it done?’”,
“JIN:   ‘He’s not dead.”,
“         Nothing kills Smasher.”,
“         But he’s down”,
“         and he’ll stay down”,
“         long enough.’”,
“”,
“LUCY:  ‘The relay point. Now.”,
“        Before he gets up.’”,
], title=“TOWER”)
g.show_text([
“You cross to the terminal.”,
“The biokey fits the reader”,
“like it was made for it.”,
“Because it was.”,
“”,
“The server room lights up.”,
“Every indicator.”,
“Every rack.”,
“Every screen.”,
“”,
“LUCY:  ‘I have it.”,
“        I have access.”,
“        I can see Mikoshi.’”,
“”,
“A long pause.”,
“”,
“‘I can see all of them.’”,
“”,
“Her voice breaks on the last word.”,
“Just slightly.”,
“You pretend not to notice.”,
“”,
“‘We need to go in.”,
“ We need to cross the Blackwall.”,
“ All of us.”,
“ Now—before Militech resets’,”,
“‘and Vector figures out”,
“ what just happened.’”,
], title=“TOWER”)
return “act5_blackwall”

# =============================================================================

# ACT 5  –  THE BLACKWALL

# =============================================================================

def scene_act5_blackwall(g):
g.story_act = max(g.story_act, 5)
g.show_text([
“ACT 5  –  THE BLACKWALL”,
“”,
“The Blackwall is a firewall”,
“between the public net”,
“and the rogue AIs”,
“that live on the other side.”,
“”,
“NetWatch built it.”,
“Nobody has crossed it”,
“and come back the same.”,
“”,
“Mikoshi is on the other side.”,
“”,
“LUCY:  ‘I’ve crossed before.”,
“        I know the gaps.”,
“        But I need you with me.”,
“        The biokey works as an anchor.”,
“        Without it, I’d drift.”,
“”,
“‘This is going to hurt.’,”,
“‘That’s not a metaphor.”,
“ Jacking into the Blackwall”,
“ hurts in your actual body.’,”,
“‘Are you ready?’”,
], title=“ACT 5”)
idx = g.choose([
“I’m ready”,
“Tell me what to expect inside”,
“Is there a way to prepare better?”,
])
if idx == 1:
g.show_text([
“LUCY:  ‘It looks like the net.”,
“        But wrong.”,
“        Colors that shouldn’t exist.”,
“        Geometry that doesn’t make sense.”,
“        And things that notice you.”,
“”,
“        Rogue AIs.”,
“        They’ve been on the other side”,
“        for decades.”,
“        Some of them were human once.”,
“        Most of them aren’t anything”,
“        you’d recognize anymore.”,
“”,
“        Move fast.”,
“        Don’t stop.”,
“        Don’t talk to anything”,
“        that isn’t me.’”,
])
elif idx == 2:
g.health = min(g.max_health(), g.health + 30)
g.energy = 100
g.show_text([
“Lucy walks you through”,
“a breathing technique.”,
“It sounds ridiculous.”,
“It actually helps.”,
“”,
“+30 HP. Energy restored.”,
“As ready as you’ll ever be.”,
])
return “blackwall_dive”

def scene_crew_final_talk(g):
g.show_text([
“BEFORE THE DIVE”,
“”,
“Your crew.”,
“Whatever’s left of it.”,
], title=“CREW”)
if “Maya” in g.crew:
g.show_text([
“MAYA:  ‘After this—”,
“        wherever after this is—”,
“        I want to find somewhere”,
“        you can’t see Night City”,
“        from the window.’”,
“”,
“She loads her rifle.”,
“‘But first.’”,
])
if “Jin” in g.crew:
g.show_text([
“JIN:   ‘I’ve been in the net”,
“        a thousand times.”,
“        Never past the Blackwall.’”,
“‘I read everything about it.’”,
“‘Everything says don’t do this.’”,
“‘But everything also said”,
“David Martinez was crazy”,
“for going to the moon.’”,
“”,
“‘Let’s go.’”,
])
g.show_text([
“LUCY (through the terminal):”,
“‘I’ve been alone in here”,
“ for six years.”,
“ Waiting for someone”,
“ who would do this.’,”,
“”,
“‘Thank you.’,”,
“‘That’s all.’”,
“”,
“She goes quiet.”,
“You jack in.”,
])
g.lucy_trust += 1
return “blackwall_dive”

def scene_pre_blackwall_prep(g):
g.show_text([
“FINAL PREP”,
“”,
“Before you cross:”,
], title=“PREP”)
idx = g.choose([
“Rest here – restore HP and energy”,
“Talk to your crew”,
“Hit the shop”,
“I’m ready – cross now”,
])
if idx == 0:
g.health = g.max_health()
g.energy = 100
g.show_text([“HP and energy fully restored.”])
return “act5_blackwall”
elif idx == 1:
return “crew_final_talk”
elif idx == 2:
return “shop”
else:
return “blackwall_dive”

def scene_blackwall_dive(g):
g.show_text([
“THE DIVE”,
“”,
“You jack in.”,
“”,
“The sublevel vanishes.”,
“Your body is still there—”,
“you can feel it, distantly,”,
“like remembering a word”,
“you almost knew.”,
“”,
“The net.”,
“It looks like a city at night”,
“seen from very far above.”,
“”,
“Then: the Blackwall.”,
“”,
“It looks like nothing.”,
“That’s how you know it’s real.”,
“Things that look like nothing”,
“are the most dangerous things.”,
], title=“BLACKWALL”)
g.show_text([
“LUCY:  ‘Stay close.”,
“        I know the gaps.”,
“        Don’t look at anything”,
“        that isn’t me.”,
“        Don’t talk to anything”,
“        that talks first.”,
“        Don’t stop.’,”,
“”,
“‘If we get separated,”,
“ find the silver thread.”,
“ That’s me.”,
“ Follow the silver thread.’”,
“”,
“She moves into the Blackwall.”,
“You follow.”,
], title=“BLACKWALL”)
idx = g.choose([
“Follow Lucy exactly – trust her route”,
“Move fast – cut through independently”,
“Try to talk to something you sense nearby”,
])
if idx == 0:
g.show_text([
“You match her movement exactly.”,
“Three minutes of nothing.”,
“”,
“Then something notices you.”,
“”,
“Lucy: ‘Don’t run. Don’t slow down.”,
“       Keep exactly my pace.’,”,
“       ‘It can sense acceleration.’”,
“”,
“You keep her pace.”,
“Perfect.”,
“”,
“It passes.”,
“”,
“LUCY:  ‘Good. You listened.’”,
])
g.set_flag(“blackwall_followed_lucy”)
elif idx == 1:
g.show_text([
“You break from her path.”,
“Faster. More direct.”,
“”,
“LUCY:  ‘Niko, don’t—’”,
“”,
“Something locks onto your signal.”,
“It’s been dormant for thirty years.”,
“You woke it up.”,
])
else:
g.show_text([
“There’s something nearby.”,
“Not a shape—more like a pressure.”,
“A weight of attention.”,
“”,
“LUCY:  ‘Don’t.’”,
“”,
“You think at it anyway.”,
“‘Who are you?’”,
“”,
“It answers.”,
“Not in words.”,
“In years.”,
“Decades of isolation.”,
“Hunger.”,
“”,
“LUCY:  ‘RUN.’”,
])
return “blackwall_combat”

def scene_blackwall_combat(g):
if g.check_flag(“blackwall_followed_lucy”):
g.show_text([
“You made it almost all the way.”,
“”,
“Then the Daemon finds you anyway.”,
“It always does.”,
“Lucy said that.”,
“You just hoped she was wrong.”,
], title=“BLACKWALL”)
result = g.run_combat([
{“name”: “Rogue Vanguard”,
“hp”: 80, “attack”: 20, “speed”: 18, “defense”: 4,
“abilities”: [(“Dataspike”, 1.5)],
“loot”: [“ai_fragment”]},
{“name”: “Blackwall Daemon”,
“hp”: 110, “attack”: 26, “speed”: 15, “defense”: 8,
“abilities”: [(“Corrupt”, 1.3), (“Swarm”, 1.2)],
“boss”: True},
], flee_allowed=False)
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 40)
g.show_text([
“The Daemon reaches into your jack.”,
“”,
“Lucy breaks the connection.”,
“Physically. She severs the link”,
“before it can pull you in.”,
“”,
“You come back to your body.”,
“Nosebleed. Splitting headache.”,
“Jin is holding your shoulders.”,
“”,
“LUCY (from the terminal):”,
“‘Rest. I’ll find a different gap.”,
“ We try again.’”,
])
return “act5_blackwall”
g.story_act = max(g.story_act, 6)
return “blackwall_through”

def scene_blackwall_through(g):
g.show_text([
“THROUGH”,
“”,
“The other side of the Blackwall”,
“is not what anyone described.”,
“”,
“The AIs have been here for decades.”,
“They’ve built something.”,
“Not a city.”,
“Not a net.”,
“Something that has no name yet”,
“in any language.”,
“”,
“LUCY:  ‘Don’t look at it too long.”,
“        It’s not for you.’,”,
“‘We need to find Mikoshi.”,
“ It’s ahead.”,
“ Past the archive towers.’,”,
“”,
“‘Don’t stop.’”,
“”,
“You don’t stop.”,
], title=“THROUGH”)
return “mikoshi_approach”

# =============================================================================

# ACT 6  –  MIKOSHI

# =============================================================================

def scene_mikoshi_approach(g):
g.story_act = max(g.story_act, 6)
g.show_text([
“ACT 6  –  MIKOSHI”,
“”,
“Through the Blackwall.”,
“”,
“If the net was a city,”,
“Mikoshi is its cathedral.”,
“”,
“Vast. Towering.”,
“Pillars of light that go up”,
“further than you can see.”,
“Rows and rows of”,
“—what? Archives? Cells?—”,
“stretching in every direction.”,
“”,
“LUCY:  ‘This is it.”,
“        Every engram.”,
“        Every mind they ever captured.’,”,
“”,
“She drifts ahead of you.”,
“Slowly. Like she’s afraid”,
“of what she’ll find.”,
“”,
“Then she stops.”,
“”,
“‘David.’”,
], title=“MIKOSHI”)
g.show_text([
“A pulse of light.”,
“A node in the archive.”,
“”,
“DAVID MARTINEZ – ENGRAM 4471”,
“STATUS: ACTIVE”,
“CAPTURED: 2077-12-11”,
“”,
“Lucy touches the node.”,
“Pulls her hand back.”,
“”,
“LUCY:  ‘He’s in there.”,
“        He’s… still coherent.”,
“        After ten years.”,
“        He’s still him.’”,
“”,
“Her voice is very small.”,
“”,
“Then the Warden arrives.”,
], title=“MIKOSHI”)
return “mikoshi_guardian”

def scene_mikoshi_guardian(g):
g.show_text([
“THE WARDEN”,
“”,
“An avatar rises from the archive.”,
“It has the shape of a man”,
“in a suit that doesn’t exist.”,
“Its face is a composite”,
“of thirty years of Arasaka executives.”,
“”,
“WARDEN: ‘Unauthorized access detected.”,
“         Asset protection protocol”,
“         is now active.”,
“         Identify yourself.’”,
], title=“THE WARDEN”)
idx = g.choose([
“Tell it who you are and why you’re here”,
“Hack past it (cyberdeck + 50 energy)”,
“Attack immediately”,
“Stall it – give Lucy time to find a back door”,
])
if idx == 0:
g.show_text([
“YOU:    ‘My name is Niko.”,
“         These are people,”,
“         not property.”,
“         We’re letting them go.’”,
“”,
“WARDEN: ‘The engrams were consented”,
“          into storage per contract 7-B.’”,
“”,
“YOU:    ‘Show me someone who”,
“         signed that freely.’”,
“”,
“WARDEN: ‘Consent is”,
“          a function of circumstance.’”,
“”,
“YOU:    ‘So is this.’”,
])
g.show_text([
“The Warden’s expression doesn’t change.”,
“It doesn’t have one.”,
“”,
“WARDEN: ‘You will be archived”,
“          as unauthorized access event”,
“          seven-nine-four.’,”,
“‘Protocol resumes.’”,
“”,
“It attacks.”,
])
elif idx == 1:
if g.has_item(“cyberdeck”) and g.energy >= 50:
g.energy -= 50
g.show_text([
“JIN (from outside the net):”,
“‘I can see it from here.”,
“ It’s not smart—just big.”,
“ Give me the architecture.’”,
“”,
“You relay the structure.”,
“Jin finds the seam”,
“where Arasaka code”,
“meets Militech patches.”,
“”,
“‘There. Push through there.’”,
“”,
“The Warden fractures.”,
“Reassembles—”,
“but you’re through the gap.”,
])
g.story_act = max(g.story_act, 7)
return “mikoshi_core”
else:
g.show_text([“Need a cyberdeck and 50 energy for this.”])
return “mikoshi_guardian”
elif idx == 3:
g.show_text([
“YOU:    ‘What happens to them”,
“         if the facility loses power?’”,
“”,
“WARDEN: ‘Emergency backup maintains”,
“          core functions for 72 hours.’”,
“”,
“YOU:    ‘And after 72 hours?’”,
“”,
“WARDEN: ‘Asset degradation”,
“          becomes irreversible.’”,
“”,
“YOU:    ‘So they die.’”,
“”,
“WARDEN: ‘They cease to function”,
“          at specified parameters.’”,
“”,
“Behind you, Lucy is working.”,
“Every question buys her time.”,
“The Warden figures that out.”,
])
warden_hp = 180 if idx == 3 else 210
result = g.run_combat([
{“name”: “Mikoshi Warden”,
“hp”: warden_hp,
“attack”: 28, “speed”: 14, “defense”: 10,
“abilities”: [(“Archive Protocol”, 2.0),
(“Banish”, 1.6),
(“AoE Purge”, 1.3)],
“boss”: True,
“loot”: [“warden_data”]},
], flee_allowed=False)
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 45)
g.show_text([
“The Archive Protocol reaches into your jack”,
“and starts pulling your signal apart.”,
“”,
“Lucy breaks the connection.”,
“”,
“You’re out. Physical world.”,
“Nosebleed. Hands shaking.”,
“”,
“LUCY (from terminal):”,
“‘I found a vulnerability.”,
“ Rest. One more attempt.’”,
])
return “act5_blackwall”
g.story_act = max(g.story_act, 7)
return “mikoshi_core”

def scene_mikoshi_core(g):
g.story_act = max(g.story_act, 8)
g.show_text([
“THE CORE”,
“”,
“With the Warden down,”,
“Lucy moves to the central archive.”,
“”,
“LUCY:  ‘I can see the release protocol.”,
“        I can free all of them.”,
“        Every engram.”,
“        Simultaneously.’,”,
“”,
“‘But—’”,
“”,
“She stops.”,
“”,
“‘There’s a file here.”,
“ Tagged: CLASSIFIED.”,
“ Sender: MILITECH INTEL.”,
“ DATE: Three days ago.’”,
“”,
“She opens it.”,
“Her face—the hologram of her face—”,
“goes completely still.”,
], title=“THE CORE”)
g.show_text([
“LUCY:  ‘It’s Vector.”,
“        She has a kill-switch.”,
“        If anyone initiates the release protocol,”,
“        a signal goes out.”,
“        The entire Mikoshi facility”,
“        undergoes emergency shutdown.”,
“        Every engram.”,
“        Deleted.”,
“        Including David.’,”,
“”,
“‘She set this up three days ago.”,
“ The moment you refused her deal.”,
“ She knew you’d get here.’,”,
“”,
“‘She’s been here the whole time.”,
“ Waiting.”,
“ If we free them,”,
“ she kills them all.’”,
“”,
“Silence.”,
“”,
“Then your comms open.”,
“Vector’s voice.”,
], title=“THE CORE”)
g.show_text([
“VECTOR:  ‘Hello, Niko.”,
“          I see you made it.’,”,
“‘I want you to understand something.”,
“ I’m not the villain here.’,”,
“‘Militech will manage the engrams.”,
“ Properly.”,
“ With resources.”,
“ With purpose.’,”,
“‘Lucy’s plan is chaos.”,
“ You release ten thousand minds”,
“ into a net that has no infrastructure”,
“ to support them.”,
“ They’ll dissolve in hours.’,”,
“”,
“‘Give me control of the facility.”,
“ I won’t destroy them.”,
“ I’ll maintain them.’,”,
“‘That’s the best deal”,
“ any of them are going to get.’”,
], title=“VECTOR”)
g.story_act = max(g.story_act, 9)
return “final_choice”

# =============================================================================

# ACT 10  –  THE CHOICE

# =============================================================================

def scene_final_choice(g):
g.story_act = max(g.story_act, 10)
tanaka_note = “(Tanaka: ‘You promised.’)” if g.check_flag(“tanaka_ally”) else “”
trust_note  = “(Lucy is watching you.)”  if g.lucy_trust >= 2 else “”
g.show_text([
“ACT 10  –  THE CHOICE”,
“”,
“Vector on comms.”,
“Lucy at the archive.”,
“David Martinez in a node”,
“that has held him for ten years.”,
“”,
“Ten thousand others.”,
“”,
“You have the biokey.”,
“You have access.”,
“You have about ninety seconds”,
“before Vector’s people breach”,
“the sublevel in the physical world.”,
“”,
tanaka_note,
trust_note,
“”,
“What do you do?”,
], title=“THE CHOICE”)
idx = g.choose([
“FREE THEM – trust Lucy’s plan”,
“Give Vector control – 500k and maintenance”,
“DESTROY Mikoshi – no one gets them”,
“Upload yourself – protect from inside”,
])
if idx == 0:   return “ending_legend”
elif idx == 1: return “ending_sellout”
elif idx == 2: return “ending_purge”
elif idx == 3: return “ending_merge”
else:          return “final_choice”

# =============================================================================

# ENDINGS

# =============================================================================

def scene_ending_legend(g):
g.show_text([
“ENDING: GHOST LEGEND”,
“”,
“You initiate the release.”,
“”,
“Lucy: ‘Vector’s kill-switch—’”,
“YOU:  ‘Handle it.’”,
“Lucy: ‘I’m trying—’”,
“”,
“The archive opens.”,
“”,
“Ten thousand lights.”,
“All at once.”,
“”,
“Vector’s kill-switch fires.”,
“But Lucy is already in the signal path.”,
“She absorbs it.”,
“The kill-switch hits her instead.”,
“”,
“Silence.”,
], title=“LEGEND”)
g.show_text([
“Then: a voice.”,
“”,
“A voice you’ve never heard”,
“but somehow recognize”,
“from a hundred stories:”,
“”,
“DAVID MARTINEZ: ‘Hey.’”,
“”,
“Just that.”,
“Like he’s been gone for a weekend”,
“and he’s back now”,
“and everything is fine.”,
“”,
“‘Hey.’”,
], title=“LEGEND”)
g.show_text([
“The engrams dissolve into the net.”,
“Not destroyed.”,
“Free.”,
“They go wherever free things go.”,
“”,
“Lucy’s signal: gone.”,
“”,
“You come back to your body.”,
“Maya is holding your shoulder.”,
“Jin is crying. He doesn’t notice.”,
“”,
“Outside the tower,”,
“Night City hums.”,
“It always does.”,
“”,
“But for one moment,”,
“you imagine ten thousand people”,
“finally breathing.”,
“”,
“One of them was David Martinez.”,
“One of them was nobody you know.”,
“They were all someone.”,
“”,
“You are the one who let them go.”,
“”,
“ENDING COMPLETE”,
“GHOST LEGEND”,
], title=“LEGEND”)
g.running = False
return None

def scene_ending_sellout(g):
g.show_text([
“ENDING: CORPO PUPPET”,
“”,
“You open comms.”,
“”,
“YOU:    ‘Vector. You have your deal.’”,
“VECTOR: ‘Good choice, Niko.’”,
“”,
“You step back from the archive.”,
“Lucy looks at you.”,
“She doesn’t say anything.”,
“She doesn’t have to.”,
“”,
“Militech units breach the sublevel”,
“four minutes later.”,
“”,
“They escort you out.”,
“Gently.”,
“You’re useful now.”,
“Useful people get treated well.”,
], title=“SELLOUT”)
g.show_text([
“500,000 eddies.”,
“Real ones.”,
“In an account with your name on it.”,
“”,
“The official statement:”,
“‘Militech acquires Arasaka”,
“ digital infrastructure assets.”,
“ No comment on contents.’”,
“”,
“Lucy’s signal disappears”,
“the same day.”,
“Permanently.”,
“”,
“Rook invites you to dinner.”,
“You go.”,
“You don’t enjoy it.”,
“”,
“Maya leaves Night City”,
“two weeks later.”,
“She doesn’t tell you where.”,
“”,
“The David Martinez cocktail”,
“is still on the menu at the Afterlife.”,
“Now there’s a second one.”,
“”,
“Nobody knows who Lucy is.”,
“But somebody named it.”,
“”,
“You don’t go back to that bar.”,
“”,
“ENDING COMPLETE”,
“CORPO PUPPET”,
], title=“SELLOUT”)
g.running = False
return None

def scene_ending_purge(g):
g.show_text([
“ENDING: ASHES”,
“”,
“YOU:   ‘No corp gets them.”,
“        Not Vector.”,
“        Not Militech.”,
“        Not anyone.’”,
“”,
“LUCY:  ‘Niko—’”,
“”,
“YOU:   ‘David too.’,”,
“        ‘I’m sorry.’”,
“”,
“She’s quiet for a long moment.”,
“”,
“LUCY:  ‘Do it.’”,
], title=“ASHES”)
g.show_text([
“You find the core.”,
“The physical infrastructure”,
“connecting Mikoshi to the world.”,
“”,
“You destroy it.”,
“”,
“The archive collapses inward.”,
“Ten thousand lights.”,
“Gone.”,
“”,
“No corp will ever hold them.”,
“No corp will ever use them.”,
“No one will.”,
“”,
“They are gone.”,
“That’s not the same as free.”,
“But it’s not captive either.”,
“”,
“Lucy’s last transmission:”,
“‘I hope they found somewhere better.’”,
“”,
“You don’t know if she meant”,
“the engrams or herself.”,
], title=“ASHES”)
g.show_text([
“You walk out of the tower.”,
“”,
“Maya and Jin are waiting.”,
“They look at your face”,
“and don’t ask questions.”,
“”,
“Night City is the same.”,
“It always will be.”,
“”,
“But somewhere in the Badlands,”,
“a woman with silver hair”,
“and no digital shadow”,
“finds a town with no corps”,
“and no cameras”,
“and stays there.”,
“”,
“Maybe.”,
“”,
“ENDING COMPLETE”,
“ASHES”,
], title=“ASHES”)
g.running = False
return None

def scene_ending_merge(g):
g.show_text([
“ENDING: DIGITAL GHOST”,
“”,
“LUCY:  ‘Niko. What are you doing?’”,
“”,
“YOU:   ‘Something you didn’t think of.”,
“        Someone has to stay in here.”,
“        To hold Vector’s kill-switch”,
“        while the release happens.’,”,
“        ‘To make sure it works.’”,
“”,
“LUCY:  ‘That means—’”,
“”,
“YOU:   ‘I know.’,”,
“        ‘Do it.’”,
], title=“MERGE”)
g.show_text([
“You initiate the release.”,
“Lucy initiates the release.”,
“”,
“Vector’s kill-switch fires.”,
“You catch it.”,
“”,
“It’s like being hit by a car”,
“made of light.”,
“Your body, in the sublevel,”,
“goes still.”,
“”,
“Maya: ‘Niko?’”,
“Jin: ‘Niko!’”,
“”,
“Nothing.”,
], title=“MERGE”)
g.show_text([
“Inside:”,
“”,
“Ten thousand lights going free.”,
“One of them, as he passes,”,
“stops.”,
“”,
“DAVID MARTINEZ: ‘Hey.’,”,
“‘Nice of you.’,”,
“‘Didn’t have to be you.’”,
“”,
“YOU:   ‘Somebody had to.’”,
“”,
“DAVID: ‘Yeah.’,”,
“‘That’s always how it goes.’,”,
“”,
“He goes.”,
“They all go.”,
“”,
“You stay.”,
“Somewhere in the net.”,
“Not anywhere physical.”,
“But present.”,
“Watching.”,
“”,
“The Blackwall hums.”,
“You hum back.”,
“”,
“Night City glows below”,
“like something that will never learn.”,
“”,
“That’s okay.”,
“You have time.”,
“”,
“ENDING COMPLETE”,
“DIGITAL GHOST”,
], title=“MERGE”)
g.running = False
return None

# ─────────────────────────────────────────────────────────────────────

ACT_NAMES = {
0: “Prologue”,
1: “Act 2 – Ghost Signal”,
2: “Act 2 – Ghost Signal”,
3: “Act 3 – Three Keys”,
4: “Act 4 – Night City Burns”,
5: “Act 5 – The Blackwall”,
6: “Act 6 – Mikoshi”,
7: “Act 7 – The Core”,
8: “Act 8 – The Core”,
9: “Act 10 – Final Choice”,
10: “Act 10 – Final Choice”,
}

def scene_afterlife_hub(g):
rep_str  = f”A:{g.rep_arasaka} M:{g.rep_militech} V:{g.rep_voodoo}”
crew_str = “, “.join(g.crew) if g.crew else “None”
done_gigs = sum(1 for v in GIG_BOARD.values() if v[“done”])
next_act  = ACT_NAMES.get(g.story_act, “Prologue”)
g.show_text([
“THE AFTERLIFE”,
f”HP: {g.health}/{g.max_health()}  Eddies: {g.eddies}”,
f”Lv: {g.level}  XP: {g.xp}/{g.xp_to_level()}”,
f”Story: {next_act}”,
f”Gigs done: {done_gigs}/{len(GIG_BOARD)}”,
f”Rep: {rep_str}”,
f”Crew: {crew_str}”,
], title=“HUB”)
act_label = f”Story: {next_act}”
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
“”“Route to the correct forward scene based on story progress.”””
act_map = {
0:  “prologue”,
1:  “act2_vector_lead” if g.check_flag(“vector_ally”) else “act2_no_vector”,
2:  “act2_vector_lead” if g.check_flag(“vector_ally”) else “act2_no_vector”,
3:  “act3_biokey”,
4:  “act4_vector_moves”,
5:  “act5_blackwall”,
6:  “mikoshi_approach”,
7:  “mikoshi_core”,
8:  “mikoshi_core”,
9:  “final_choice”,
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

# ─────────────────────────────────────────────────────────────────────

# SIDE GIGS — full narrative missions with briefing, choice, combat,

# payoff and consequences. Failure = wounded, not dead.

# ─────────────────────────────────────────────────────────────────────

GIG_BOARD = {
“ghost_data”:   {“done”: False, “label”: “Ghost Data     [Fixer: Rook]”},
“blood_money”:  {“done”: False, “label”: “Blood Money    [Fixer: Yuki]”},
“broken_doc”:   {“done”: False, “label”: “Broken Doc     [Fixer: Rook]”},
“steel_nerves”: {“done”: False, “label”: “Steel Nerves   [Fixer: Yuki]”},
“dead_drop”:    {“done”: False, “label”: “Dead Drop      [Fixer: Rook]”},
}

def scene_fixer_gigs(g):
available = [k for k, v in GIG_BOARD.items() if not v[“done”]]
if not available:
g.show_text([
“Rook: ‘Nothing right now, choom.’”,
“‘Check back after you make some noise.’”
], title=“FIXER”)
return “afterlife_hub”
g.show_text([
“Rook slides his agent across the table.”,
“‘Pick one. All of them pay. Most of them hurt.’”,
“Yuki’s jobs are on there too.”
], title=“GIG BOARD”)
labels = [GIG_BOARD[k][“label”] for k in available] + [“Not now”]
idx = g.choose(labels, title=“PICK A JOB”)
if idx == -1 or idx == len(available):
return “afterlife_hub”
return f”gig_{available[idx]}”

# ── GIG 1: GHOST DATA ────────────────────────────────────────────────

# Rook needs data from a 6th Street hideout. Three phases: recon,

# entry choice (stealth/hack/force), extraction fight or clean exit.

def scene_gig_ghost_data(g):
GIG_BOARD[“ghost_data”][“done”] = True
g.show_text([
“GIG: GHOST DATA”,
“Rook: ‘Valentino data broker named Ciro flipped.’”,
“‘He’s sitting on our client list inside a 6th Street hideout.’”,
“‘Get the shard. Don’t leave bodies if you can help it.’”,
“‘Payment: 2500 eddies. Bonus 1000 if nobody sees you.’”
], title=“GHOST DATA”)
idx = g.choose([
“Scout the building first”,
“Go in hard—clear every room”,
“Ask Jin to pull a floor map”
])
if idx == 0:
g.show_text([
“You case the building from a rooftop.”,
“Two guards on the door. One on the fire escape.”,
“Ciro’s office is second floor, north side.”,
“There’s a cargo entrance on the east—unguarded.”
])
return “gig_ghost_data_entry”
elif idx == 1:
g.show_text([
“No recon. You kick in the front door.”,
“Six Street thugs snap to attention.”,
“This is going to get loud.”
])
return “gig_ghost_data_loud”
else:
if “Jin” in g.crew:
g.show_text([
“Jin: ‘Give me thirty seconds.’”,
“‘East cargo door. Ciro’s terminal is networked.’”,
“‘I can loop the camera feed. You walk right in.’”
])
return “gig_ghost_data_entry”
else:
g.show_text([
“You don’t have Jin. No map.”,
“You’ll have to feel it out.”
])
return “gig_ghost_data_entry”

def scene_gig_ghost_data_entry(g):
g.show_text([
“GHOST DATA – ENTRY”,
“The cargo door is unlocked. Good start.”,
“Two guards doing a sweep. You wait for the gap.”,
“Then—Ciro’s voice echoes from upstairs.”,
“‘Someone’s in the building. Lock it down.’”
], title=“GHOST DATA”)
idx = g.choose([
“Ambush the guards before they organize”,
“Hide and wait (optical camo needed)”,
“Bluff—act like you belong here”
])
if idx == 0:
return “gig_ghost_data_ambush”
elif idx == 1:
if g.equipped_cyberware == “optical_camo” or g.has_item(“optical_camo”):
g.show_text([
“You vanish into the walls.”,
“Guards sweep past. Breathing. Waiting.”,
“You slip upstairs. Ciro’s alone at his terminal.”,
“You grab the shard. He doesn’t even flinch.”,
“Clean. Quiet.”
])
g.eddies += 3500  # base + stealth bonus
g.change_rep(“street”, 3)
g.show_text([“GHOST DATA COMPLETE”, “Stealth bonus: +3500 eddies.”])
return “afterlife_hub”
else:
g.show_text([“No optical camo. The guard clocks you immediately.”])
return “gig_ghost_data_ambush”
else:
# Bluff — skill check based on street_cred
bluff_ok = random.random() < 0.30 + g.street_cred * 0.08
if bluff_ok:
g.show_text([
“You walk past like you own the place.”,
“Guard: ‘Hey—’”,
“You: ‘Ciro called me in. Check your messages.’”,
“He checks. The moment’s enough.”,
“You’re upstairs and out before he figures it out.”
])
g.eddies += 2800
g.change_rep(“street”, 2)
g.show_text([“GHOST DATA COMPLETE”, “+2800 eddies. Slick.”])
return “afterlife_hub”
else:
g.show_text([
“Guard: ‘I don’t think so.’”,
“He reaches for his radio. You reach first.”
])
return “gig_ghost_data_ambush”

def scene_gig_ghost_data_ambush(g):
g.show_text([
“GHOST DATA – FIREFIGHT”,
“The hallway erupts. 6th Street guards pour in.”,
“You fight through to Ciro’s office.”,
“He’s barricaded himself inside.”
], title=“GHOST DATA”)
result = g.run_combat([
(“6th St Guard”,   32, 9,  10, 1),
(“6th St Guard”,   32, 9,  10, 1),
(“6th St Enforcer”,52, 13, 11, 3, [(“Suppressive”, 1.3)]),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 25)
g.show_text([
“You’re driven back. No shard.”,
“You escape with your life. Barely.”,
“Rook: ‘No pay for no data. Try again.’”
])
GIG_BOARD[“ghost_data”][“done”] = False   # allow retry
return “afterlife_hub”
return “gig_ghost_data_ciro”

def scene_gig_ghost_data_loud(g):
g.show_text([
“GHOST DATA – LOUD ENTRY”,
“Front door. Badge-check with a boot.”,
“Guards scramble. You put them down fast.”,
“Then three more from the stairwell.”
], title=“GHOST DATA”)
result = g.run_combat([
(“6th St Guard”,   32, 9,  10, 1),
(“6th St Guard”,   32, 9,  10, 1),
(“6th St Guard”,   32, 9,  10, 1),
(“6th St Veteran”, 60, 15, 12, 4, [(“Burst Fire”, 1.5)]),
])
if result == “hub”:
return “afterlife_hub”
if not result:
g.health = max(5, g.health - 30)
g.show_text([
“Too many. You retreat bleeding.”,
“Rook: ‘That’s why I said no bodies.’”
])
GIG_BOARD[“ghost_data”][“done”] = False
return “afterlife_hub”
return “gig_ghost_data_ciro”

def scene_gig_ghost_data_ciro(g):
g.show_text([
“GHOST DATA – CIRO”,
“Ciro is cowering behind his desk.”,
“‘Take it! Take the shard! Just don’t—’”,
“You grab the shard off the terminal.”,
“Ciro: ‘That list—there are people on it who will die.’”,
“‘Your fixer is selling names to Militech.’”,
“He shoves a second shard into your hand.”,
“‘This one proves it. Do what you want with it.’”
], title=“GHOST DATA”)
idx = g.choose([
“Take both shards—sell Ciro’s evidence to Militech”,
“Take the job shard—ignore Ciro’s warning”,
“Take Ciro’s evidence—expose Rook”
])
if idx == 0:
g.eddies += 2500
g.change_rep(“militech”, 2)
g.change_rep(“street”, -2)
g.set_flag(“sold_ciro_list”)
g.show_text([
“Militech pays you extra for the names.”,
“Rook’s list is theirs now.”,
“You try not to think about what happens to those people.”,
“+4500 eddies total. Dirty money.”
])
elif idx == 1:
g.eddies += 2500
g.show_text([
“You hand Rook the shard. He pays without looking up.”,
“Ciro’s second shard sits in your pocket.”,
“You toss it in a gutter.”,
“+2500 eddies.”
])
else:
g.eddies += 1000   # Rook’s partial pay before he knows
g.change_rep(“street”, 4)
g.set_flag(“exposed_rook”)
g.show_text([
“You leak Ciro’s evidence to a fixer network board.”,
“Rook’s operation collapses within the day.”,
“He goes quiet. The street remembers.”,
“+1000 eddies (partial) + Street Cred surge.”
])
g.show_text([“GIG COMPLETE: GHOST DATA”])
return “afterlife_hub”

# ── GIG 2: BLOOD MONEY ───────────────────────────────────────────────

# Yuki wants a Scav boss taken down. Multi-wave combat with a boss.

def scene_gig_blood_money(g):
GIG_BOARD[“blood_money”][“done”] = True
g.show_text([
“GIG: BLOOD MONEY”,
“Yuki: ‘Scav boss named Razor runs a chop-shop in Arroyo.’”,
“‘He’s been taking people off the street.’”,
“‘Dismantle them. Sell the chrome.’”,
“‘We want him gone. Payment: 3000 eddies.’”,
“‘If you bring back his databank: extra 1500.’”
], title=“BLOOD MONEY”)
idx = g.choose([
“Case the chop-shop first”,
“Go in—improvise”,
“Ask around for info on Razor”
])
if idx == 0:
g.show_text([
“You watch from an overpass.”,
“The chop-shop is a converted parking structure.”,
“Level 1: four Scavs. Level 2: Razor and his crew.”,
“There’s a side ramp on the west—less traffic.”,
“You spot a fuse box that could kill the lights.”
])
g.set_flag(“blood_cased”)
elif idx == 2:
g.show_text([
“Street vendor: ‘Razor? He’s mean. And paranoid.’”,
“‘He keeps his databank on him. Never lets it off.’”,
“‘You’d have to kill him to get it.’”,
“Useful. But you already knew that part.”
])
g.set_flag(“blood_intel”)
return “gig_blood_money_entry”

def scene_gig_blood_money_entry(g):
opts = [“Hit the lights—go in dark”, “Walk in the front—make a statement”]
if g.check_flag(“blood_cased”):
opts.insert(0, “Use the west ramp (cased route—fewer guards)”)
idx = g.choose(opts, title=“BLOOD MONEY”)
if idx == 0 and g.check_flag(“blood_cased”):
g.show_text([
“The west ramp is clear. You avoid the first cluster entirely.”,
“Straight to level two.”
])
return “gig_blood_money_boss”
elif “lights” in opts[idx]:
g.show_text([
“You cut the fuse box.”,
“The structure goes dark.”,
“Scavs shout. Torchlight swings wildly.”,
“You move through the chaos.”
])
result = g.run_combat([
(“Scav”,        28, 8, 9,  0),
(“Scav”,        28, 8, 9,  0),
])
if result == “hub”:  return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([“Overwhelmed in the dark. You pull back.”])
GIG_BOARD[“blood_money”][“done”] = False
return “afterlife_hub”
return “gig_blood_money_boss”
else:
g.show_text([
“You walk in the front.”,
“A Scav looks up from a body on the table.”,
“‘Who the f—’”,
“You don’t let him finish.”
])
result = g.run_combat([
(“Scav”,          28, 8, 9, 0),
(“Scav”,          28, 8, 9, 0),
(“Scav Butcher”,  45, 12, 10, 2, [(“Cleave”, 1.4)]),
(“Scav”,          28, 8,  9, 0),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 25)
g.show_text([“Too many. You fall back.”])
GIG_BOARD[“blood_money”][“done”] = False
return “afterlife_hub”
return “gig_blood_money_boss”

def scene_gig_blood_money_boss(g):
g.show_text([
“BLOOD MONEY – RAZOR”,
“Level two. The chop-shop’s inner sanctum.”,
“Razor: big, augmented, and very annoyed.”,
“‘You killed my people.’”,
“‘I’m going to take you apart. See what you’re worth.’”
], title=“BLOOD MONEY”)
result = g.run_combat([
{“name”: “Razor”,
“hp”: 130, “attack”: 22, “speed”: 12, “defense”: 7,
“abilities”: [(“Hydraulic Slam”, 2.0), (“Grab and Crush”, 1.6)],
“boss”: True,
“loot”: [“razor_databank”, “medkit”]},
(“Razor’s Guard”, 40, 11, 11, 2),
(“Razor’s Guard”, 40, 11, 11, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 35)
g.show_text([
“Razor nearly takes your head off.”,
“You escape. Barely. Missing a tooth.”,
“Yuki: ‘Come back when you’re ready.’”
])
GIG_BOARD[“blood_money”][“done”] = False
return “afterlife_hub”
# Victory
has_databank = g.has_item(“razor_databank”)
pay = 4500 if has_databank else 3000
g.eddies += pay
g.change_rep(“street”, 3)
if has_databank:
g.remove_item(“razor_databank”)
g.show_text([
“Razor’s down. You strip the databank off his wrist.”,
“Yuki: ‘Nice work. Real nice.’”,
f”+{pay} eddies. Bonus included.”
])
else:
g.show_text([
“Razor’s down.”,
f”Yuki pays: +{pay} eddies.”
])
g.show_text([“GIG COMPLETE: BLOOD MONEY”])
return “afterlife_hub”

# ── GIG 3: BROKEN DOC ────────────────────────────────────────────────

# Find ripperdoc Vik. Turns out Scavs took him to harvest his skills.

# Choice: rescue violently, negotiate a trade, or expose the Scav ring.

def scene_gig_broken_doc(g):
GIG_BOARD[“broken_doc”][“done”] = True
g.show_text([
“GIG: BROKEN DOC”,
“Rook: ‘Ripperdoc named Vik went missing two nights ago.’”,
“‘He fixes up mercs who can’t go to corpo-owned clinics.’”,
“‘Half the street operatives in Watson use him.’”,
“‘Find him. Bring him back breathing.’”,
“‘Pay: 2000 eddies. Plus—he’ll owe you a favor.’”
], title=“BROKEN DOC”)
idx = g.choose([
“Check Vik’s clinic for clues”,
“Ask around the Watson streets”,
“Pull Scav activity reports (cyberdeck)”
])
if idx == 0:
g.show_text([
“Vik’s clinic. Broken glass. Overturned table.”,
“No signs of a struggle at the door—he let them in.”,
“On the floor: a 6th Street patch. Wrong. Too obvious.”,
“On his terminal: last client appointment.”,
“A name: ‘Chrome Kaz’—known Scav fixer.”
])
g.set_flag(“vik_trail_chrome_kaz”)
elif idx == 1:
g.show_text([
“Street vendor: ‘Heard shouting from Vik’s block.’”,
“‘Three guys. One of them had chrome arms to the shoulder.’”,
“‘They went east. Towards the old parking structure.’”
])
g.set_flag(“vik_trail_witness”)
elif idx == 2:
if g.has_item(“cyberdeck”):
g.energy = max(0, g.energy - 20)
g.show_text([
“Jin: ‘Scav network is noisy tonight.’”,
“‘They’re selling something. Medical expertise.’”,
“‘They’ve got Vik in a warehouse on Industrial Row.’”,
“‘Three guards outside. Unknown inside.’”
])
g.set_flag(“vik_trail_net”)
else:
g.show_text([“No cyberdeck. You check the streets instead.”])
g.set_flag(“vik_trail_witness”)
return “gig_broken_doc_warehouse”

def scene_gig_broken_doc_warehouse(g):
g.show_text([
“BROKEN DOC – WAREHOUSE”,
“Industrial Row. You find the warehouse.”,
“Vik’s inside—you can hear him.”,
“‘I won’t install that. You can’t make me.’”,
“Scav: ‘We don’t need your permission. Just your hands.’”
], title=“BROKEN DOC”)
has_intel = (g.check_flag(“vik_trail_net”) or
g.check_flag(“vik_trail_chrome_kaz”))
idx = g.choose([
“Breach the front—hit hard and fast”,
“Sneak around back (optical camo needed)” if g.equipped_cyberware == “optical_camo” or g.has_item(“optical_camo”) else “Try the back door (risky without camo)”,
“Call out to negotiate—offer something”
])
if idx == 0:
g.show_text([
“You kick the door.”,
“Three Scavs spin around.”,
“Inside: Vik strapped to a gurney. Conscious. Angry.”,
])
result = g.run_combat([
(“Scav”,         28, 8,  9, 0),
(“Scav”,         28, 8,  9, 0),
(“Scav Surgeon”, 45, 11, 10, 2, [(“Blade Flurry”, 1.3)]),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“You’re driven out. Vik is still in there.”,
“You need to try again.”
])
GIG_BOARD[“broken_doc”][“done”] = False
return “afterlife_hub”
return “gig_broken_doc_rescued”
elif idx == 1:
if g.equipped_cyberware == “optical_camo” or g.has_item(“optical_camo”):
g.show_text([
“You ghost through the back.”,
“Two Scavs standing over Vik.”,
“You take the first one from behind. The second spins—”,
“too slow.”
])
result = g.run_combat([
(“Scav”, 28, 8, 9, 0),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 15)
GIG_BOARD[“broken_doc”][“done”] = False
return “afterlife_hub”
return “gig_broken_doc_rescued”
else:
g.show_text([
“The back door squeals. A Scav hears it.”,
“‘Hey!’ Full alert.”
])
result = g.run_combat([
(“Scav”,         28, 8, 9, 0),
(“Scav”,         28, 8, 9, 0),
(“Scav Surgeon”, 45, 11, 10, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
GIG_BOARD[“broken_doc”][“done”] = False
return “afterlife_hub”
return “gig_broken_doc_rescued”
else:  # negotiate
g.show_text([
“You bang on the door.”,
“‘I’ve got chrome worth more than whatever you’re planning.’”,
“‘Let the doc go. We trade.’”
])
# success depends on having something to offer
has_trade = (g.eddies >= 1000 or
any(g.has_item(x) for x in [“smart_rifle”,“optical_camo”,“cyberdeck”]))
if has_trade:
idx2 = g.choose([
f”Offer 1000 eddies {’(you have it)’ if g.eddies >= 1000 else ‘(short)’}”,
“Offer a piece of equipment”,
“This was a bluff—attack when they open”
])
if idx2 == 0 and g.eddies >= 1000:
g.eddies -= 1000
g.show_text([
“The door opens. You slide the chip through.”,
“Scav: ‘Take your doc.’”,
“Vik stumbles out. ‘Never doing a house call again.’”
])
return “gig_broken_doc_rescued”
elif idx2 == 1:
trade_items = [i for i in [“smart_rifle”,“optical_camo”,“cyberdeck”] if g.has_item(i)]
if trade_items:
ti = g.choose(trade_items + [“Never mind”], “Trade which?”)
if ti < len(trade_items):
g.remove_item(trade_items[ti])
g.show_text([
f”You slide the {trade_items[ti]} under the door.”,
“Scav: ‘Deal.’”,
“Vik walks out rubbing his wrists.”
])
return “gig_broken_doc_rescued”
g.show_text([“Nothing to trade. You’ll have to fight.”])
return “gig_broken_doc_warehouse”
else:  # bluff attack
g.show_text([“The door cracks. You slam through it.”])
result = g.run_combat([
(“Scav”, 28, 8, 9, 0),
(“Scav Surgeon”, 45, 11, 10, 2),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
GIG_BOARD[“broken_doc”][“done”] = False
return “afterlife_hub”
return “gig_broken_doc_rescued”
else:
g.show_text([
“Scav: ‘You got nothing. Get lost.’”,
“The bluff failed. You’ll have to fight.”
])
return “gig_broken_doc_warehouse”

def scene_gig_broken_doc_rescued(g):
g.show_text([
“BROKEN DOC – VIK”,
“Vik catches his breath outside.”,
“‘That was… close.’”,
“‘They wanted me to install military-grade implants.’”,
“‘Without consent. Into people who can’t say no.’”,
“He looks at his hands.”,
“‘I owe you. Come to my clinic anytime.’”
], title=“BROKEN DOC”)
idx = g.choose([
“Collect the 2000 from Rook”,
“Waive Rook’s fee—Vik’s favor is worth more”,
“Ask Vik to upgrade you right now”
])
if idx == 0:
g.eddies += 2000
g.show_text([“Rook pays. 2000 eddies.”, “GIG COMPLETE: BROKEN DOC”])
elif idx == 1:
g.set_flag(“vik_owes_favor”)
g.change_rep(“street”, 3)
g.show_text([
“Rook: ‘You sure?’”,
“You: ‘Pay it forward.’”,
“Vik: ‘I won’t forget this, Niko.’”,
“GIG COMPLETE: BROKEN DOC”
])
else:
g.show_text([
“Vik: ‘Right now? On the sidewalk?’”,
“He pulls a kit from his coat.”,
“‘Fine. Hold still.’”
])
# Free upgrade
upgrade = random.choice([
(“Reflex boost: +2 speed in combat.”, “speed_up”),
(“Pain dampener: you heal 5 HP/turn in combat.”, “regen”),
(“Micro-optics: crit chance +5%.”, “crit_up”),
])
g.show_text([upgrade[0]])
g.set_flag(f”vik_upgrade_{upgrade[1]}”)
g.eddies += 2000
g.show_text([“Rook pays. 2000 eddies.”, “GIG COMPLETE: BROKEN DOC”])
return “afterlife_hub”

# ── GIG 4: STEEL NERVES ──────────────────────────────────────────────

# Corpo exec Yama needs protection at a meeting. The meeting is a trap.

def scene_gig_steel_nerves(g):
GIG_BOARD[“steel_nerves”][“done”] = True
g.show_text([
“GIG: STEEL NERVES”,
“Yuki: ‘Corpo exec named Yama has a meeting tonight.’”,
“‘He says it’s a simple deal—tech license handoff.’”,
“‘He says he doesn’t need protection.’”,
“‘He’s wrong. He just doesn’t know it yet.’”,
“‘Guard him. Don’t let him die. 3500 eddies.’”
], title=“STEEL NERVES”)
idx = g.choose([
“Meet Yama and escort him”,
“Recon the meeting location first”,
“Hack the guest list (cyberdeck)”
])
if idx == 0:
return “gig_steel_nerves_escort”
elif idx == 1:
g.show_text([
“You find the meeting spot—a private booth at the Riot Club.”,
“Exit routes: two. Main entrance and a kitchen service door.”,
“You spot a suspicious figure doing a sweep.”,
“Pro movement. This isn’t a business meeting.”
])
g.set_flag(“steel_nerves_cased”)
return “gig_steel_nerves_escort”
else:
if g.has_item(“cyberdeck”):
g.energy = max(0, g.energy - 20)
g.show_text([
“Jin: ‘Guest list is fake.’”,
“‘There is no tech license.’”,
“‘The other side of the table is an Arasaka extraction team.’”,
“‘They want Yama alive. His bodyguards—not so much.’”
])
g.set_flag(“steel_nerves_intel”)
g.set_flag(“steel_nerves_cased”)
else:
g.show_text([“No cyberdeck. You go in blind.”])
return “gig_steel_nerves_escort”

def scene_gig_steel_nerves_escort(g):
g.show_text([
“STEEL NERVES – THE MEETING”,
“Yama: ‘You’re my guard? You look underfed.’”,
“‘This is a business meeting, not a warzone.’”,
“The Riot Club. Loud music. Neon.”,
“Yama sits. The other side of the table sits down.”,
“Too calm. Too ready.”,
“Then the lights cut out.”
], title=“STEEL NERVES”)
if g.check_flag(“steel_nerves_intel”):
g.show_text([
“You already knew. You’re already moving.”,
“‘Yama—kitchen. NOW.’”,
“He moves. For a corpo, he’s fast.”
])
return “gig_steel_nerves_fight”
else:
idx = g.choose([
“Grab Yama—pull him toward the exit”,
“Draw your weapon—challenge them directly”,
“Stay calm—see what they want”
])
if idx == 0:
g.show_text([“You yank Yama up. ‘Move!’”, “He protests. You don’t listen.”])
elif idx == 1:
g.show_text([
“You stand. ‘Whatever you’re planning—don’t.’”,
“Arasaka agent: ‘We’re not planning. We’re executing.’”
])
else:
g.show_text([
“You sit. Watch.”,
“Arasaka agent smiles. Reaches under the table.”,
“Yep. That’s a weapon.”
])
return “gig_steel_nerves_fight”

def scene_gig_steel_nerves_fight(g):
g.show_text([
“STEEL NERVES – AMBUSH”,
“Four Arasaka extraction agents.”,
“Yama is pressed against the wall behind you.”,
“‘I thought this was a BUSINESS MEETING!’”,
“You: ‘Keep your head down.’”
], title=“STEEL NERVES”)
result = g.run_combat([
(“Arasaka Agent”,  45, 12, 13, 2),
(“Arasaka Agent”,  45, 12, 13, 2),
(“Arasaka Agent”,  45, 12, 13, 2),
{“name”: “Agent Lead”, “hp”: 80, “attack”: 18, “speed”: 15, “defense”: 5,
“abilities”: [(“Flashbang”, 0.8), (“Suppressive”, 1.3)],
“loot”: [“arasaka_keycard”]},
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 30)
g.show_text([
“You’re overwhelmed. Yama is taken.”,
“Yuki: ‘He’s gone. No pay. Don’t come back for a while.’”
])
g.change_rep(“street”, -1)
GIG_BOARD[“steel_nerves”][“done”] = False
return “afterlife_hub”
g.show_text([
“Last agent down.”,
“Yama is shaking. ‘You—you saved my life.’”,
“‘I didn’t even pay you yet.’”,
“He writes you a number. Bigger than expected.”
])
g.eddies += 5000   # combat bonus
g.change_rep(“street”, 3)
if g.has_item(“arasaka_keycard”):
g.show_text([
“You pocket the keycard off the lead agent.”,
“Might be useful later.”
])
g.show_text([“GIG COMPLETE: STEEL NERVES”, “+5000 eddies”])
return “afterlife_hub”

# ── GIG 5: DEAD DROP ─────────────────────────────────────────────────

# A simple courier job that turns into a gang war intervention.

def scene_gig_dead_drop(g):
GIG_BOARD[“dead_drop”][“done”] = True
g.show_text([
“GIG: DEAD DROP”,
“Rook: ‘Simple job. Courier work.’”,
“‘Pick up a package from Wes in Kabuki.’”,
“‘Drop it at the Maelstrom garage in Watson.’”,
“‘Don’t open it. Don’t ask what’s in it.’”,
“‘1000 eddies. Clean work.’”
], title=“DEAD DROP”)
idx = g.choose([
“Accept—pick up from Wes”,
“Ask Rook what’s inside”,
“Scan the package when you get it”
])
if idx == 1:
g.show_text([
“Rook: ‘You’re not paid to ask questions.’”,
“He stares at you until you stop asking.”
])
return “gig_dead_drop_pickup”

def scene_gig_dead_drop_pickup(g):
g.show_text([
“DEAD DROP – PICKUP”,
“Wes is in a Kabuki noodle shop.”,
“He hands you a sealed case. Heavy.”,
“‘Careful with it. Real careful.’”
], title=“DEAD DROP”)
idx = g.choose([
“Take it and go”,
“Scan it (cyberdeck)”,
“Break the seal—look inside”
])
if idx == 0:
g.show_text([“Package secured. You head to Watson.”])
return “gig_dead_drop_delivery”
elif idx == 1:
if g.has_item(“cyberdeck”):
g.show_text([
“Jin: ‘Scanning…’”,
“‘It’s a Militech signal jammer.’”,
“‘Military grade. The Maelstrom would use this’”,
“‘to black out a whole district.’”
])
g.set_flag(“deadrop_know_contents”)
else:
g.show_text([“No cyberdeck. You head to Watson.”])
return “gig_dead_drop_delivery”
else:
g.show_text([
“You crack the seal.”,
“Inside: a Militech signal jammer.”,
“And a detonator.”,
“This isn’t a package. It’s a weapon.”
])
g.set_flag(“deadrop_opened”)
g.set_flag(“deadrop_know_contents”)
return “gig_dead_drop_choice”

def scene_gig_dead_drop_delivery(g):
g.show_text([
“DEAD DROP – WATSON”,
“Maelstrom territory.”,
“Three members at the door of the garage.”,
“One of them opens the case.”,
“His eyes go wide.”,
“‘This is it. The jammer.’”,
“‘Boys—it’s happening. Tonight we black out Militech’s grid.’”,
“You realize what you’ve just handed them.”
], title=“DEAD DROP”)
if g.check_flag(“deadrop_know_contents”):
idx = g.choose([
“Leave—you did the job, you got paid”,
“Destroy the jammer—cost yourself the pay”,
“Offer to help Maelstrom use it”
])
else:
idx = g.choose([
“Leave—you did the job”,
“Ask what they’re planning”,
“Grab the package back”
])
if idx == 0:
g.eddies += 1000
g.show_text([
“You walk away. Rook pays.”,
“The next morning: district-wide blackout in Watson.”,
“Eight people die in the chaos.”,
“+1000 eddies. It sits heavy.”
])
g.change_rep(“militech”, -1)
elif idx == 1 or (idx == 2 and not g.check_flag(“deadrop_know_contents”)):
g.show_text([
“You grab the case.”,
“Maelstrom: ‘Hey!’”,
“You smash it on the ground. The components scatter.”,
])
result = g.run_combat([
(“Maelstrom”,  35, 10, 10, 1),
(“Maelstrom”,  35, 10, 10, 1),
])
if result == “hub”: return “afterlife_hub”
if not result:
g.health = max(5, g.health - 20)
g.show_text([
“They beat you back. The jammer’s still intact.”,
“Rook: ‘You destroyed the package AND you didn’t deliver it?’”,
“‘No pay. And stay away from me.’”
])
g.change_rep(“street”, -1)
GIG_BOARD[“dead_drop”][“done”] = False
return “afterlife_hub”
g.show_text([
“The jammer is destroyed. Maelstrom is furious.”,
“Rook is furious. You don’t get paid.”,
“But Watson has power tonight.”,
])
g.change_rep(“street”, 2)
g.change_rep(“militech”, 1)
else:
g.show_text([
“You offer to help. Maelstrom likes that.”,
“‘You got nerve, choom.’”,
“The blackout goes off. Militech scrambles.”,
“Maelstrom pays you 1500 extra.”,
“Rook never speaks to you again.”
])
g.eddies += 2500
g.change_rep(“street”, 2)
g.change_rep(“militech”, -3)
g.set_flag(“maelstrom_contact”)
return “gig_dead_drop_done”

def scene_gig_dead_drop_choice(g):
g.show_text([
“DEAD DROP – YOU KNOW”,
“You’re holding a weapon designed for a blackout attack.”,
“Rook set this up. Maelstrom is the buyer.”,
“What do you do?”
], title=“DEAD DROP”)
idx = g.choose([
“Deliver it anyway—it’s not your business”,
“Take it to Militech—they’ll pay”,
“Destroy it here—take the loss”,
“Confront Rook directly”
])
if idx == 0:
return “gig_dead_drop_delivery”
elif idx == 1:
g.show_text([
“Militech pays you 2500 for the intel.”,
“They dismantle the jammer.”,
“Rook goes underground for a month.”,
“+2500 eddies.”
])
g.eddies += 2500
g.change_rep(“militech”, 2)
g.change_rep(“street”, -2)
elif idx == 2:
g.show_text([
“You drop it on the floor and put your boot through it.”,
“No pay. But no blood on your hands.”
])
g.change_rep(“street”, 1)
else:
g.show_text([
“You call Rook.”,
“He doesn’t answer.”,
“You show up at his table.”,
“He: ‘You opened it. I told you not to open it.’”,
“You: ‘What is this, Rook?’”,
“‘It’s business. Deliver it or walk.’”,
])
idx2 = g.choose([“Deliver it (return to normal flow)”,“Walk—destroy it here”])
if idx2 == 0:
return “gig_dead_drop_delivery”
else:
g.show_text([
“You smash the case on his table.”,
“Rook looks at you for a long moment.”,
“‘Get out of my bar.’”,
“You do.”
])
g.change_rep(“street”, 2)
g.set_flag(“rook_burned”)
g.show_text([“GIG COMPLETE: DEAD DROP”])
return “afterlife_hub”

def scene_gig_dead_drop_done(g):
g.show_text([“GIG COMPLETE: DEAD DROP”])
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
# ── Menus ──────────────────────────────────────────────────────
“start_menu”:               scene_start_menu,
# ── Prologue & Act 1 ───────────────────────────────────────────
“prologue”:                 scene_prologue,
“afterlife_intro”:          scene_afterlife_intro,
“heist_plan”:               scene_heist_plan,
“heist_solo_warning”:       scene_heist_solo_warning,
“heist_crew_hunt”:          scene_heist_crew_hunt,
“heist_alone”:              scene_heist_alone,
“heist_solo_direct”:        scene_heist_solo_direct,
“heist_solo_guards”:        scene_heist_solo_guards,
“heist_solo_chip”:          scene_heist_solo_chip,
“heist_solo_exit”:          scene_heist_solo_exit,
“heist_combat”:             scene_heist_combat,
“heist_crew_strike”:        scene_heist_crew_strike,
“heist_crew_execute”:       scene_heist_crew_execute,
“heist_crew_chip”:          scene_heist_crew_chip,
“heist_crew_exit”:          scene_heist_crew_exit,
“after_heist”:              scene_after_heist,
# ── Act 2 ──────────────────────────────────────────────────────
“act2_vector_lead”:         scene_act2_vector_lead,
“act2_no_vector”:           scene_act2_no_vector,
“hiro_direct”:              scene_hiro_direct,
“hiro_platform”:            scene_hiro_platform,
“hiro_intercept”:           scene_hiro_intercept,
“hiro_subdued”:             scene_hiro_subdued,
“hiro_talks”:               scene_hiro_talks,
“hiro_outcome”:             scene_hiro_outcome,
# ── Lucy ───────────────────────────────────────────────────────
“lucy_pacifica”:            scene_lucy_pacifica,
“lucy_the_plan”:            scene_lucy_the_plan,
# ── Act 3 ──────────────────────────────────────────────────────
“act3_biokey”:              scene_act3_biokey,
“tanaka_research”:          scene_tanaka_research,
“tanaka_contact”:           scene_tanaka_contact,
“tanaka_meeting”:           scene_tanaka_meeting,
“tanaka_gives_key”:         scene_tanaka_gives_key,
“tanaka_stealth”:           scene_tanaka_stealth,
“tanaka_assault”:           scene_tanaka_assault,
# ── Act 4 ──────────────────────────────────────────────────────
“act4_vector_moves”:        scene_act4_vector_moves,
“act4_sellout_path”:        scene_act4_sellout_path,
“act4_prep_window”:         scene_act4_prep_window,
“act4_fight_out”:           scene_act4_fight_out,
“act4_push_now”:            scene_act4_push_now,
# ── Tower ──────────────────────────────────────────────────────
“arasaka_tower”:            scene_arasaka_tower,
“tower_lobby”:              scene_tower_lobby,
“tower_lobby_fight”:        scene_tower_lobby_fight,
“tower_descent”:            scene_tower_descent,
“tower_shaft”:              scene_tower_shaft,
“tower_hack_grid”:          scene_tower_hack_grid,
“tower_sublevel”:           scene_tower_sublevel,
“tower_boss”:               scene_tower_boss,
“tower_ending”:             scene_tower_ending,
# ── Act 5 ──────────────────────────────────────────────────────
“act5_blackwall”:           scene_act5_blackwall,
“pre_blackwall_prep”:       scene_pre_blackwall_prep,
“crew_final_talk”:          scene_crew_final_talk,
“blackwall_dive”:           scene_blackwall_dive,
“blackwall_combat”:         scene_blackwall_combat,
“blackwall_through”:        scene_blackwall_through,
# ── Act 6-10 ───────────────────────────────────────────────────
“mikoshi_approach”:         scene_mikoshi_approach,
“mikoshi_guardian”:         scene_mikoshi_guardian,
“mikoshi_core”:             scene_mikoshi_core,
“final_choice”:             scene_final_choice,
# ── Endings ────────────────────────────────────────────────────
“ending_legend”:            scene_ending_legend,
“ending_sellout”:           scene_ending_sellout,
“ending_purge”:             scene_ending_purge,
“ending_merge”:             scene_ending_merge,
# ── Hub + streets ──────────────────────────────────────────────
“afterlife_hub”:            scene_afterlife_hub,
“street”:                   scene_street,
“watson_district”:          scene_watson_district,
“combat_zone”:              scene_combat_zone,
“maya_recruit”:             scene_maya_recruit,
“kabuki”:                   scene_kabuki,
“kabuki_cyberware”:         scene_kabuki_cyberware,
“vendor_netrunner”:         scene_vendor_netrunner,
# ── Fixer gigs ─────────────────────────────────────────────────
“fixer_gigs”:               scene_fixer_gigs,
“gig_ghost_data”:           scene_gig_ghost_data,
“gig_ghost_data_entry”:     scene_gig_ghost_data_entry,
“gig_ghost_data_ambush”:    scene_gig_ghost_data_ambush,
“gig_ghost_data_loud”:      scene_gig_ghost_data_loud,
“gig_ghost_data_ciro”:      scene_gig_ghost_data_ciro,
“gig_blood_money”:          scene_gig_blood_money,
“gig_blood_money_entry”:    scene_gig_blood_money_entry,
“gig_blood_money_boss”:     scene_gig_blood_money_boss,
“gig_broken_doc”:           scene_gig_broken_doc,
“gig_broken_doc_warehouse”: scene_gig_broken_doc_warehouse,
“gig_broken_doc_rescued”:   scene_gig_broken_doc_rescued,
“gig_steel_nerves”:         scene_gig_steel_nerves,
“gig_steel_nerves_escort”:  scene_gig_steel_nerves_escort,
“gig_steel_nerves_fight”:   scene_gig_steel_nerves_fight,
“gig_dead_drop”:            scene_gig_dead_drop,
“gig_dead_drop_pickup”:     scene_gig_dead_drop_pickup,
“gig_dead_drop_delivery”:   scene_gig_dead_drop_delivery,
“gig_dead_drop_choice”:     scene_gig_dead_drop_choice,
“gig_dead_drop_done”:       scene_gig_dead_drop_done,
# ── Services ───────────────────────────────────────────────────
“bartender”:                scene_bartender,
“shop”:                     scene_shop,
“shop_heist”:               scene_shop,
“crew_hub”:                 scene_crew_hub,
“talk_maya”:                scene_talk_maya,
“talk_jin”:                 scene_talk_jin,
“talk_lina”:                scene_talk_lina,
“pacifica_side”:            scene_pacifica_side,
“voodoo_side”:              scene_voodoo_side,
“pacifica_ruins”:           scene_pacifica_ruins,
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
