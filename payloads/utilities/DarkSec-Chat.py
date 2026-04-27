#!/usr/bin/env python3
"""
DarkSec-Chat – Unified Mesh + darksec.uk Chat
==============================================
Author: wickednull

- Full chat UI with on‑screen keyboard
- Joins KTOx mesh network (auto‑discovers peers)
- Bridges to darksec.uk/chat web room
- Scrollable conversation history
- Set your own username at startup

Controls:
  UP/DOWN  – scroll conversation
  KEY1     – open keyboard to send message
  KEY3     – exit (saves session)
"""

import os
import sys
import time
import socket
import threading
import json
import requests
import textwrap
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from _darksec_keyboard import DarkSecKeyboard
from _input_helper import flush_input

# ----------------------------------------------------------------------
# Hardware & LCD
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("KTOx hardware not found")
    sys.exit(1)

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

f9 = font(9)

# ----------------------------------------------------------------------
# Web API constants
# ----------------------------------------------------------------------
WEB_API_URL = "https://darksec.uk/api/chat"
WEB_API_KEY = os.environ.get("DARKSEC_API_KEY", "")  # Optional API key for authentication

# ----------------------------------------------------------------------
# LCD helpers
# ----------------------------------------------------------------------
def draw_screen(lines, title="DarkSec-Chat", title_color="#8B0000", text_color="#FFBBBB"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=title_color)
    d.text((4, 3), title[:20], font=f9, fill=(231, 76, 60) if title_color == "#8B0000" else "white")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill=text_color)
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN K1=send K3=exit", font=f9, fill="#FF7777")
    LCD.LCD_ShowImage(img, 0, 0)

def wait_btn(timeout=0.1):
    start = time.time()
    while time.time() - start < timeout:
        for name, pin in PINS.items():
            if GPIO.input(pin) == 0:
                time.sleep(0.05)
                return name
        time.sleep(0.02)
    return None

def osk_input(prompt="Enter:", initial=""):
    """Display prompt, wait for OK button, then show keyboard."""
    # Show prompt screen first
    draw_screen(
        [prompt, "", "(Press OK to", "start typing)"],
        title="INPUT"
    )

    # Wait for user to press OK to bring up keyboard
    while True:
        btn = wait_btn(0.2)
        if btn == "OK":
            # Wait for button release before opening keyboard
            while GPIO.input(PINS["OK"]) == 0:
                time.sleep(0.02)
            time.sleep(0.1)  # debounce delay
            break
        elif btn == "KEY3":
            # Wait for KEY3 release
            while GPIO.input(PINS["KEY3"]) == 0:
                time.sleep(0.02)
            return None
        time.sleep(0.05)

    # Clear button state before opening keyboard
    flush_input()
    time.sleep(0.1)
    # Ensure all GPIO buttons are released before keyboard start
    for pin in PINS.values():
        while GPIO.input(pin) == 0:
            time.sleep(0.02)

    kb = DarkSecKeyboard(width=W, height=H, lcd=LCD, gpio_pins=PINS, gpio_module=GPIO)
    result = kb.run()
    if result is None:
        return None
    result = result.strip()
    return result or initial

# ----------------------------------------------------------------------
# Chat storage & viewer
# ----------------------------------------------------------------------
chat_messages = []          # (sender, text, timestamp, source)
chat_lock = threading.Lock()
scroll_pos = 0
LOOT_DIR = "/root/KTOx/loot/DarkSecChat"
os.makedirs(LOOT_DIR, exist_ok=True)

def add_message(sender, text, source):
    with chat_lock:
        chat_messages.append((sender, text, time.time(), source))
        if len(chat_messages) > 200:
            chat_messages.pop(0)

