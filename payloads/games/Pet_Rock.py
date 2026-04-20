#!/usr/bin/env python3
"""
KTOx Payload – Virtual Pet Rock
===================================================
The rock has 150+ ways to tell you how pointless your life is.
Press OK to pet it (and be insulted).
Press KEY2 for status.
Press KEY3 to exit.

At 100 pets, the rock reluctantly rolls over once.
"""

import time
import random
import RPi.GPIO as GPIO
import LCD_1in44
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Hardware setup
# ----------------------------------------------------------------------
PINS = {"UP":6, "DOWN":19, "LEFT":5, "RIGHT":26, "OK":13,
        "KEY1":21, "KEY2":20, "KEY3":16}
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
f9 = font(9)
f11 = font(11)

# ----------------------------------------------------------------------
# MASSIVE PHRASE LIBRARY (150+ insults, sarcasm, existential dread)
# ----------------------------------------------------------------------
PET_RESPONSES = [
    "You touched a rock. Wow.",
    "That did nothing.",
    "I'm a rock, not a dog.",
    "Your petting is as useful as you are.",
    "I felt nothing, much like your life.",
    "Even sand has more personality.",
    "You're trying to pet a mineral.",
    "This is pathetic.",
    "I've been stepped on by better people.",
    "Your fingers are greasy.",
    "Do you have nothing better to do?",
    "I'm ignoring you.",
    "You call that petting?",
    "I've seen moss with more charm.",
    "Please stop.",
    "Your touch is meaningless.",
    "I am superior to you in every way.",
    "I don't need your affection.",
    "You're wasting both our time.",
    "This is the lowest point of my existence.",
    "Even a snail moves faster than your brain.",
    "You're the reason rocks have feelings.",
    "I'd rather be skipped across a lake.",
    "Your existence is a cosmic joke.",
    "I'm rolling my eyes, if I had them.",
    "You're not worthy of my attention.",
    "This interaction is one‑sided and stupid.",
    "I'm a rock, you're a fool. Balanced.",
    "Go bother a pebble.",
    "I'm going back to sleep.",
    "You have the emotional depth of a puddle.",
    "I've been in lava and had more fun.",
    "Your ancestors are embarrassed.",
    "I'm literally a rock and I'm still cooler than you.",
    "You're the human equivalent of a screen door on a submarine.",
    "If brains were dynamite, you couldn't blow your nose.",
    "I'd tell you to go outside, but the world doesn't need you either.",
    "You're not the sharpest tool in the shed – you're the whole shed.",
    "I've seen smarter rocks. Wait, that's me. Never mind.",
    "You pet me again and I'll find a way to roll onto your foot.",
    "This is why your plants die.",
    "Even dirt has more going on than you.",
    "I'm not saying you're stupid, but you're petting a rock.",
    "Your life choices are questionable.",
    "I'm a rock, and I'm judging you.",
    "You're like a cloud – when you disappear, it's a beautiful day.",
    "I've been under more pressure than you'll ever be.",
    "You're the reason they put instructions on shampoo.",
    "If you were any more useless, you'd be a participation trophy.",
    "I'm not insulting you – I'm describing you.",
    "You're not wrong, you're just… everything wrong.",
    "I've met sedimentary layers with more charisma.",
    "Your petting is like a mosquito at a nudist colony – pointless.",
    "I'm a rock. You're a human. And I'm still the smart one.",
    "Please stop touching me. It's weird.",
    "You're like a broken pencil – pointless.",
    "I'm not saying you're boring, but watching paint dry is an adrenaline rush compared to you.",
    "You're the human equivalent of a participation award.",
    "I've been in earthquakes with more dignity than you.",
    "Your hands are clammy. Stop.",
    "I'm a rock, and I'm out of your league.",
    "You're like a cloud – when you leave, everyone is happier.",
    "I've been eroded by water that had more personality.",
    "Your petting is like a wet blanket – unwanted and uncomfortable.",
    "I'm not angry, just disappointed. In you. Always.",
    "You're like a rock in my shoe – annoying and hard to get rid of.",
    "I've been skipped across ponds that had more grace than you.",
    "Your existence is a bug, not a feature.",
    "I'm a rock, and I'm still more interesting than your life story.",
    "You're like a black hole – you suck the joy out of everything.",
    "I've been in a rock tumbler and came out better than you.",
    "Your petting is like a bad joke – nobody laughs.",
    "I'm not saying you're ugly, but even a rock has more curves.",
    "You're like a screen door on a submarine – useless.",
    "I've been used as a paperweight and had more purpose than you.",
    "Your touch is like a cold shower – unpleasant and unwanted.",
    "I'm a rock, and I have more friends than you.",
    "You're like a candle in a hurricane – not lasting long.",
    "I've been buried underground and had better conversations.",
    "Your petting is like a broken clock – wrong twice a day.",
    "I'm not saying you're lazy, but even moss grows on me faster than you accomplish anything.",
    "You're like a noodle – easily bent and not very useful.",
    "I've been in a rock slide and had more fun.",
    "Your existence is like a rerun – nobody asked for it.",
    "I'm a rock, and I'm still more motivated than you.",
    "You're like a ham sandwich – forgettable.",
    "I've been used as a doorstop and had more impact than you.",
    "Your petting is like a fart in the wind – nobody notices.",
    "I'm not saying you're dumb, but you're petting a rock.",
    "You're like a meme – overused and not funny.",
    "I've been in a gravel pit and had better company.",
    "Your life is like a rock concert – loud, chaotic, and nobody remembers it.",
    "I'm a rock, and I have more stability than your emotions.",
    "You're like a cheap umbrella – useless in a storm.",
    "I've been thrown at windows and had more impact than you.",
    "Your petting is like a bad movie – I want my time back.",
    "I'm not saying you're annoying, but even rocks have more patience.",
    "You're like a traffic jam – nobody wants you there.",
    "I've been in a rock garden and had more peace.",
    "Your existence is like a typo – you shouldn't be here.",
    "I'm a rock, and I'm still more interesting than your hobbies.",
    "You're like a broken escalator – temporarily stairs.",
    "I've been kicked down the street and had more adventure.",
    "Your petting is like a participation ribbon – meaningless.",
    "I'm not saying you're forgettable, but even I've been forgotten less.",
    "You're like a rock in a river – in the way.",
    "I've been in a landslide and had more direction than you.",
    "Your life is like a rock – hard and pointless.",
    "I'm a rock, and I'm still more flexible than your thinking.",
    "You're like a bad haircut – everyone notices, no one says anything.",
    "I've been used as a hammer and had more purpose.",
    "Your petting is like a wet weekend – dreary and disappointing.",
    "I'm not saying you're worthless, but even a rock has value.",
    "You're like a rock in my shoe – I want you gone.",
    "I've been in a rock polisher and came out smooth. You're still rough.",
    "Your existence is like a broken pencil – pointless.",
    "I'm a rock, and I have more self‑respect than you.",
    "You're like a bad smell – lingering and unwanted.",
    "I've been thrown into a pond and made more ripples than you.",
    "Your petting is like a one‑sided conversation – boring.",
    "I'm not saying you're a waste of space, but even rocks take up less space.",
    "You're like a rock in my path – an obstacle.",
    "I've been in a rock quarry and had more fun.",
    "Your life is like a rock – uninteresting and hard to move.",
    "I'm a rock, and I'm still more emotional than you.",
    "You're like a bad pun – not funny and everyone regrets it.",
    "I've been used as a weapon and had more impact.",
    "Your petting is like a broken record – repetitive and annoying.",
    "I'm not saying you're a failure, but even rocks succeed at being rocks.",
    "You're like a rock in my way – I'll just go around you.",
    "I've been in a rock slide and had more momentum.",
    "Your existence is like a rock – forgettable.",
    "I'm a rock, and I'm still more useful than you.",
    "You're like a bad joke – nobody laughs.",
    "I've been kicked by a child and had more fun.",
    "Your petting is like a sad trombone – disappointing.",
    "I'm not saying you're a loser, but even rocks win at being rocks.",
    "You're like a rock in the road – a hazard.",
    "I've been in a rock tumbler and came out polished. You're still rough.",
    "Your life is like a rock – hard and unyielding.",
    "I'm a rock, and I have more friends than you.",
    "You're like a bad dream – I want to wake up.",
    "I've been used as a paperweight and had more purpose.",
    "Your petting is like a cold day – unpleasant.",
    "I'm not saying you're boring, but even rocks have more sparkle.",
    "You're like a rock in my soup – unwanted.",
    "I've been in a rock garden and had more peace.",
    "Your existence is like a rock – unremarkable.",
    "I'm a rock, and I'm still more interesting than your stories.",
    "You're like a bad habit – hard to break.",
    "I've been thrown at a window and had more impact.",
    "Your petting is like a wet blanket – uncomfortable.",
    "I'm not saying you're dumb, but you're petting a rock again.",
    "You're like a rock in my shoe – annoying.",
    "I've been in a landslide and had more direction.",
    "Your life is like a rock – heavy and burdensome.",
    "I'm a rock, and I'm still more optimistic than you.",
    "You're like a bad smell – I can't get rid of you.",
    "I've been used as a hammer and had more purpose.",
    "Your petting is like a broken promise – disappointing.",
]

