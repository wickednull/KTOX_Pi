import os
import sys
import time
import subprocess
import re
import threading
from datetime import datetime
import random

# Add KTOx root to sys.path for imports
sys.path.append('/root/KTOx/')

# Add the parent directory of the current script to sys.path to find helpers
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.append(parent_dir)

# Import KTOx LCD modules
try:
    import LCD_1in44, LCD_Config
    from PIL import Image, ImageDraw, ImageFont
    import RPi.GPIO as GPIO
    LCD_AVAILABLE = True
except ImportError as e:
    print(f"LCD import error: {e}")
    LCD_AVAILABLE = False

# Import monitor mode helper
try:
    import monitor_mode_helper
except ImportError as e:
    print(f"monitor_mode_helper import error: {e}")
    sys.exit("monitor_mode_helper not found. Exiting.")

# Import scapy for pcap processing
try:
    from scapy.all import rdpcap, Dot11, Dot11Elt, EAPOL
    from scapy.utils import wrpcap
    SCAPY_AVAILABLE = True
except ImportError as e:
    print(f"Scapy import error: {e}")
    SCAPY_AVAILABLE = False

# --- Configuration ---
PWNAGOTCHI_LOG_FILE = "/tmp/pwnagotchi_payload.log"
PWNAGOTCHI_PCAP_DIR = "/root/KTOx/loot/pwnagotchi_pcaps/"
PWNAGOTCHI_HANDSHAKE_DIR = "/root/KTOx/loot/handshakes/" # Where verified handshakes will go
PWNAGOTCHI_HASHCAT_DIR = "/root/KTOx/loot/hashcat_files/"

# --- Global State ---
HCXTOOLS_AVAILABLE = False

# --- Logging ---
def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [PWNAGOTCHI] {message}"
    print(log_msg)
    try:
        with open(PWNAGOTCHI_LOG_FILE, 'a') as f:
            f.write(log_msg + "\\n")
    except Exception as e:
        print(f"Error writing to log file: {e}")