def draw_chat():
    global scroll_pos
    with chat_lock:
        msgs = chat_messages[-50:]
    if not msgs:
        scroll_pos = 0
        draw_screen(["No messages yet", "Press K1 to send"], title="DarkSec-Chat")
        return
    # Build display lines (reverse order, newest at bottom, but we show top = newest)
    # We'll show the most recent messages, scrollable.
    lines = []
    for sender, text, ts, src in reversed(msgs[-20:]):
        time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        prefix = f"{sender}:"
        # Calculate wrap width: screen shows 23 chars max, minus prefix length for first line
        max_line_width = 23
        first_line_width = max(8, max_line_width - len(prefix) - 1)  # -1 for space after colon
        subsequent_line_width = max_line_width - 3  # -3 for "   " indent

        wrapped = []
        remaining_text = text
        first_line = True
        while remaining_text:
            if first_line:
                wrap_width = first_line_width
                first_line = False
            else:
                wrap_width = subsequent_line_width

            # Manual wrap since textwrap doesn't support varying widths
            if len(remaining_text) <= wrap_width:
                wrapped.append(remaining_text)
                break
            else:
                # Find last space within wrap_width
                chunk = remaining_text[:wrap_width]
                last_space = chunk.rfind(' ')
                if last_space > 0:
                    wrapped.append(remaining_text[:last_space])
                    remaining_text = remaining_text[last_space+1:]
                else:
                    wrapped.append(chunk)
                    remaining_text = remaining_text[wrap_width:]

        for i, line in enumerate(wrapped):
            if i == 0:
                lines.append(f"{prefix} {line}")
            else:
                lines.append(f"   {line}")
        lines.append("")
    # Constrain scroll_pos to valid range based on actual line count
    max_scroll = max(0, len(lines) - 6)
    scroll_pos = min(scroll_pos, max_scroll)
    visible = lines[scroll_pos:scroll_pos+6]
    draw_screen(visible, title="DarkSec-Chat", title_color="#8B0000")

def scroll_up():
    global scroll_pos
    if scroll_pos > 0:
        scroll_pos -= 1
        draw_chat()

def scroll_down():
    global scroll_pos
    scroll_pos += 1
    draw_chat()

# ----------------------------------------------------------------------
# Mesh networking
# ----------------------------------------------------------------------
UDP_PORT = 9999
TCP_PORT = 9998
BROADCAST_ADDR = '<broadcast>'
BUFFER_SIZE = 4096

mesh_running = True
mesh_username = ""
mesh_peers = {}        # ip -> socket
mesh_lock = threading.Lock()

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def mesh_broadcast_presence():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1)
    msg = json.dumps({"type": "presence", "username": mesh_username, "ip": get_local_ip()})
    while mesh_running:
        try:
            sock.sendto(msg.encode(), (BROADCAST_ADDR, UDP_PORT))
        except:
            pass
        time.sleep(5)
    sock.close()

def mesh_listen_for_peers():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', UDP_PORT))
    sock.settimeout(1)
    while mesh_running:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            if addr[0] == get_local_ip():
                continue
            msg = json.loads(data.decode())
            if msg.get("type") == "presence" and msg["username"] != mesh_username:
                peer_ip = msg.get("ip", addr[0])
                with mesh_lock:
                    if peer_ip not in mesh_peers:
                        try:
                            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            tcp_sock.connect((peer_ip, TCP_PORT))
                            mesh_peers[peer_ip] = tcp_sock
                            handshake = json.dumps({"type": "handshake", "username": mesh_username})
                            tcp_sock.send(handshake.encode())
                            threading.Thread(target=mesh_handle_tcp_peer, args=(tcp_sock, peer_ip, msg["username"]), daemon=True).start()
                        except:
                            pass
        except:
            pass
    sock.close()

def mesh_tcp_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('', TCP_PORT))
    server.listen(5)
    server.settimeout(1)
    while mesh_running:
        try:
            client, addr = server.accept()
            with mesh_lock:
                if addr[0] not in mesh_peers:
                    mesh_peers[addr[0]] = client
                    try:
                        data = client.recv(BUFFER_SIZE).decode()
                        handshake = json.loads(data)
                        if handshake.get("type") == "handshake":
                            peer_name = handshake.get("username", "Unknown")
                            threading.Thread(target=mesh_handle_tcp_peer, args=(client, addr[0], peer_name), daemon=True).start()
                    except:
                        pass
        except:
            pass
    server.close()

def mesh_handle_tcp_peer(sock, ip, peer_name):
    sock.settimeout(1)
    while mesh_running:
        try:
            data = sock.recv(BUFFER_SIZE).decode()
            if not data:
                break
            msg = json.loads(data)
            if msg.get("type") == "chat":
                add_message(peer_name, msg["text"], "mesh")
        except:
            break
    with mesh_lock:
        if ip in mesh_peers:
            del mesh_peers[ip]
    sock.close()

def mesh_send_message(text):
    payload = json.dumps({"type": "chat", "text": text})
    with mesh_lock:
        for ip, sock in list(mesh_peers.items()):
            try:
                sock.send(payload.encode())
            except:
                del mesh_peers[ip]

# ----------------------------------------------------------------------
# Web bridge
# ----------------------------------------------------------------------
web_poll_interval = 3
last_seen_ids = set()

