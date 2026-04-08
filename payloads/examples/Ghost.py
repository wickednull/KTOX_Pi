#!/usr/bin/env python3
"""
KTOx ULTRA-HACKER HUD – Cyberpunk Elite Edition
-------------------------------------------------
HUD with live packet visualization, pulsing threat bars,
ghost trails, AI cyberpunk logs, and neon glitch animations.
"""

import os, time, random, json, subprocess
from datetime import datetime

try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except:
    HAS_HW = False
    print("Hardware not detected, running in simulation mode")

# ── CONFIG ─────────────────────────────────────────────
W,H=128,128
PINS={"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
MODES=["HUD","GHOST","AI","GAME","AURA"]
MODE=0
DEVICE_LOG="ktx_devices.json"
MAX_AI_LOG=20

# ── GLOBALS ─────────────────────────────────────────────
devices = {}
ghost_trails = {}
ai_log=[]
game_code=[random.randint(0,3) for _ in range(4)]
game_input=[]
_glitch_timer = 0

LCD=_draw=_image=_font=None

# ── PHRASES ─────────────────────────────────────────────
AI_PHRASES=[
"Neon shadows detected","Packet ghosts online","Signal spike at 0xDEADBEEF",
"Firewall bypassed","Ghost in the machine","Zero-day incoming",
"Code bleeding","Packet swarm detected","Deep web shadows",
"Quantum breach active","System integrity compromised","Encrypting reality",
"Cyber drift detected","Neural overload imminent","RAM ghosts active",
"Network bleed detected","Ghost packet spawned","Black ICE alert",
"Override initialized","Synthetic pulse detected","Signal anomaly",
"Digital phantoms","Firmware breach","Trace suppressed","Data shadowing active",
"Neon grid compromised","Network phantoms","Memory leak detected","Pulse breach",
"Digital bleed","AI ghost detected","Kernel override","Firmware anomaly",
"Packet cascade","Quantum leak","Signal breach","Cyber drift","Black code active",
"Neural spike","Firewall phantom","Packet anomaly","System shadow","Data ripple",
"Code fragment found","Network bleed","Signal pulse","Deep net trace","Override active",
"Ghost matrix detected","Cyber pulse","Neural bleed","Packet shadow","Digital breach",
"Signal ripple","Zero-trust breach","Memory ghost","System phantom","Network spike",
"Firmware ghost","AI drift","Quantum spike","Cyber ripple","Code ghosted","Pulse detected",
"Packet drift","System breach","Digital ripple","Neon ghost","Kernel spike","Data phantom",
"Signal ghost","Firmware bleed","Override detected","Neural trace","Packet fragment",
"Deep web breach","Cyber anomaly","Black ICE spike","Ghost protocol","AI breach",
"Signal anomaly detected","Packet ripple","Cyber phantom","Neural ghost"
]

# ── INIT ───────────────────────────────────────────────
def init():
    global LCD,_draw,_image,_font
    if not HAS_HW: return
    GPIO.setmode(GPIO.BCM)
    for p in PINS.values(): GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD=LCD_1in44.LCD(); LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT); LCD.LCD_Clear()
    _image=Image.new("RGB",(W,H),"black"); _draw=ImageDraw.Draw(_image); _font=ImageFont.load_default()

def push():
    if HAS_HW and LCD: LCD.LCD_ShowImage(_image,0,0)

# ── DEVICE LOG ──────────────────────────────────────────
def load_devices():
    global devices
    if os.path.exists(DEVICE_LOG):
        try: devices=json.load(open(DEVICE_LOG,"r"))
        except: devices={}

def save_devices(): json.dump(devices, open(DEVICE_LOG,"w"))

# ── SYSTEM STATS ───────────────────────────────────────
def get_cpu():
    try: return float(subprocess.getoutput("top -bn1 | grep 'Cpu' | awk '{print $2}'"))
    except: return 0.0
def get_ram():
    try: mem=subprocess.getoutput("free -m | grep Mem").split(); return int(mem[2]),int(mem[1])
    except: return 0,0
def get_temp():
    try: return float(subprocess.getoutput("vcgencmd measure_temp").split('=')[1].split("'")[0])
    except: return 0.0

# ── WIFI SCAN & PACKET SIM ──────────────────────────────
def scan_wifi():
    global devices
    nets=[]
    try:
        iface=subprocess.getoutput("iw dev | grep Interface | awk '{print $2}'").splitlines()[0]
        raw=subprocess.getoutput(f"iwlist {iface} scanning | egrep 'ESSID|Signal level'")
        lines=raw.splitlines()
        for i in range(0,len(lines),2):
            try:
                ssid=lines[i].split(":")[1].replace('"','')
                sig=int(lines[i+1].split("=")[2].split()[0])
                mac=f"{ssid}_{sig}"; threat=max(1,min(5,int((sig+100)/20)))
                devices[mac]={"ssid":ssid,"sig":sig,"threat":threat,"last_seen":datetime.now().isoformat()}
                nets.append((ssid,sig,threat))
            except: continue
    except: pass
    return nets

