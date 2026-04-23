#!/usr/bin/env python3
"""Central network-interface role and monitor-mode manager for KTOx."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from ktox_config import CONTROL_INTERFACE
from wifi.monitor_mode_helper import (
    activate_monitor_mode,
    deactivate_monitor_mode,
    find_monitor_capable_interface,
)


@dataclass
class InterfaceRoles:
    control: str = "wlan0"
    attack: str = ""


class InterfaceManager:
    """Assign control/attack roles and guard monitor-mode operations."""

    def __init__(self, preferred_control: str = CONTROL_INTERFACE):
        self.preferred_control = preferred_control
        self.roles = InterfaceRoles(control=preferred_control, attack="")
        self.monitor_iface: str | None = None
        self.refresh_roles()

    def _wireless_interfaces(self) -> list[str]:
        try:
            names = [n for n in sorted(os.listdir("/sys/class/net")) if n != "lo"]
            return [n for n in names if os.path.isdir(f"/sys/class/net/{n}/wireless")]
        except Exception:
            return []

    def refresh_roles(self) -> InterfaceRoles:
        wireless = self._wireless_interfaces()
        control = self.preferred_control if self.preferred_control in wireless else (wireless[0] if wireless else self.preferred_control)

        attack = find_monitor_capable_interface() or ""
        if attack == control:
            attack = next((i for i in wireless if i != control), "")

        self.roles = InterfaceRoles(control=control, attack=attack)
        return self.roles

    def get_roles(self) -> InterfaceRoles:
        return self.refresh_roles()

    def get_webui_interfaces(self) -> list[str]:
        """Interfaces that are safe for WebUI binding."""
        roles = self.get_roles()
        out: list[str] = ["eth0", "tailscale0"]
        if roles.control:
            out.insert(0, roles.control)
        # preserve order, remove duplicates
        seen = set()
        return [i for i in out if not (i in seen or seen.add(i))]

    def start_monitor_mode(self, attack_iface: str | None = None) -> str | None:
        roles = self.get_roles()
        target = (attack_iface or roles.attack or "").strip()
        if not target:
            return None
        if target == roles.control:
            return None

        mon = activate_monitor_mode(target)
        if mon:
            self.monitor_iface = mon
        return mon

    def stop_monitor_mode(self, monitor_iface: str | None = None) -> bool:
        iface = (monitor_iface or self.monitor_iface or "").strip()
        if not iface:
            return True
        ok = deactivate_monitor_mode(iface)
        if ok:
            self.monitor_iface = None
        return ok

    def recover_network(self) -> None:
        """Best-effort bring network services back after monitor sessions."""
        for svc in ("wpa_supplicant", "NetworkManager"):
            subprocess.run(["systemctl", "start", svc], capture_output=True, text=True)