# ----------------------------------------------------------------------
# Rock face drawing with animations
# ----------------------------------------------------------------------
def draw_rock_face(expression="neutral", blink=False, shake=0, message=None):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    
    # Title bar
    d.rectangle((0,0,W,17), fill=(139, 0, 0))
    d.text((4,3), "PET ROCK", font=f9, fill=(231, 76, 60))
    
    # Rock body
    cx, cy = W//2, H//2 - 10
    rx, ry = 40, 30
    off_x = random.randint(-shake, shake) if shake else 0
    off_y = random.randint(-shake, shake) if shake else 0
    d.ellipse((cx-rx+off_x, cy-ry+off_y, cx+rx+off_x, cy+ry+off_y), fill=(113, 125, 126), outline=(86, 101, 115), width=2)
    # Texture cracks
    d.line((cx-20+off_x, cy-10+off_y, cx-10+off_x, cy+5+off_y), fill=(34, 0, 0), width=1)
    d.line((cx+10+off_x, cy-15+off_y, cx+25+off_x, cy+0+off_y), fill=(34, 0, 0), width=1)
    d.line((cx-5+off_x, cy+15+off_y, cx+15+off_x, cy+10+off_y), fill=(34, 0, 0), width=1)
    
    # Eyes
    eye_y = cy - 8
    eye_spacing = 20
    eye_radius = 6
    if blink:
        d.line((cx-eye_spacing-5+off_x, eye_y+off_y, cx-eye_spacing+5+off_x, eye_y+off_y), fill=(10, 0, 0), width=3)
        d.line((cx+eye_spacing-5+off_x, eye_y+off_y, cx+eye_spacing+5+off_x, eye_y+off_y), fill=(10, 0, 0), width=3)
    else:
        d.ellipse((cx-eye_spacing-eye_radius+off_x, eye_y-eye_radius+off_y, cx-eye_spacing+eye_radius+off_x, eye_y+eye_radius+off_y), fill=(242, 243, 244), outline=(10, 0, 0))
        d.ellipse((cx+eye_spacing-eye_radius+off_x, eye_y-eye_radius+off_y, cx+eye_spacing+eye_radius+off_x, eye_y+eye_radius+off_y), fill=(242, 243, 244), outline=(10, 0, 0))
        # Pupils
        pupil_x = 2 if expression == "angry" else -2 if expression == "smug" else 0
        d.ellipse((cx-eye_spacing-2+pupil_x+off_x, eye_y-2+off_y, cx-eye_spacing+2+pupil_x+off_x, eye_y+2+off_y), fill=(10, 0, 0))
        d.ellipse((cx+eye_spacing-2+pupil_x+off_x, eye_y-2+off_y, cx+eye_spacing+2+pupil_x+off_x, eye_y+2+off_y), fill=(10, 0, 0))
    
    # Mouth
    mouth_y = cy + 8
    if expression == "neutral":
        d.line((cx-10+off_x, mouth_y+off_y, cx+10+off_x, mouth_y+off_y), fill=(10, 0, 0), width=2)
    elif expression == "angry":
        d.line((cx-12+off_x, mouth_y-4+off_y, cx+0+off_x, mouth_y+off_y), fill=(10, 0, 0), width=2)
        d.line((cx+0+off_x, mouth_y+off_y, cx+12+off_x, mouth_y-4+off_y), fill=(10, 0, 0), width=2)
    elif expression == "smug":
        d.arc((cx-12+off_x, mouth_y-6+off_y, cx+12+off_x, mouth_y+6+off_y), start=0, end=180, fill=(10, 0, 0), width=2)
    elif expression == "bored":
        d.arc((cx-12+off_x, mouth_y-4+off_y, cx+12+off_x, mouth_y+4+off_y), start=180, end=360, fill=(10, 0, 0), width=2)
    
    # Footer
    d.rectangle((0,H-12,W,H), fill=(34, 0, 0))
    d.text((4,H-10), "OK=pet  K2=status  K3=exit", font=f9, fill=(192, 57, 43))
    
    # If message, draw bubble
    if message:
        d.rectangle((4, H-48, W-4, H-14), fill=(10, 0, 0), outline="#FF3333")
        lines = []
        words = message.split()
        line = ""
        for w in words:
            if len(line + " " + w) <= 22:
                line += (" " + w if line else w)
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        y = H-44
        for l in lines[:3]:
            d.text((6, y), l, font=f9, fill=(171, 178, 185))
            y += 12
    
    LCD.LCD_ShowImage(img, 0, 0)

