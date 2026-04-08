#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_config.py — KTOx Session Configuration v1.0
#
# Saves and restores session settings across runs:
#   · Interface, gateway, attacker IP
#   · Stealth profile preference
#   · Last-used targets and module preferences
#   · Host notes (annotate discovered devices)

import os, json, re
from datetime import datetime
from pathlib import Path

CONFIG_PATH = os.path.expanduser("~/.ktox/config.json")
NOTES_PATH  = os.path.expanduser("~/.ktox/host_notes.json")
DEFAULTS = {
    "interface":      "",
    "gateway_ip":     "",
    "gateway_mac":    "",
    "attacker_ip":    "",
    "stealth_profile":"off",
    "loot_dir":       "ktox_loot",
    "scan_timeout":   3,
    "auto_scan":      False,
    "theme":          "blood",
    "last_updated":   "",
}


class KTOxConfig:
    """
    Persistent configuration manager.
    Reads from ~/.ktox/config.json on startup.
    Saves on exit or explicit save() call.
    """

    def __init__(self):
        self._cfg   = dict(DEFAULTS)
        self._notes = {}   # ip → note string
        self._dirty = False
        self._load()

    def _load(self):
        """Load config from disk."""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)

        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    saved = json.load(f)
                # Merge with defaults so new keys always exist
                self._cfg.update(saved)
            except Exception:
                pass

        if os.path.exists(NOTES_PATH):
            try:
                with open(NOTES_PATH) as f:
                    self._notes = json.load(f)
            except: pass

    def save(self):
        """Write config to disk."""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        self._cfg["last_updated"] = datetime.now().isoformat()
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(self._cfg, f, indent=2)
            with open(NOTES_PATH, "w") as f:
                json.dump(self._notes, f, indent=2)
            self._dirty = False
            return True
        except Exception as e:
            return False

    # ── Getters / Setters ───────────────────────────────────────────────
    def get(self, key, default=None):
        return self._cfg.get(key, default)

    def set(self, key, value):
        if key in self._cfg or key in DEFAULTS:
            self._cfg[key] = value
            self._dirty = True
        else:
            raise KeyError(f"Unknown config key: {key}")

    def update_from_session(self, iface=None, gateway_ip=None,
                            gateway_mac=None, attacker_ip=None,
                            stealth=None):
        """Called after interface setup to persist discovered values."""
        if iface:        self._cfg["interface"]   = iface
        if gateway_ip:   self._cfg["gateway_ip"]  = gateway_ip
        if gateway_mac:  self._cfg["gateway_mac"] = gateway_mac
        if attacker_ip:  self._cfg["attacker_ip"] = attacker_ip
        if stealth:      self._cfg["stealth_profile"] = stealth
        self._dirty = True

    # ── Host Notes ──────────────────────────────────────────────────────
    def add_note(self, ip, note):
        """Annotate a host with a note."""
        self._notes[ip] = {
            "note": note,
            "ts":   datetime.now().isoformat()
        }
        self._dirty = True

    def get_note(self, ip):
        """Get the note for a host, or empty string."""
        entry = self._notes.get(ip)
        return entry["note"] if entry else ""

    def all_notes(self):
        return dict(self._notes)

    def delete_note(self, ip):
        self._notes.pop(ip, None)
        self._dirty = True

    # ── Convenience properties ──────────────────────────────────────────
    @property
    def interface(self):   return self._cfg.get("interface", "")
    @property
    def gateway_ip(self):  return self._cfg.get("gateway_ip", "")
    @property
    def gateway_mac(self): return self._cfg.get("gateway_mac", "")
    @property
    def attacker_ip(self): return self._cfg.get("attacker_ip", "")
    @property
    def stealth(self):     return self._cfg.get("stealth_profile", "off")
    @property
    def loot_dir(self):    return self._cfg.get("loot_dir", "ktox_loot")
    @property
    def auto_scan(self):   return self._cfg.get("auto_scan", False)

    def __repr__(self):
        return f"<KTOxConfig {self._cfg}>"

    def show(self):
        """Print current config in a formatted table."""
        try:
            from rich.console import Console
            from rich.table   import Table
            from rich         import box
            con = Console(highlight=False)
            table = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
            table.add_column("key",   style="#922B21", width=20)
            table.add_column("value", style="#F2F3F4")
            for k, v in sorted(self._cfg.items()):
                table.add_row(k, str(v))
            con.print(table)
        except ImportError:
            for k, v in sorted(self._cfg.items()):
                print(f"  {k:22s} = {v}")


# ── Global singleton ──────────────────────────────────────────────────────────
_config = None

def get_config() -> KTOxConfig:
    global _config
    if _config is None:
        _config = KTOxConfig()
    return _config