# --- Pwnagotchi UI Class ---
class PwnagotchiUI:
    def __init__(self, lcd_display):
        self.lcd = lcd_display
        self.width = 128
        self.height = 128
        self.image = Image.new("RGB", (self.width, self.height), "BLACK")
        self.draw = ImageDraw.Draw(self.image)
        
        # Fonts
        log("Forcing default PIL font to isolate potential crash source.")
        self.font_small = ImageFont.load_default()
        self.font_medium = ImageFont.load_default()
        self.font_large = ImageFont.load_default()

        self.view_mode = "main"
        self.face_state = 0 # 0: neutral, 1: happy, 2: sad, 3: pwned, 4: bored, 5: excited
        self.status_message = "Initializing..."
        self.handshakes_count = 0
        self.channel = "N/A"
        self.uptime = 0
        self.last_update_time = time.time()

        # Face mode attributes
        self.sayings = [
            "feed me handshakes", "looking for wifi...", "is that a deauth?",
            "hehehe >:)", "*zzt*", "pwned!", "sleepy...", "bored",
            "need more power", "channel surfing..."
        ]
        self.bubble_text = None
        self.bubble_timer = 0
        self.bubble_duration = 5 # seconds

        # Settings mode attributes
        self.settings = {}
        self.settings_options = []
        self.settings_cursor = 0

    def _draw_face(self, box):
        # Simple Pwnagotchi-like face based on state, drawn in a specific box
        x, y, width, height = box
        
        # Scale factors for drawing within the box
        w_ratio = width / 25.0
        h_ratio = height / 25.0

        if self.face_state == 0: # Neutral
            self.draw.ellipse([(x + 5*w_ratio, y + 5*h_ratio), (x + 10*w_ratio, y + 10*h_ratio)], fill="WHITE")
            self.draw.ellipse([(x + 15*w_ratio, y + 5*h_ratio), (x + 20*w_ratio, y + 10*h_ratio)], fill="WHITE")
            self.draw.line([(x + 10*w_ratio, y + 15*h_ratio), (x + 15*w_ratio, y + 15*h_ratio)], fill="WHITE", width=1)
        elif self.face_state == 1: # Happy
            self.draw.ellipse([(x + 5*w_ratio, y + 5*h_ratio), (x + 10*w_ratio, y + 10*h_ratio)], fill="WHITE")
            self.draw.ellipse([(x + 15*w_ratio, y + 5*h_ratio), (x + 20*w_ratio, y + 10*h_ratio)], fill="WHITE")
            self.draw.arc([(x + 8*w_ratio, y + 10*h_ratio), (x + 17*w_ratio, y + 20*h_ratio)], 0, 180, fill="WHITE", width=2)
        elif self.face_state == 2: # Sad
            self.draw.ellipse([(x + 5*w_ratio, y + 5*h_ratio), (x + 10*w_ratio, y + 10*h_ratio)], fill="WHITE")
            self.draw.ellipse([(x + 15*w_ratio, y + 5*h_ratio), (x + 20*w_ratio, y + 10*h_ratio)], fill="WHITE")
            self.draw.arc([(x + 8*w_ratio, y + 15*h_ratio), (x + 17*w_ratio, y + 25*h_ratio)], 180, 360, fill="WHITE", width=2)
        elif self.face_state == 3: # Pwned
            self.draw.line([(x + 5*w_ratio, y + 8*h_ratio), (x + 10*w_ratio, y + 8*h_ratio)], fill="WHITE", width=2)
            self.draw.line([(x + 15*w_ratio, y + 8*h_ratio), (x + 20*w_ratio, y + 8*h_ratio)], fill="WHITE", width=2)
            self.draw.arc([(x + 7*w_ratio, y + 12*h_ratio), (x + 18*w_ratio, y + 23*h_ratio)], 0, 180, fill="WHITE", width=2)
        elif self.face_state == 4: # Bored
            self.draw.line([(x + 5*w_ratio, y + 8*h_ratio), (x + 10*w_ratio, y + 8*h_ratio)], fill="WHITE", width=1)
            self.draw.line([(x + 15*w_ratio, y + 8*h_ratio), (x + 20*w_ratio, y + 8*h_ratio)], fill="WHITE", width=1)
            self.draw.line([(x + 10*w_ratio, y + 15*h_ratio), (x + 15*w_ratio, y + 15*h_ratio)], fill="WHITE", width=1)
        elif self.face_state == 5: # Excited
            self.draw.ellipse([(x + 3*w_ratio, y + 3*h_ratio), (x + 12*w_ratio, y + 12*h_ratio)], fill="WHITE")
            self.draw.ellipse([(x + 13*w_ratio, y + 3*h_ratio), (x + 22*w_ratio, y + 12*h_ratio)], fill="WHITE")
            self.draw.arc([(x + 7*w_ratio, y + 12*h_ratio), (x + 18*w_ratio, y + 23*h_ratio)], 0, 180, fill="WHITE", width=2)

    def _draw_main_view(self):
        # Draw Pwnagotchi title
        self.draw.text((5, 5), "Pwnagotchi", fill="WHITE", font=self.font_large)
        
        # Draw small face in the corner
        self._draw_face((self.width - 30, 5, 25, 25))

        # Display status
        self.draw.text((5, 30), f"Status: {self.status_message}", fill="WHITE", font=self.font_small)
        self.draw.text((5, 45), f"Handshakes: {self.handshakes_count}", fill="WHITE", font=self.font_small)
        self.draw.text((5, 60), f"Channel: {self.channel}", fill="WHITE", font=self.font_small)
        
        hours, rem = divmod(int(self.uptime), 3600)
        mins, secs = divmod(rem, 60)
        self.draw.text((5, 75), f"Uptime: {hours:02d}:{mins:02d}:{secs:02d}", fill="WHITE", font=self.font_small)

    def _draw_face_view(self):
        # Draw large face in the center
        face_size = 80
        face_box = ((self.width - face_size) // 2, (self.height - face_size) // 2, face_size, face_size)
        self._draw_face(face_box)

        # Update and draw speech bubble
        if self.bubble_timer <= 0:
            self.bubble_text = random.choice(self.sayings)
            self.bubble_timer = self.bubble_duration + random.uniform(-1, 1)

        if self.bubble_text:
            bubble_padding = 5
            _b = self.draw.textbbox((0, 0), self.bubble_text, font=self.font_medium)
            text_width, text_height = _b[2] - _b[0], _b[3] - _b[1]
            
            bubble_x = (self.width - text_width) // 2
            bubble_y = face_box[1] - text_height - bubble_padding * 3
            
            if bubble_y < 0: bubble_y = 5 # Prevent drawing off-screen

            bubble_box = [
                (bubble_x - bubble_padding, bubble_y - bubble_padding),
                (bubble_x + text_width + bubble_padding, bubble_y + text_height + bubble_padding)
            ]
            self.draw.rectangle(bubble_box, fill="BLACK", outline="WHITE", width=1)
            self.draw.text((bubble_x, bubble_y), self.bubble_text, font=self.font_medium, fill="WHITE")
            
            # Draw pointer triangle
            pointer_base_y = bubble_box[1][1]
            self.draw.polygon([
                (bubble_x + 10, pointer_base_y),
                (bubble_x + 20, pointer_base_y),
                (bubble_x + 15, pointer_base_y + 5)
            ], fill="WHITE")

    def _draw_settings_view(self):
        self.draw.text((5, 5), "Settings", fill="WHITE", font=self.font_large)
        
        y_offset = 30
        line_height = 15
        
        for i, key in enumerate(self.settings_options):
            value = self.settings[key]
            
            # Highlight the selected option
            if i == self.settings_cursor:
                self.draw.rectangle([(0, y_offset - 2), (self.width, y_offset + line_height - 2)], fill=(0, 0, 100)) # Dark blue
            
            # Display setting name
            self.draw.text((5, y_offset), key, font=self.font_medium, fill="WHITE")
            
            # Display setting value
            if isinstance(value, bool):
                display_value = "[ON]" if value else "[OFF]"
                fill_color = (0, 255, 0) if value else (255, 0, 0) # Green/Red
            else:
                display_value = str(value)
                fill_color = (255, 255, 0) # Yellow
            
            _b = self.draw.textbbox((0, 0), display_value, font=self.font_medium)
            value_width = _b[2] - _b[0]
            self.draw.text((self.width - value_width - 5, y_offset), display_value, font=self.font_medium, fill=fill_color)

            y_offset += line_height + 5

    def update_display(self):
        self.draw.rectangle((0, 0, self.width, self.height), fill="BLACK") # Clear screen
        
        # Update timers
        current_time = time.time()
        delta = current_time - self.last_update_time
        self.uptime += delta
        self.bubble_timer -= delta
        self.last_update_time = current_time

        if self.view_mode == "face":
            self._draw_face_view()
        elif self.view_mode == "settings":
            self._draw_settings_view()
        else: # "main" view
            self._draw_main_view()

        self.lcd.LCD_ShowImage(self.image, 0, 0)

# --- Pwnagotchi Payload Class ---
class PwnagotchiPayload:
    def __init__(self):
        self.lcd = None
        self.ui = None
        self.monitor_interface = None
        self.bettercap_process = None
        self.running = False
        self.handshakes_captured = 0
        self.current_channel = "N/A"
        self.view_mode = "main" # main, face, settings
        
        # Settings
        self.settings = {
            "Channel Hop": True,
            "Save Handshakes": True,
            "Channels": "2.4GHz" # 2.4GHz or 5GHz
        }
        self.settings_options = list(self.settings.keys())
        self.settings_cursor = 0

        # Debouncing for keys
        self.last_press_time = 0
        self.debounce_delay = 0.3

        # AI Mood attributes
        self.last_ap_seen_time = time.time()

        os.makedirs(PWNAGOTCHI_PCAP_DIR, exist_ok=True)
        os.makedirs(PWNAGOTCHI_HANDSHAKE_DIR, exist_ok=True)
        os.makedirs(PWNAGOTCHI_HASHCAT_DIR, exist_ok=True)

    def _handle_input(self):
        current_time = time.time()
        if (current_time - self.last_press_time) < self.debounce_delay:
            return # Debouncing
        
        if GPIO.input(self.PINS["KEY3"]) == 0:
            self.last_press_time = current_time
            self.running = False # Signal to exit
            return

        if self.view_mode == "main":
            if GPIO.input(self.PINS["KEY1"]) == 0:
                self.last_press_time = current_time
                self.view_mode = "face"
            elif GPIO.input(self.PINS["KEY2"]) == 0:
                self.last_press_time = current_time
                self.view_mode = "settings"
        
        elif self.view_mode == "face":
            if GPIO.input(self.PINS["KEY_PRESS"]) == 0:
                self.last_press_time = current_time
                self.view_mode = "main"

        elif self.view_mode == "settings":
            if GPIO.input(self.PINS["KEY_PRESS"]) == 0:
                self.last_press_time = current_time
                setting_key = self.settings_options[self.settings_cursor]
                
                # Toggle boolean settings
                if isinstance(self.settings[setting_key], bool):
                    self.settings[setting_key] = not self.settings[setting_key]
                    log(f"Toggled setting '{setting_key}' to {self.settings[setting_key]}")
                    self._apply_settings()
                
                # Cycle through string settings
                elif setting_key == "Channels":
                    if self.settings[setting_key] == "2.4GHz":
                        self.settings[setting_key] = "5GHz"
                    else:
                        self.settings[setting_key] = "2.4GHz"
                    log(f"Cycled setting '{setting_key}' to {self.settings[setting_key]}")
                    self._apply_settings()

            elif GPIO.input(self.PINS["KEY_UP"]) == 0:
                self.last_press_time = current_time
                self.settings_cursor = (self.settings_cursor - 1) % len(self.settings_options)
            
            elif GPIO.input(self.PINS["KEY_DOWN"]) == 0:
                self.last_press_time = current_time
                self.settings_cursor = (self.settings_cursor + 1) % len(self.settings_options)

            elif GPIO.input(self.PINS["KEY2"]) == 0: # Use KEY2 to exit settings
                self.last_press_time = current_time
                self.view_mode = "main"

    def _check_bettercap(self):
        log("Checking for bettercap installation...")
        try:
            subprocess.run(['which', 'bettercap'], check=True, capture_output=True)
            log("bettercap found.")
            return True
        except subprocess.CalledProcessError:
            log("bettercap not found. Please install bettercap to use this payload.")
            return False
        except FileNotFoundError:
            log("bettercap command not found. Please install bettercap to use this payload.")
            return False

    def _init_lcd(self):
        if not LCD_AVAILABLE:
            log("LCD modules not available. Running headless.")
            return False
        
        log("Initializing LCD...")
        try:
            LCD_Config.GPIO_Init()
            self.lcd = LCD_1in44.LCD()
            self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
            self.lcd.LCD_Clear()
            self.ui = PwnagotchiUI(self.lcd)
            log("LCD initialized successfully.")
            return True
        except Exception as e:
            log(f"Failed to initialize LCD: {e}")
            return False

    def _init_gpio(self):
        log("Initializing GPIO for keys...")
        try:
            # Pin definitions
            self.PINS = { "KEY_UP": 6, "KEY_DOWN": 19, "KEY_LEFT": 5, "KEY_RIGHT": 26, "KEY_PRESS": 13, "KEY1": 21, "KEY2": 20, "KEY3": 16 }
            GPIO.setmode(GPIO.BCM)
            for pin in self.PINS.values():
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            log("GPIO initialized successfully.")
            return True
        except Exception as e:
            log(f"Failed to initialize GPIO: {e}")
            return False

    def _cleanup(self):
        log("Cleaning up Pwnagotchi payload...")
        self.running = False
        
        if self.bettercap_process:
            log("Terminating bettercap process...")
            self.bettercap_process.terminate()
            try:
                self.bettercap_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log("bettercap did not terminate, killing...")
                self.bettercap_process.kill()
            self.bettercap_process = None

        if self.monitor_interface:
            log(f"Deactivating monitor mode on {self.monitor_interface}...")
            try:
                monitor_mode_helper.deactivate_monitor_mode(self.monitor_interface)
            except Exception as e:
                log(f"Error deactivating monitor mode: {e}")
            self.monitor_interface = None

        if self.lcd:
            log("Clearing LCD and cleaning up GPIO...")
            try:
                self.lcd.LCD_Clear()
                GPIO.cleanup()
            except Exception as e:
                log(f"Error during LCD cleanup: {e}")
            self.lcd = None
            self.ui = None
        
        log("Cleanup complete.")

    def _generate_caplet(self):
        log("Generating new bettercap caplet from settings...")
        
        commands = [
            "set events.stream.output off",
            "set ui.update.interval 1s",
            "set wifi.show.uptime true",
            "set wifi.recon.interval 5s"
        ]

        # Apply dynamic settings
        if self.settings["Channel Hop"]:
            commands.append("set wifi.recon.channel hop")
            if self.settings["Channels"] == "2.4GHz":
                commands.append("set wifi.recon.channels 1,6,11")
            elif self.settings["Channels"] == "5GHz":
                commands.append("set wifi.recon.channels 36,40,44,48,149,153,157,161")
        else:
            channel = self.current_channel if self.current_channel != 'N/A' else '1'
            commands.append(f"set wifi.recon.channel {channel}")

        if self.settings["Save Handshakes"]:
            commands.append(f"set wifi.handshakes.file {PWNAGOTCHI_PCAP_DIR}/bettercap_handshakes.pcap")
            commands.append("wifi.handshakes on")
        
        commands.append("wifi.recon on")
        
        caplet_content = "\\n".join(commands)
        log(f"Generated Caplet:\\n{caplet_content}")
        return caplet_content

    def _start_bettercap(self, caplet_content):
        log(f"Starting bettercap on {self.monitor_interface}...")
        
        caplet_path = "/tmp/pwnagotchi.cap"
        try:
            with open(caplet_path, "w") as f:
                f.write(caplet_content)
            log(f"Wrote bettercap caplet to {caplet_path}")
        except Exception as e:
            log(f"Failed to create bettercap caplet: {e}")
            return False

        try:
            # Start bettercap with the caplet in a non-interactive way
            self.bettercap_process = subprocess.Popen(
                ['bettercap', '-iface', self.monitor_interface, '-caplet', caplet_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1, # Line-buffered output
                universal_newlines=True
            )
            log(f"bettercap started with PID {self.bettercap_process.pid}")
            
            # Start a thread to read bettercap's output
            threading.Thread(target=self._read_bettercap_output, daemon=True).start()
            
            return True
        except FileNotFoundError:
            log("bettercap command not found. Please ensure it's installed and in your PATH.")
            return False
        except Exception as e:
            log(f"Failed to start bettercap: {e}")
            return False

    def _apply_settings(self):
        log("Applying new settings and restarting bettercap...")
        
        # Stop current bettercap process
        if self.bettercap_process:
            log("Terminating bettercap process for restart...")
            self.bettercap_process.terminate()
            try:
                self.bettercap_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log("bettercap did not terminate, killing...")
                self.bettercap_process.kill()
            self.bettercap_process = None
            # Give a moment for the process to die
            time.sleep(1)

        # Generate new caplet and restart
        new_caplet = self._generate_caplet()
        if not self._start_bettercap(new_caplet):
            log("Failed to restart bettercap with new settings!")
            if self.ui:
                self.ui.status_message = "Restart failed!"
                self.ui.face_state = 2
        else:
            log("bettercap restarted successfully with new settings.")
            if self.ui:
                self.ui.status_message = "Settings applied!"

    def _update_ai_mood(self):
        # Check for boredom
        if time.time() - self.last_ap_seen_time > 30: # 30 seconds of no new APs
            if self.ui and self.ui.face_state not in [3, 2]: # Don't get bored if sad or pwned
                self.ui.face_state = 4 # Bored
                self.ui.status_message = "Bored..."


    def _read_bettercap_output(self):
        log("Starting bettercap output reader thread...")
        try:
            for line in iter(self.bettercap_process.stdout.readline, ''):
                if not self.running: # Exit thread if payload is stopping
                    break
                log(f"[BETTERCAP] {line.strip()}")
                # Parse bettercap output for handshakes, channel changes, etc.
                if "full handshake captured" in line or "PMKID captured" in line:
                    self.handshakes_captured += 1
                    if self.ui:
                        self.ui.face_state = 3 # Pwned face
                        self.ui.status_message = "Handshake!"
                    log(f"Handshake detected! Total: {self.handshakes_captured}")
                elif "hopping on channel" in line:
                    match = re.search(r'hopping on channel (\\d+)', line)
                    if match:
                        self.current_channel = match.group(1)
                        if self.ui:
                            self.ui.channel = self.current_channel
                            self.ui.face_state = 0 # Neutral face
                
                # Update UI status based on bettercap output
                if "wifi.recon.started" in line and self.ui:
                    self.ui.status_message = "Reconnaissance"
                elif "wifi.client.new" in line and self.ui:
                    self.ui.face_state = 1 # Happy face for new client
                elif "wifi.ap.new" in line and self.ui:
                    self.ui.face_state = 5 # Excited face
                    self.last_ap_seen_time = time.time()
        except Exception as e:
            log(f"Error reading bettercap output: {e}")
        finally:
            log("Bettercap output reader thread finished.")

    def _process_pcap_files(self):
        if not SCAPY_AVAILABLE:
            log("Scapy not available, cannot process pcap files.")
            return

        source_pcap = os.path.join(PWNAGOTCHI_PCAP_DIR, "bettercap_handshakes.pcap")
        if not os.path.exists(source_pcap) or os.path.getsize(source_pcap) == 0:
            return

        # Move the source file to a temporary location for processing.
        # This is an atomic operation and prevents reprocessing.
        processing_pcap = os.path.join(PWNAGOTCHI_PCAP_DIR, f"processing_{int(time.time())}.pcap")
        try:
            os.rename(source_pcap, processing_pcap)
            log(f"Moved {source_pcap} to {processing_pcap} for processing.")
        except Exception as e:
            log(f"Error renaming pcap file for processing: {e}")
            return

        try:
            log(f"Scanning {processing_pcap} for EAPOL packets...")
            packets = rdpcap(processing_pcap)
            
            handshake_packets = []
            for packet in packets:
                if packet.haslayer(EAPOL):
                    handshake_packets.append(packet)
            
            if handshake_packets:
                count = len(handshake_packets)
                log(f"Found {count} EAPOL packets.")
                
                # Save the verified handshake packets to a new, permanent file
                final_pcap_name = f"handshake_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pcap"
                final_pcap_path = os.path.join(PWNAGOTCHI_HANDSHAKE_DIR, final_pcap_name)
                
                wrpcap(final_pcap_path, handshake_packets)
                log(f"Saved {count} handshake packets to {final_pcap_path}")

                # --- Convert to hashcat format ---
                if HCXTOOLS_AVAILABLE:
                    hash_file_path = os.path.join(PWNAGOTCHI_HASHCAT_DIR, final_pcap_name.replace('.pcap', '.hc22000'))
                    log(f"Converting {final_pcap_path} to {hash_file_path}...")
                    try:
                        conversion_cmd = ['hcxpcapngtool', '-o', hash_file_path, final_pcap_path]
                        subprocess.run(conversion_cmd, check=True, capture_output=True)
                        log("Conversion successful.")
                        if self.ui: self.ui.status_message = "Converted hash!"
                    except Exception as conv_e:
                        log(f"Handshake conversion failed: {conv_e}")
                # --- End conversion ---

                self.handshakes_captured += 1 # Increment by 1 for each file with handshakes, not each packet
                if self.ui:
                    self.ui.face_state = 3 # Pwned face
                    self.ui.status_message = "Handshake saved!"
            else:
                log("No new EAPOL packets found in this batch.")

        except Exception as e:
            log(f"Error processing pcap file {processing_pcap}: {e}")
        finally:
            # Clean up the processed file
            try:
                log(f"Deleting processed file: {processing_pcap}")
                os.remove(processing_pcap)
            except Exception as e:
                log(f"Error deleting processed file {processing_pcap}: {e}")

    def _check_hcxtools(self):
        global HCXTOOLS_AVAILABLE
        log("Checking for hcxtools installation...")
        try:
            subprocess.run(['which', 'hcxpcapngtool'], check=True, capture_output=True)
            log("hcxtools found.")
            HCXTOOLS_AVAILABLE = True
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            log("hcxpcapngtool not found. Handshake conversion will be disabled.")
            log("To enable, please install 'hcxtools' on your device.")
            HCXTOOLS_AVAILABLE = False
            return False

    def run(self):
        # --- 1. Initialize Core Hardware ---
        if not self._init_gpio() or not self._init_lcd():
            log("Fatal: GPIO or LCD failed to initialize.")
            self._cleanup()
            return

        # --- 2. Perform Dependency Checks ---
        bettercap_ok = self._check_bettercap()
        self._check_hcxtools() # This one is not critical, just sets a flag

        # --- 3. Report Critical Errors on Screen ---
        if not bettercap_ok:
            self.ui.status_message = "bettercap missing!"
            self.ui.face_state = 2 # Sad face
            self.ui.update_display()
            log("bettercap not found. Exiting.")
            time.sleep(5)
            self._cleanup()
            return
        
        if not SCAPY_AVAILABLE:
            self.ui.status_message = "Scapy missing!"
            self.ui.face_state = 2 # Sad face
            self.ui.update_display()
            log("Scapy not found. Exiting.")
            time.sleep(5)
            self._cleanup()
            return

        # --- 4. Proceed with Payload Logic ---
        self.ui.status_message = "Activating monitor mode..."
        self.ui.update_display()

        # Find and activate monitor mode
        potential_interfaces = []
        try:
            for iface in os.listdir("/sys/class/net"):
                if os.path.exists(f"/sys/class/net/{iface}/wireless"):
                    potential_interfaces.append(iface)
            potential_interfaces.sort(key=lambda x: (x != 'wlan1', x != 'wlan0', x))
        except Exception as e:
            log(f"Error detecting potential interfaces: {e}")
        
        if not potential_interfaces:
            self.ui.status_message = "No WiFi interfaces!"
            self.ui.face_state = 2
            self.ui.update_display()
            log("No WiFi interfaces detected. Exiting.")
            time.sleep(5)
            self._cleanup()
            return

        for iface in potential_interfaces:
            log(f"Attempting monitor mode on {iface}...")
            self.monitor_interface = monitor_mode_helper.activate_monitor_mode(iface)
            if self.monitor_interface:
                log(f"Monitor mode activated on {self.monitor_interface}")
                self.ui.status_message = f"Monitor: {self.monitor_interface}"
                self.ui.face_state = 0
                self.ui.update_display()
                break
            else:
                log(f"Failed to activate monitor mode on {iface}")
        
        if not self.monitor_interface:
            self.ui.status_message = "Monitor mode failed!"
            self.ui.face_state = 2
            self.ui.update_display()
            log("Failed to activate monitor mode on any interface. Exiting.")
            time.sleep(5)
            self._cleanup()
            return

        # Generate the initial caplet and start bettercap
        initial_caplet = self._generate_caplet()
        if not self._start_bettercap(initial_caplet):
            self.ui.status_message = "bettercap failed!"
            self.ui.face_state = 2
            self.ui.update_display()
            log("Failed to start bettercap. Exiting.")
            time.sleep(5)
            self._cleanup()
            return

        self.running = True
        self.ui.status_message = "Pwnagotchi running!"
        self.ui.update_display()

        # Main loop
        try:
            last_pcap_process_time = time.time()
            while self.running:
                self._handle_input()
                self._update_ai_mood()
                
                # Pass current state to the UI object for drawing
                self.ui.view_mode = self.view_mode
                self.ui.handshakes_count = self.handshakes_captured
                self.ui.channel = self.current_channel
                self.ui.settings = self.settings
                self.ui.settings_options = self.settings_options
                self.ui.settings_cursor = self.settings_cursor
                self.ui.update_display()
                
                # Periodically process pcap files
                if time.time() - last_pcap_process_time > 10:
                    self._process_pcap_files()
                    last_pcap_process_time = time.time()
                
                time.sleep(0.1) # Short sleep for responsiveness

        except KeyboardInterrupt:
            log("KeyboardInterrupt detected.")
        finally:
            self._cleanup()

if __name__ == "__main__":
    payload = PwnagotchiPayload()
    payload.run()