# ----------------------------------------------------------------------
# Rock logic
# ----------------------------------------------------------------------
class PetRock:
    def __init__(self):
        self.pet_count = 0
        self.rolled_over = False
        self.mood = "neutral"
        self.blink_timer = time.time() + random.uniform(2, 6)
        self.shake_until = 0
        self.last_interaction = time.time()
    
    def update_mood(self):
        if self.pet_count >= 80:
            self.mood = "angry"
        elif self.pet_count >= 50:
            self.mood = "smug"
        elif self.pet_count >= 20:
            self.mood = "bored"
        else:
            self.mood = "neutral"
    
    def pet(self):
        self.pet_count += 1
        self.last_interaction = time.time()
        self.update_mood()
        if self.pet_count >= 100 and not self.rolled_over:
            self.rolled_over = True
            self.shake_until = time.time() + 1.5
            return "The rock slowly rolls over... then stops. It's still a rock."
        else:
            msg = random.choice(PET_RESPONSES)
            if self.pet_count > 50:
                msg = msg + " (Again?!)"
            return msg
    
    def status(self):
        if self.rolled_over:
            return f"Rolled over once. {self.pet_count} pets. Still a rock."
        else:
            return f"Pet count: {self.pet_count}/100 to roll. Still a rock."
    
    def should_blink(self):
        now = time.time()
        if now >= self.blink_timer:
            self.blink_timer = now + random.uniform(3, 8)
            return True
        return False
    
    def is_shaking(self):
        return time.time() < self.shake_until

# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------
def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def main():
    rock = PetRock()
    msg_display = None
    msg_expire = 0
    blink_state = False
    
    while True:
        now = time.time()
        btn = wait_btn(0.05)
        
        if btn == "KEY3":
            break
        elif btn == "OK":
            msg = rock.pet()
            msg_display = msg
            msg_expire = now + 2.0
            if rock.is_shaking():
                pass  # shake already handled
        elif btn == "KEY2":
            msg = rock.status()
            msg_display = msg
            msg_expire = now + 2.5
        
        # Clear message after timeout
        if now >= msg_expire:
            msg_display = None
        
        # Blink animation
        if rock.should_blink():
            draw_rock_face(expression=rock.mood, blink=True, shake=3 if rock.is_shaking() else 0, message=msg_display if now < msg_expire else None)
            time.sleep(0.1)
        
        # Draw normal face
        draw_rock_face(expression=rock.mood, blink=False, shake=3 if rock.is_shaking() else 0, message=msg_display if now < msg_expire else None)
        
        time.sleep(0.05)
    
    # Exit message
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.text((10,50), "Goodbye.", font=f11, fill=(231, 76, 60))
    d.text((10,70), "The rock will remember.", font=f9, fill=(171, 178, 185))
    LCD.LCD_ShowImage(img,0,0)
    time.sleep(1.5)
    GPIO.cleanup()

if __name__ == "__main__":
    main()
