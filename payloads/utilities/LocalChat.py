#!/usr/bin/env python3
"""
KTOx Payload – KTOx Mesh Chat
===============================
Author: wickednull

A decentralized, serverless chat network for KTOx devices over a LAN.
- Auto-discovers peers using UDP broadcast.
- Direct peer-to-peer TCP connections for chatting.
- Full control via KTOx LCD and buttons.

Controls:
  UP/DOWN    – Scroll chat history.
  OK         – Enter character (keyboard) / send message (review screen).
  KEY1       – Switch to keyboard / send (review screen).
  KEY2       – Backspace (keyboard) / switch to conversation view (review).
  KEY3       – Exit.
"""

import os
import sys
import time
import socket
import threading
import select
import textwrap
import json
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from payloads._darksec_keyboard import DarkSecKeyboard

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
# Network Constants & Config
# ----------------------------------------------------------------------
UDP_PORT = 9999
TCP_PORT = 9998
BROADCAST_ADDR = '<broadcast>'
BUFFER_SIZE = 4096

# Global state
username = ""
chat_history = []       # list of (sender, message, timestamp)
peers = {}              # ip -> socket
running = True
state = "setup"         # setup, conversation, typing

# Locks for thread-safe operations
history_lock = threading.Lock()
peers_lock = threading.Lock()

# ----------------------------------------------------------------------
# LCD Helpers
# ----------------------------------------------------------------------
def draw_screen(lines, title="KTOx MESH", title_color="#8B0000", text_color="#FFBBBB"):
    img = Image.new("RGB", (W, H), "#0A0000")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 17), fill=title_color)
    d.text((4, 3), title[:20], font=f9, fill=(231, 76, 60) if title_color == "#8B0000" else "white")
    y = 20
    for line in lines[:7]:
        d.text((4, y), line[:23], font=f9, fill=text_color)
        y += 12
    d.rectangle((0, H-12, W, H), fill="#220000")
    d.text((4, H-10), "UP/DN OK KEY1/2 K3", font=f9, fill="#FF7777")
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
    kb = DarkSecKeyboard(width=W, height=H, lcd=LCD, gpio_pins=PINS, gpio_module=GPIO)
    result = kb.run()
    if result is None:
        return None
    result = result.strip()
    return result or initial

# ----------------------------------------------------------------------
# Chat History Viewer
# ----------------------------------------------------------------------
class ChatView:
    def __init__(self):
        self.scroll = 0
        self.lines = []

    def rebuild_lines(self):
        with history_lock:
            self.lines = []
            for sender, msg, ts in chat_history[-50:]:
                time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                prefix = f"{sender}:"
                wrapped = textwrap.wrap(msg, width=20)
                for i, line in enumerate(wrapped):
                    if i == 0:
                        self.lines.append(f"{prefix} {line}")
                    else:
                        self.lines.append(f"  {line}")
                self.lines.append("")  # Spacer
        self.scroll = max(0, len(self.lines) - 6)

    def draw(self):
        self.rebuild_lines()
        if not self.lines:
            draw_screen(["No messages yet", "Press KEY1 to chat"], title="CHAT ROOM")
            return
        total = len(self.lines)
        visible = self.lines[self.scroll:self.scroll+6]
        display = visible + [f"Line {self.scroll+1}/{total}"] if total > 6 else visible
        draw_screen(display, title="CHAT ROOM", title_color="#8B0000")

    def scroll_up(self):
        if self.scroll > 0:
            self.scroll -= 1
            self.draw()

    def scroll_down(self):
        if self.scroll + 6 < len(self.lines):
            self.scroll += 1
            self.draw()

