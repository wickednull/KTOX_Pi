#!/usr/bin/env python3
"""
Test version of Pet_Rock_WiFi_Pro without hardware dependencies
Simulates WiFi scanning to test emotion changes and logic
"""

import time
import threading
import random
from collections import defaultdict

# Cute faces with moods
FACES = {
    "normal": "(◕‿◕)",
    "blink": "(-‿-)",
    "happy": "(≧◡≦)",
    "excited": "(☼◡☼)",
    "cracked": "(★◡★)",
    "cracking": "(⊙_⊙)",
    "attacking": "(⌐■_■)",
    "deauthing": "(◣_◢)",
    "pmkid": "(ᗒᗨᗕ)",
    "half": "(◕∇◕)",
    "scanning": "(ಠ_↼)",
    "waiting": "(·_·)",
    "stealth": "(#◡#)",
    "lost": "(X∇X)",
}

MOOD_DURATIONS = {
    "happy": 4.0, "excited": 3.0, "cracked": 5.0, "cracking": 0,
    "attacking": 2.5, "deauthing": 2.0, "pmkid": 4.0, "half": 3.0,
    "scanning": 0, "waiting": 0, "lost": 2.0,
}

mood = "waiting"
mood_timer = None
lock = threading.Lock()
shutdown = False

session_aps = {}
session_hs = session_hhs = session_pmkid = 0
lifetime_hs = lifetime_hhs = lifetime_pmkid = 0

def set_mood(new_mood):
    """Set mood with auto-revert timer."""
    global mood, mood_timer
    with lock:
        mood = new_mood
        if mood_timer:
            mood_timer.cancel()
        if dur := MOOD_DURATIONS.get(new_mood):
            mood_timer = threading.Timer(dur, lambda: set_mood("normal"))
            mood_timer.start()
    print(f"[MOOD] {new_mood} {FACES[new_mood]}")

def simulate_scanning():
    """Simulate WiFi scanning and handshake detection"""
    global session_aps, session_hs, session_hhs, session_pmkid, lifetime_hs, lifetime_hhs, lifetime_pmkid

    ap_count = 0
    tick = 0
    while not shutdown:
        time.sleep(0.3)
        tick += 1

        # Simulate discovering new APs (every 2-3 ticks)
        if tick % 3 == 0:
            ap_id = f"AA:BB:CC:DD:EE:{random.randint(1, 255):02X}"
            ssid = f"Network_{ap_count}"
            ap_count += 1
            session_aps[ap_id] = {"essid": ssid, "signal": random.randint(-80, -30)}
            print(f"[BEACON] New AP: {ap_id} ({ssid})")
            set_mood("scanning")

        # Simulate handshake capture (every 6-8 ticks)
        if tick % 7 == 0 and session_aps:
            ap_id = random.choice(list(session_aps.keys()))
            essid = session_aps[ap_id]["essid"]
            session_hs += 1
            lifetime_hs += 1
            print(f"[CAPTURE] 4-Way Handshake: {essid} ({ap_id})")
            set_mood("happy")

        # Simulate PMKID capture (every 10-15 ticks)
        if tick % 12 == 0 and session_aps:
            ap_id = random.choice(list(session_aps.keys()))
            essid = session_aps[ap_id]["essid"]
            session_pmkid += 1
            lifetime_pmkid += 1
            print(f"[CAPTURE] PMKID: {essid} ({ap_id})")
            set_mood("pmkid")

        # Simulate half handshake (every 8-10 ticks)
        if tick % 9 == 0 and session_aps:
            ap_id = random.choice(list(session_aps.keys()))
            essid = session_aps[ap_id]["essid"]
            session_hhs += 1
            lifetime_hhs += 1
            print(f"[CAPTURE] Half-Handshake: {essid} ({ap_id})")
            set_mood("half")

def display_loop():
    """Simulate display updates"""
    last_display = 0
    uptime = 0
    start = time.time()

    while not shutdown:
        now = time.time()

        # Update every 0.5 seconds
        if now - last_display > 0.5:
            uptime = int(now - start)
            with lock:
                current_mood = mood
                face = FACES.get(current_mood, FACES["normal"])
                aps = len(session_aps)
                total = session_hs + session_hhs + session_pmkid

            # Clear and redraw
            print("\033[2J\033[H", end="")  # Clear screen
            print("=" * 40)
            print("PET ROCK WiFi PRO - TEST MODE")
            print("=" * 40)
            print(f"Status: AP:{aps} Total:{total} LT:{lifetime_hs+lifetime_hhs+lifetime_pmkid}")
            print()
            print(f"   {face}   <- Current mood: {current_mood}")
            print()
            print(f"Session: HS:{session_hs} HHS:{session_hhs} PMKID:{session_pmkid}")
            print(f"Lifetime: HS:{lifetime_hs} HHS:{lifetime_hhs} PMKID:{lifetime_pmkid}")
            print(f"Uptime: {uptime//60:02d}:{uptime%60:02d}")
            print("=" * 40)
            print("Press Ctrl+C to exit")

            last_display = now

        time.sleep(0.1)

def main():
    global shutdown

    print("Pet Rock WiFi Pro - TEST MODE")
    print("Simulating WiFi scanning without hardware...\n")

    # Start scanning simulator
    scan_thread = threading.Thread(target=simulate_scanning, daemon=True)
    scan_thread.start()

    # Start display loop
    display_thread = threading.Thread(target=display_loop, daemon=True)
    display_thread.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        shutdown = True
        time.sleep(1)
        print("Done!")

if __name__ == "__main__":
    main()
