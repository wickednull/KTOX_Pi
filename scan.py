#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# scan.py

"""
Copyright (C) 2017-18 Nikolaos Kamarinakis (nikolaskam@gmail.com) & David Schütz (xdavid@protonmail.com)
See License at nikolaskama.me (https://nikolaskama.me/kickthemoutproject)

Extended by wickednull — extracts vendor and hostname from nmap output
"""

import nmap, subprocess, re

def _arp_table():
    """
    Read the OS ARP table to get MAC addresses for hosts that nmap may miss.
    Returns dict: {ip: mac}
    """
    macs = {}
    try:
        out = subprocess.check_output(["arp", "-an"], text=True, timeout=3)
        for line in out.splitlines():
            parts = line.split()
            try:
                ip  = parts[1].strip("()")
                mac = parts[3]
                if mac and mac != "<incomplete>" and ":" in mac:
                    macs[ip] = mac.lower()
            except IndexError:
                pass
    except Exception:
        pass
    return macs


def scanNetwork(network):
    """
    Scan the network and return a list of:
        [ip, mac, vendor, hostname]

    nmap -sn already does ARP ping, OUI vendor lookup, and PTR hostname
    resolution — we extract all four fields from its output rather than
    doing them again separately.

    Falls back to the OS ARP table for MACs that nmap misses (e.g. the
    scanning host itself, or hosts that respond to ARP but not to nmap probes).
    """
    returnlist = []
    nm = nmap.PortScanner()

    try:
        result = nm.scan(hosts=network, arguments="-sn")
    except Exception:
        return returnlist

    # Build ARP table fallback
    arp_cache = _arp_table()

    for k, v in result.get("scan", {}).items():
        if str(v.get("status", {}).get("state", "")) != "up":
            continue

        addrs = v.get("addresses", {})
        ip    = str(addrs.get("ipv4", k))
        if not ip:
            continue

        # MAC — from nmap output first, then ARP table fallback
        mac = str(addrs.get("mac", "")).lower()
        if not mac and ip in arp_cache:
            mac = arp_cache[ip]

        # Vendor — nmap does OUI lookup and puts it in v['vendor']
        # Format: {'b8:27:eb:74:f2:6c': 'Raspberry Pi Trading'}
        vendor = ""
        vendor_dict = v.get("vendor", {})
        if vendor_dict:
            vendor = list(vendor_dict.values())[0]
        # Trim long vendor strings
        if vendor and len(vendor) > 20:
            vendor = vendor[:20]

        # Hostname — nmap does PTR lookup and puts it in v['hostnames']
        # Format: [{'name': 'router.lan', 'type': 'PTR'}]
        hostname = ""
        for h in v.get("hostnames", []):
            name = h.get("name", "")
            if name and name != ip:
                hostname = name[:24]
                break

        returnlist.append([ip, mac, vendor, hostname])

    return returnlist