# ── AI UPDATE ──────────────────────────────────────────
def ai_update(nets):
    global ai_log
    if not nets or random.random()<0.3: msg=random.choice(AI_PHRASES)
    else: msg=f"Detected {len(nets)} signals"
    ai_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(ai_log)>MAX_AI_LOG: ai_log.pop(0)

# ── DRAW FUNCTIONS ─────────────────────────────────────
def draw_hud(nets):
    global _glitch_timer
    _draw.rectangle((0,0,W,H), fill="black")
    cpu=get_cpu(); ram_used,ram_total=get_ram(); temp=get_temp()
    _draw.text((2,2),"HUD",font=_font,fill="#FF44FF")
    _draw.text((2,15),f"CPU:{cpu:.1f}%",font=_font,fill="#FF88FF")
    _draw.text((2,28),f"RAM:{ram_used}/{ram_total}MB",font=_font,fill="#FF88FF")
    _draw.text((2,41),f"TEMP:{temp:.1f}C",font=_font,fill="#FF88FF")
    _draw.text((2,54),f"NETS:{len(nets)}",font=_font,fill="#FF88FF")

    top_nets=sorted(nets,key=lambda x:x[2],reverse=True)[:5]
    for i,(s,sig,threat) in enumerate(top_nets):
        bar="#"*threat; color=["#44FF44","#FFFF44","#FF4444","#FF2222","#880000"][min(threat-1,4)]
        # PULSING threat
        if int(time.time()*2)%2==0: color="#FF0000"
        _draw.text((2,67+i*10),f"{s[:12]} {bar}",font=_font,fill=color)
        # LIVE packet spikes
        for j in range(threat): _draw.line((2+j*3,67+i*10,2+j*3,67+i*10-random.randint(1,5)),fill=color)

    # NEON GLITCH
    _glitch_timer+=1
    if _glitch_timer%3==0:
        for _ in range(2):
            x1=random.randint(0,W-1); y1=random.randint(0,H-1)
            x2=x1+random.randint(1,5); y2=y1+random.randint(1,5)
            _draw.rectangle((x1,y1,x2,y2),outline="#FF00FF")

def draw_ghost(nets):
    _draw.rectangle((0,0,W,H), fill="black")
    t=int(time.time()*5)
    for i,(s,sig,threat) in enumerate(nets[:8]):
        x=(i*15+t)%W; y=int((sig+100)*1.2)%H
        colors=["#44FF44","#FFFF44","#FF4444","#FF2222","#880000"]
        c=colors[min(threat-1,len(colors)-1)]
        _draw.ellipse((x,y,x+3,y+3), fill=c)
        ghost_trails.setdefault(s,[]).append((x,y))
        if len(ghost_trails[s])>6: ghost_trails[s].pop(0)
        for j,(tx,ty) in enumerate(ghost_trails[s]): _draw.ellipse((tx,ty,tx+2,ty+2), fill=c)

def draw_ai():
    _draw.rectangle((0,0,W,H), fill="black")
    _draw.text((2,2),"AI",font=_font,fill="#FF44FF")
    for i,line in enumerate(ai_log[-6:]): _draw.text((2,15+i*15),line[:18],font=_font,fill="#FFCCFF")

def draw_game():
    _draw.rectangle((0,0,W,H), fill="black"); _draw.text((2,2),"UNLOCK",font=_font,fill="#FF44FF")
    for i,v in enumerate(game_input): _draw.text((10+i*20,60),str(v),font=_font,fill="#FFCCFF")

def draw_aura():
    _draw.rectangle((0,0,W,H), fill=(random.randint(0,50),0,random.randint(0,50)))

# ── MAIN LOOP ─────────────────────────────────────────
def main():
    global MODE, game_input
    init(); load_devices()
    while True:
        nets=scan_wifi(); ai_update(nets)
        if MODE==0: draw_hud(nets)
        elif MODE==1: draw_ghost(nets)
        elif MODE==2: draw_ai()
        elif MODE==3: draw_game()
        elif MODE==4: draw_aura()
        push()

        if HAS_HW:
            if GPIO.input(PINS["UP"])==0: MODE=(MODE-1)%len(MODES); time.sleep(0.3)
            if GPIO.input(PINS["DOWN"])==0: MODE=(MODE+1)%len(MODES); time.sleep(0.3)
            if MODE==3:
                if GPIO.input(PINS["LEFT"])==0: game_input.append(0)
                if GPIO.input(PINS["RIGHT"])==0: game_input.append(1)
                if GPIO.input(PINS["OK"])==0: game_input.append(2)
                if GPIO.input(PINS["KEY1"])==0: game_input.append(3)
                if len(game_input)==4:
                    if game_input==game_code: ai_log.append("ACCESS GRANTED")
                    else: ai_log.append("ACCESS DENIED")
                    game_input=[]
                    time.sleep(1)
            if GPIO.input(PINS["KEY3"])==0: break
        time.sleep(0.1)

    save_devices()
    if HAS_HW:
        GPIO.cleanup(); LCD.LCD_Clear()

if __name__=="__main__": main()
