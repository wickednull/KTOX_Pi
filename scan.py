#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scan.py – KTOx network discovery (hardened for ARP attacks)

import subprocess
import re
import sys
from typing import List, Tuple, Optional

# Optional nmap – if not present, fallback to arp-scan
try:
    import nmap
    HAS_NMAP = True
except ImportError:
    HAS_NMAP = False
    print("[scan] python3-nmap not installed, using arp-scan fallback", file=sys.stderr)

def _arp_table() -> dict:
    """
    Read OS ARP cache. Returns dict {ip: mac}.
    Handles `arp -an` output differences (Kali vs others).
    """
    macs = {}
    try:
        out = subprocess.check_output(["arp", "-an"], text=True, timeout=3)
        # Example lines:
        #   ? (192.168.1.1) at 11:22:33:44:55:66 [ether] on eth0
        #   ? (192.168.1.2) at <incomplete> on eth0
        for line in out.splitlines():
            ip_match = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)', line)
            mac_match = re.search(r'at ([0-9a-fA-F:]{17})', line)
            if ip_match and mac_match:
                ip = ip_match.group(1)
                mac = mac_match.group(1).lower()
                macs[ip] = mac
    except Exception:
        pass
    return macs

def scanNetwork(network: str, timeout_sec: int = 5) -> List[List[str]]:
    """
    Scan the network and return list of [ip, mac, vendor, hostname].
    Uses nmap -sn if available, else arp-scan.
    """
    results = []
    arp_cache = _arp_table()

    if HAS_NMAP:
        try:
            nm = nmap.PortScanner()
            # -sn: ping scan (no port scan), --send-ip forces ARP on local net
            # time to live limited by timeout
            nm.scan(hosts=network, arguments=f"-sn --send-ip --host-timeout {timeout_sec}s")
        except Exception as e:
            print(f"[scan] nmap error: {e}, falling back to arp-scan", file=sys.stderr)
            return _arp_scan_fallback(network, arp_cache)

        for ip, info in nm.get('scan', {}).items():
            if info.get('status', {}).get('state') != 'up':
                continue

            addrs = info.get('addresses', {})
            ip_addr = addrs.get('ipv4', ip)
            if not ip_addr:
                continue

            # MAC from nmap first, else from system ARP cache
            mac = addrs.get('mac', '').lower()
            if not mac and ip_addr in arp_cache:
                mac = arp_cache[ip_addr]

            # Vendor (OUI lookup) – nmap stores in info['vendor']
            vendor = ''
            vendor_dict = info.get('vendor', {})
            if vendor_dict:
                vendor = list(vendor_dict.values())[0][:20]

            # Hostname from PTR record
            hostname = ''
            for h in info.get('hostnames', []):
                name = h.get('name', '')
                if name and name != ip_addr and '.' in name:
                    hostname = name[:24]
                    break

            results.append([ip_addr, mac, vendor, hostname])

    else:
        # Fallback to arp-scan (fast, no nmap)
        results = _arp_scan_fallback(network, arp_cache)

    return results

def _arp_scan_fallback(network: str, arp_cache: dict) -> List[List[str]]:
    """
    Use `arp-scan` if available; otherwise use `ping -c1` + ARP cache.
    Returns same list format.
    """
    results = []
    try:
        # arp-scan is more reliable than nmap for pure ARP
        out = subprocess.check_output(
            ["arp-scan", "--localnet", "--numeric"],
            text=True, timeout=10
        )
        # Parse lines like: 192.168.1.1	11:22:33:44:55:66	VendorName
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and re.match(r'\d+\.\d+\.\d+\.\d+', parts[0]):
                ip = parts[0]
                mac = parts[1].lower() if len(parts) > 1 else ''
                vendor = parts[2] if len(parts) > 2 else ''
                if mac and ':' in mac:
                    results.append([ip, mac, vendor[:20], ''])
    except (subprocess.CalledProcessError, FileNotFoundError):
        # No arp-scan – brute force ping sweep
        base = network.rsplit('.', 1)[0] if '.' in network else '192.168.1'
        for i in range(1, 255):
            ip = f"{base}.{i}"
            try:
                subprocess.run(["ping", "-c", "1", "-W", "1", ip],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=2)
                # If ping succeeds, try to get MAC from ARP cache
                mac = arp_cache.get(ip, '')
                if mac:
                    results.append([ip, mac, '', ''])
            except:
                pass
    return results

# Optional: direct test
if __name__ == "__main__":
    import sys
    net = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.0/24"
    hosts = scanNetwork(net)
    for h in hosts:
        print(f"{h[0]}  {h[1]}  {h[2]}  {h[3]}")
