import sys, os, time, subprocess

# This script is OPTIONAL. Run it if you want to add Navarro, DNSSpoof, and Screensaver
# to your working KTOX_Pi menu. It will back up your ktox_device.py first.

path = "/root/KTOx/ktox_device.py"
if not os.path.exists(path):
    path = "ktox_device.py"  # Local check
if not os.path.exists(path):
    path = "/root/KTOx/ktox_pi/ktox_device.py"  # Legacy location
if not os.path.exists(path):
    path = "ktox_pi/ktox_device.py"  # Legacy local check

if not os.path.exists(path):
    print(f"Error: Could not find {path}")
    sys.exit(1)

print(f"Backing up {path} to {path}.bak...")
os.system(f"cp {path} {path}.bak")

with open(path, "r") as f:
    content = f.read()

# 1. Add new menu items to the tree
if 'self.tree = {' in content and '"nav":' not in content:
    print("Adding Navarro and DNSSpoof to menu tree...")
    new_tree = """self.tree = {
            "nav": (
                ("Scan Network", self._nav_scan),
                ("Scan Ports",   self._nav_ports),
                ("Reports",      self._nav_reports),
                ("Back",         "home"),
            ),
            "dns": (
                ("Start Spoof",  self._dns_start),
                ("Stop Spoof",   self._dns_stop),
                ("Back",         "home"),
            ),"""
    content = content.replace('self.tree = {', new_tree)

# 2. Add to home menu
if '"sys": ("System", "sys"),' in content and '"nav":' not in content:
    print("Adding Navarro and DNSSpoof to home menu...")
    new_home = '"nav": ("Navarro Recon", "nav"),\n            "dns": ("DNSSpoof", "dns"),\n            "sys": ("System", "sys"),'
    content = content.replace('"sys": ("System", "sys"),', new_home)

# 3. Add methods
if 'def home_loop(self):' in content and 'def _nav_scan' not in content:
    print("Adding new menu methods...")
    methods = """
    # ── Navarro Recon ──────────────────────────────────────────────────────────
    def _nav_scan(self):
        exec_payload("Navarro/navarro_scan.py")
    def _nav_ports(self):
        exec_payload("Navarro/navarro_ports.py")
    def _nav_reports(self):
        self._browse_dir(KTOX_DIR + "/Navarro/reports", "Navarro Reports")

    # ── DNSSpoof ───────────────────────────────────────────────────────────────
    def _dns_start(self):
        exec_payload("DNSSpoof/dns_spoof.py")
    def _dns_stop(self):
        # Using a safe way to stop the process
        os.system("ps aux | grep dns_spoof.py | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null")
        Dialog_info("DNS Spoof stopped", wait=False, timeout=1)
"""
    content = content.replace('def home_loop(self):', methods + "\n    def home_loop(self):")

with open(path, "w") as f:
    f.write(content)

print("Update complete! Please restart your KTOX_Pi service.")
