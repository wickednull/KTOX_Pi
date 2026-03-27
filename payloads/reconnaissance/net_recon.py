#!/usr/bin/env python3
# NAME: Network Recon
# DESC: Scan network, log all hosts with MAC/vendor/hostname to loot

import sys, os, time, signal
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont

# KTOx/KTOx compatibility
sys.path.insert(0, "/root/KTOx")
import LCD_Config
import LCD_1in44

# ── Config ────────────────────────────────────────────────────────────────────

PAYLOAD_NAME = "net_recon"
LOOT_DIR     = os.environ.get("PAYLOAD_LOOT_DIR",
               f"/root/ktox_loot/payloads/{PAYLOAD_NAME}")
LOG_FILE     = f"/tmp/{PAYLOAD_NAME}_debug.log"
RUNNING      = True

os.makedirs(LOOT_DIR, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

# ── Font helper ───────────────────────────────────────────────────────────────

def load_font(size=9):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", size)
    except:
        return ImageFont.load_default()

FONT_SM = load_font(9)
FONT_MD = load_font(11)

# ── Display helpers ───────────────────────────────────────────────────────────

def centered(draw, text, y, font, fill="WHITE"):
    bbox = draw.textbbox((0, 0), text, font=font)
    w    = bbox[2] - bbox[0]
    draw.text(((128 - w) // 2, y), text, font=font, fill=fill)

def show_status(lcd, image, draw, title, lines, color="WHITE"):
    draw.rectangle([(0, 0), (128, 128)], fill="BLACK")
    # Header
    draw.rectangle([(0, 0), (128, 14)], fill="#640000")
    centered(draw, title, 2, FONT_MD, "WHITE")
    # Lines
    y = 18
    for line in lines[:6]:
        col = "#1E8449" if line.startswith("+") else \
              "#E74C3C" if line.startswith("!") else \
              "#D4AC0D" if line.startswith("~") else color
        draw.text((3, y), line[:20], font=FONT_SM, fill=col)
        y += 12
    lcd.LCD_ShowImage(image, 0, 0)

# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup(*_):
    global RUNNING
    if not RUNNING: return
    RUNNING = False
    log("Cleaning up...")
    try:
        LCD_1in44.LCD().LCD_Clear()
    except:
        pass
    try:
        GPIO.cleanup()
    except:
        pass
    log("Done.")

signal.signal(signal.SIGINT,  cleanup)
signal.signal(signal.SIGTERM, cleanup)

# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        log("Starting Network Recon payload")

        # Hardware init
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LCD_Config.KEY3_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        lcd = LCD_1in44.LCD()
        lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        lcd.LCD_Clear()

        image = Image.new("RGB", (128, 128), "BLACK")
        draw  = ImageDraw.Draw(image)

        show_status(lcd, image, draw, "NET RECON",
                    ["~ Starting scan...", "~ KEY3 to abort"])
        time.sleep(1)

        # Run KTOx scan
        import scan as _scan
        import netifaces

        try:
            gw_info = netifaces.gateways()
            gw_ip   = gw_info["default"][netifaces.AF_INET][0]
            iface   = gw_info["default"][netifaces.AF_INET][1]
        except:
            gw_ip  = "192.168.1.1"
            iface  = "eth0"

        net = gw_ip.rsplit(".", 1)[0] + ".0/24"
        log(f"Scanning {net} on {iface}")
        show_status(lcd, image, draw, "NET RECON",
                    [f"~ Scanning", f"  {net}", "~ Please wait..."])

        hosts = _scan.scanNetwork(net)
        log(f"Found {len(hosts)} hosts")

        # Save results
        import json, csv
        ts      = time.strftime("%Y%m%d_%H%M%S")
        json_path = f"{LOOT_DIR}/recon_{ts}.json"
        csv_path  = f"{LOOT_DIR}/recon_{ts}.csv"

        result = []
        for h in hosts:
            entry = {
                "ip":       h[0] if len(h)>0 else "",
                "mac":      h[1] if len(h)>1 else "",
                "vendor":   h[2] if len(h)>2 else "",
                "hostname": h[3] if len(h)>3 else "",
            }
            result.append(entry)
            log(f"  {entry['ip']} {entry['mac']} {entry['vendor']}")
            print(f"+ {entry['ip']} {entry['mac']} {entry.get('vendor','')}")

        with open(json_path, "w") as f:
            json.dump({"gateway": gw_ip, "network": net,
                       "host_count": len(result), "hosts": result}, f, indent=2)

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ip","mac","vendor","hostname"])
            writer.writeheader()
            writer.writerows(result)

        log(f"Saved to {json_path}")

        # Show results on LCD, scroll through hosts
        lines = [f"+ {len(hosts)} hosts found", f"~ GW: {gw_ip}"]
        for h in hosts[:4]:
            lines.append(f"  {h[0]}")
        if len(hosts) > 4:
            lines.append(f"  +{len(hosts)-4} more")
        lines.append("~ Saved to loot")

        show_status(lcd, image, draw, "RECON DONE", lines, "WHITE")

        # Wait for KEY3 or timeout
        start = time.time()
        last  = 0
        while RUNNING and (time.time() - start) < 30:
            now = time.time()
            if now - last > 0.1:
                last = now
                if GPIO.input(LCD_Config.KEY3_PIN) == 0:
                    break
            time.sleep(0.05)

    except Exception as e:
        log(f"FATAL: {e}")
        import traceback
        with open(LOG_FILE, "a") as f:
            traceback.print_exc(file=f)

    finally:
        cleanup()