# ----------------------------------------------------------------------
# Peer-to-Peer Networking Core
# ----------------------------------------------------------------------
def get_local_ip():
    """Get the local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def broadcast_presence():
    """Periodically broadcast username via UDP."""
    global running
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1)
    message = json.dumps({"type": "presence", "username": username, "ip": get_local_ip()})
    while running:
        try:
            sock.sendto(message.encode(), (BROADCAST_ADDR, UDP_PORT))
        except:
            pass
        time.sleep(5)
    sock.close()

def listen_for_peers():
    """Listen for UDP broadcasts and connect to new peers via TCP."""
    global running
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', UDP_PORT))
    sock.settimeout(1)
    
    while running:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)
            if addr[0] == get_local_ip():
                continue
            msg = json.loads(data.decode())
            if msg.get("type") == "presence" and msg["username"] != username:
                peer_ip = msg.get("ip", addr[0])
                with peers_lock:
                    if peer_ip not in peers:
                        # Attempt TCP connection to this new peer
                        try:
                            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            tcp_sock.connect((peer_ip, TCP_PORT))
                            peers[peer_ip] = tcp_sock
                            add_message("System", f"{msg['username']} joined the chat", time.time())
                            # Start a thread to listen on this TCP socket
                            threading.Thread(target=handle_tcp_peer, args=(tcp_sock, peer_ip, msg['username']), daemon=True).start()
                        except:
                            pass
        except:
            pass
    sock.close()

def tcp_server():
    """Accept incoming TCP connections from other KTOx devices."""
    global running
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('', TCP_PORT))
    server.listen(5)
    server.settimeout(1)
    
    while running:
        try:
            client, addr = server.accept()
            with peers_lock:
                if addr[0] not in peers:
                    peers[addr[0]] = client
                    # First message should be a handshake with username
                    try:
                        data = client.recv(BUFFER_SIZE).decode()
                        handshake = json.loads(data)
                        if handshake.get("type") == "handshake":
                            peer_name = handshake.get("username", "Unknown")
                            add_message("System", f"{peer_name} joined the chat", time.time())
                            threading.Thread(target=handle_tcp_peer, args=(client, addr[0], peer_name), daemon=True).start()
                    except:
                        pass
        except:
            pass
    server.close()

def handle_tcp_peer(sock, ip, peer_name):
    """Receive messages from a connected TCP peer."""
    global running
    sock.settimeout(1)
    while running:
        try:
            data = sock.recv(BUFFER_SIZE).decode()
            if not data:
                break
            msg = json.loads(data)
            if msg.get("type") == "chat":
                add_message(peer_name, msg["text"], time.time())
        except:
            break
    # Peer disconnected
    with peers_lock:
        if ip in peers:
            del peers[ip]
    add_message("System", f"{peer_name} left the chat", time.time())
    sock.close()

def send_message_to_all(msg_text):
    """Broadcast a chat message to all connected TCP peers."""
    payload = json.dumps({"type": "chat", "text": msg_text})
    with peers_lock:
        for ip, sock in list(peers.items()):
            try:
                sock.send(payload.encode())
            except:
                # Remove dead socket
                del peers[ip]

def add_message(sender, text, timestamp):
    """Add a message to the global chat history."""
    with history_lock:
        chat_history.append((sender, text, timestamp))
        if len(chat_history) > 200:
            chat_history.pop(0)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    global username, state, running
    
    # Username setup screen
    draw_screen(["KTOx Mesh Chat", "", "Enter your username:"], title="SETUP")
    username = osk_input("Username:", "ktox_user")
    if not username:
        draw_screen(["Setup cancelled", "KEY3 to exit"], title_color="#FF4444")
        while wait_btn(0.5) != "KEY3":
            pass
        return
    
    # Start network threads
    threading.Thread(target=broadcast_presence, daemon=True).start()
    threading.Thread(target=listen_for_peers, daemon=True).start()
    threading.Thread(target=tcp_server, daemon=True).start()
    
    # Send handshake to existing peers (will be handled by listen_for_peers)
    time.sleep(1)
    add_message("System", f"Welcome, {username}!", time.time())
    add_message("System", "Waiting for other KTOx devices...", time.time())
    
    chat_view = ChatView()
    state = "conversation"
    
    while running:
        if state == "conversation":
            chat_view.draw()
            btn = wait_btn(0.5)
            if btn == "UP":
                chat_view.scroll_up()
            elif btn == "DOWN":
                chat_view.scroll_down()
            elif btn == "KEY1":
                state = "typing"
            elif btn == "KEY3":
                break
        elif state == "typing":
            msg_text = osk_input("Send message:", "")
            if msg_text is None:
                state = "conversation"
                continue
            # Add to local history
            add_message(username, msg_text, time.time())
            # Send to all peers
            send_message_to_all(msg_text)
            state = "conversation"
            chat_view.draw()
        time.sleep(0.05)
    
    running = False
    GPIO.cleanup()
    print("[KTOx Mesh Chat] Exited.")

if __name__ == "__main__":
    main()