def fetch_web_messages():
    try:
        headers = {"Content-Type": "application/json"}
        if WEB_API_KEY:
            headers["Authorization"] = f"Bearer {WEB_API_KEY}"
        r = requests.get(WEB_API_URL, headers=headers, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "messages" in data:
                return data["messages"]
        elif r.status_code != 200:
            print(f"[WEB] GET {r.status_code}: {r.text[:100]}")
        return []
    except Exception as e:
        print(f"[WEB] Fetch error: {e}")
        return []

def post_to_web(message):
    payload = {"username": mesh_username, "message": message}
    try:
        headers = {"Content-Type": "application/json"}
        if WEB_API_KEY:
            headers["Authorization"] = f"Bearer {WEB_API_KEY}"
        r = requests.post(WEB_API_URL, json=payload, headers=headers, timeout=5, verify=False)
        if r.status_code not in (200, 201):
            print(f"[WEB] POST failed: {r.status_code} - {r.text[:100]}")
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[WEB] POST error: {e}")
        return False

def web_poll_thread():
    global last_seen_ids
    poll_count = 0
    while mesh_running:
        time.sleep(web_poll_interval)
        msgs = fetch_web_messages()
        poll_count += 1
        if msgs:
            print(f"[WEB] Poll #{poll_count}: got {len(msgs)} messages")
        for msg in msgs:
            msg_id = f"{msg.get('username', '')}|{msg.get('message', '')}|{msg.get('timestamp', '')}"
            if msg_id not in last_seen_ids and msg.get("username") != mesh_username:
                last_seen_ids.add(msg_id)
                sender = msg.get("username", "WebUser")
                text = msg.get("message", "")
                if text:
                    print(f"[WEB] New message from {sender}: {text[:50]}")
                    add_message(sender, text, "web")
                    # Forward to mesh peers
                    mesh_send_message(f"[Web] {sender}: {text}")
            elif msg.get("username") == mesh_username:
                print(f"[WEB] Skipping own message from {msg.get('username')}")

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global mesh_username, mesh_running, scroll_pos

    # Step 1: Set username
    draw_screen(["DarkSec-Chat", "", "Enter username:"], title="SETUP")
    username = osk_input("Username:", "darksec_user")
    if not username:
        draw_screen(["No username", "Exiting"], title_color="#FF4444")
        time.sleep(2)
        GPIO.cleanup()
        return
    mesh_username = username
    add_message("System", f"{mesh_username} joined", "system")
    print(f"[STARTUP] User: {mesh_username}")
    print(f"[STARTUP] Web API: {WEB_API_URL}")

    # Step 2: Start mesh networking threads
    threading.Thread(target=mesh_broadcast_presence, daemon=True).start()
    threading.Thread(target=mesh_listen_for_peers, daemon=True).start()
    threading.Thread(target=mesh_tcp_server, daemon=True).start()
    # Step 3: Start web polling thread
    threading.Thread(target=web_poll_thread, daemon=True).start()
    time.sleep(1)  # allow threads to initialise
    print("[STARTUP] Threads started")

    add_message("System", "Connected to mesh and web", "system")
    draw_chat()

    # Main loop
    while True:
        btn = wait_btn(0.5)
        if btn == "UP":
            scroll_up()
        elif btn == "DOWN":
            scroll_down()
        elif btn == "KEY1":
            # Open keyboard to send message
            msg_text = osk_input("Send message:", "")
            if msg_text:
                # Send to mesh
                mesh_send_message(msg_text)
                # Send to web
                post_to_web(msg_text)
                # Add to own chat
                add_message(mesh_username, msg_text, "self")
                draw_chat()
        elif btn == "KEY3":
            break
        else:
            draw_chat()  # refresh
        time.sleep(0.05)

    # Exit: save session
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOOT_DIR, f"session_{mesh_username}_{ts}.txt")
    with open(log_file, "w") as f:
        f.write(f"DarkSec-Chat Session - {mesh_username}\n")
        f.write(f"Started: {datetime.now().isoformat()}\n")
        f.write("-" * 40 + "\n")
        with chat_lock:
            for sender, text, ts, src in chat_messages:
                f.write(f"[{datetime.fromtimestamp(ts).strftime('%H:%M:%S')}] {sender}: {text}\n")
    draw_screen([f"Session saved", log_file[-25:], "KEY3 to exit"], title="DarkSec-Chat", title_color="#8B0000")
    while wait_btn(0.5) != "KEY3":
        pass
    mesh_running = False
    time.sleep(0.5)
    GPIO.cleanup()

if __name__ == "__main__":
    # Ensure requests is installed
    try:
        import requests
    except ImportError:
        os.system("pip install requests")
        import requests
    main()
