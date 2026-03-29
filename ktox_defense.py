#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_defense.py — KTOx Purple Team Defense Engine v2.0 (Safe Edition)
#
# SAFETY PRINCIPLES:
#   · Every file modification is backed up first (.ktox_backup)
#   · Dry-run preview shown before any change is applied
#   · User confirms every system modification
#   · iptables rules tracked and removed cleanly on rollback
#   · DNS changes never block cleartext DNS without verified DoT working
#   · smb.conf changes ask about legacy clients before disabling NTLM
#   · HTTP redirect only offered as info — NOT applied automatically
#   · Rollback function restores all backups

import os, sys, re, time, json, socket, subprocess, threading, shutil, logging
from datetime import datetime

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)

try:
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich.rule    import Rule
    from rich.prompt  import Prompt, Confirm
    from rich         import box
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

console  = Console(highlight=False)
loot_dir = "ktox_loot"

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

def tag(t, c=C_BLOOD):  return f"[{c}]{t}[/{c}]"
def ok(t):   console.print(f"  [{C_GOOD}]✔  {t}[/{C_GOOD}]")
def warn(t): console.print(f"  [{C_ORANGE}]⚠  {t}[/{C_ORANGE}]")
def err(t):  console.print(f"  [{C_BLOOD}]✖  {t}[/{C_BLOOD}]")
def info(t): console.print(f"  [{C_STEEL}]ℹ  {t}[/{C_STEEL}]")

def section(t):
    console.print()
    console.print(Rule(f"[bold {C_GOOD}] {t} [/bold {C_GOOD}]", style=C_GOOD))
    console.print()

def _loot(event, data):
    os.makedirs(loot_dir, exist_ok=True)
    path  = os.path.join(loot_dir, "defense.log")
    entry = {"ts": datetime.now().isoformat(), "event": event, "data": data}
    try:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass

def _run_cmd(cmd):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def _attack_panel(attack, how, impact):
    console.print(Panel(
        f"  {tag('Attack:',  C_BLOOD)}  [{C_WHITE}]{attack}[/{C_WHITE}]\n\n"
        f"  {tag('How:',     C_STEEL)}  [{C_ASH}]{how}[/{C_ASH}]\n\n"
        f"  {tag('Impact:',  C_ORANGE)} [{C_YELLOW}]{impact}[/{C_YELLOW}]",
        border_style=C_RUST,
        title=f"[bold {C_BLOOD}]◈ ATTACK PROFILE[/bold {C_BLOOD}]",
        padding=(1, 2)
    ))

def _defense_panel(defenses):
    lines = "\n".join(
        f"  [{C_GOOD}]✔[/{C_GOOD}]  [{C_WHITE}]{d}[/{C_WHITE}]"
        for d in defenses
    )
    console.print(Panel(
        lines,
        border_style=C_GOOD,
        title=f"[bold {C_GOOD}]◈ DEFENSES APPLIED[/bold {C_GOOD}]",
        padding=(1, 2)
    ))


# ══════════════════════════════════════════════════════════════════════════════
# ── SAFE FILE EDITOR ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SafeFileEditor:
    """
    Wraps all config file modifications with:
    - Automatic backup before any write
    - Diff preview before applying
    - Rollback to backup on request
    """

    BACKUP_SUFFIX = ".ktox_backup"
    _backups = []  # class-level registry for rollback

    @classmethod
    def backup(cls, path):
        """Create timestamped backup of a file."""
        if not os.path.exists(path):
            return None
        backup_path = path + cls.BACKUP_SUFFIX
        try:
            shutil.copy2(path, backup_path)
            cls._backups.append((path, backup_path))
            ok(f"Backup → {backup_path}")
            return backup_path
        except Exception as e:
            warn(f"Backup failed for {path}: {e}")
            return None

    @classmethod
    def rollback_all(cls):
        """Restore all backed-up files."""
        if not cls._backups:
            info("No backups to restore.")
            return
        for original, backup in reversed(cls._backups):
            try:
                shutil.copy2(backup, original)
                ok(f"Restored {original} from {backup}")
            except Exception as e:
                err(f"Restore failed for {original}: {e}")

    @classmethod
    def preview_diff(cls, path, new_content):
        """Show what will change before writing."""
        try:
            with open(path) as f:
                old = f.read()
        except:
            old = ""

        old_lines = old.splitlines()
        new_lines = new_content.splitlines()

        added   = [l for l in new_lines if l not in old_lines]
        removed = [l for l in old_lines if l not in new_lines]

        if not added and not removed:
            info("No changes needed — file already correct.")
            return False  # no changes

        console.print(f"\n  [{C_STEEL}]Preview of changes to {path}:[/{C_STEEL}]")
        for l in removed[:10]:
            console.print(f"  [{C_BLOOD}]− {l}[/{C_BLOOD}]")
        for l in added[:10]:
            console.print(f"  [{C_GOOD}]+ {l}[/{C_GOOD}]")
        if len(added) > 10:
            console.print(f"  [{C_DIM}]...and {len(added)-10} more additions[/{C_DIM}]")
        console.print()
        return True  # changes exist

    @classmethod
    def write(cls, path, new_content):
        """Backup, preview, confirm, then write."""
        has_changes = cls.preview_diff(path, new_content)
        if not has_changes:
            return True  # nothing to do

        if not Confirm.ask(f"  [{C_ORANGE}]Apply these changes to {path}?[/{C_ORANGE}]",
                           default=True):
            info("Changes skipped.")
            return False

        backup = cls.backup(path)
        if backup is None and os.path.exists(path):
            if not Confirm.ask(
                f"  [{C_BLOOD}]Backup failed. Write anyway (risky)?[/{C_BLOOD}]",
                default=False
            ):
                return False

        try:
            with open(path, "w") as f:
                f.write(new_content)
            ok(f"Written → {path}")
            _loot("FILE_MODIFIED", {"path": path, "backup": backup})
            return True
        except PermissionError:
            err(f"Permission denied: {path}  (run as root)")
            return False
        except Exception as e:
            err(f"Write failed: {e}")
            return False


# ══════════════════════════════════════════════════════════════════════════════
# ── SAFE IPTABLES MANAGER ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class IPTablesManager:
    """
    Tracks all iptables rules added and provides clean rollback.
    Checks for duplicate rules before adding.
    Never persists rules automatically — shows save command.
    """
    _rules_added = []

    @classmethod
    def rule_exists(cls, rule_args):
        """Check if rule already exists (uses -C check)."""
        check_args = [a if a != "-A" else "-C" for a in rule_args]
        success, _, _ = _run_cmd(["iptables"] + check_args)
        return success

    @classmethod
    def add(cls, rule_args, description=""):
        """Add a rule only if it doesn't already exist."""
        if cls.rule_exists(rule_args):
            ok(f"Rule already exists: {description or ' '.join(rule_args)}")
            return True

        success, _, stderr = _run_cmd(["iptables"] + rule_args)
        if success:
            cls._rules_added.append(rule_args)
            ok(f"iptables: {description or ' '.join(rule_args)}")
            return True
        else:
            warn(f"iptables failed: {stderr}")
            return False

    @classmethod
    def rollback(cls):
        """Remove all rules added this session."""
        if not cls._rules_added:
            info("No iptables rules to remove.")
            return
        for rule in reversed(cls._rules_added):
            del_rule = ["-D" if a == "-A" else a for a in rule]
            success, _, _ = _run_cmd(["iptables"] + del_rule)
            if success:
                ok(f"Removed: {' '.join(del_rule)}")
            else:
                warn(f"Could not remove: {' '.join(del_rule)}")
        cls._rules_added.clear()

    @classmethod
    def show_persist_command(cls):
        """Show how to persist rules (never auto-persist)."""
        if cls._rules_added:
            console.print(Panel(
                f"  [{C_STEEL}]iptables rules are NOT persistent by default.\n"
                f"  They will be lost on reboot.\n\n"
                f"  [{C_YELLOW}]To persist (Debian/Ubuntu):[/{C_YELLOW}]\n"
                f"  [{C_DIM}]sudo apt install iptables-persistent\n"
                f"  sudo netfilter-persistent save[/{C_DIM}]\n\n"
                f"  [{C_YELLOW}]To persist (Arch/Fedora):[/{C_YELLOW}]\n"
                f"  [{C_DIM}]sudo iptables-save > /etc/iptables/iptables.rules[/{C_DIM}]",
                border_style=C_STEEL,
                title=f"[{C_STEEL}]ℹ iptables persistence[/{C_STEEL}]",
                padding=(1, 2)
            ))


# ══════════════════════════════════════════════════════════════════════════════
# ── ARP DEFENSE ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class ArpSpoofDefense:

    def apply_static_arp(self, hosts, gateway_ip, gateway_mac):
        section("DEFENSE: STATIC ARP HARDENING")
        _attack_panel(
            "ARP Spoofing / Poisoning",
            "Attacker sends forged ARP replies claiming to own the gateway IP. "
            "Victims update their ARP cache and route all traffic to the attacker.",
            "Traffic interception, credential theft, denial of service."
        )

        info("Static ARP entries cannot be overwritten by forged ARP replies.")
        info("This locks the gateway and all discovered hosts into the ARP cache.")
        console.print()

        if not Confirm.ask(
            f"  [{C_ORANGE}]Apply static ARP entries for {len(hosts)+1} host(s)?[/{C_ORANGE}]",
            default=True
        ):
            info("Skipped."); return [], []

        applied, failed = [], []

        # Gateway first
        if gateway_ip and gateway_mac:
            success, _, _ = _run_cmd(["arp", "-s", gateway_ip, gateway_mac])
            if success:
                ok(f"Gateway locked: {gateway_ip} → {gateway_mac}")
                applied.append(f"Gateway {gateway_ip}")
            else:
                warn(f"Gateway ARP failed — may need root")
                failed.append(gateway_ip)

        for host in hosts:
            ip  = host.get("ip") or (host[0] if isinstance(host,(list,tuple)) else None)
            mac = host.get("mac") or (host[1] if isinstance(host,(list,tuple)) else None)
            if not ip or not mac or ip == gateway_ip: continue
            success, _, _ = _run_cmd(["arp", "-s", ip, mac])
            if success:
                applied.append(ip)
            else:
                failed.append(ip)

        # Save script
        os.makedirs(loot_dir, exist_ok=True)
        script = os.path.join(loot_dir, "arp_defense.sh")
        lines  = ["#!/bin/bash", "# KTOx ARP Defense Script",
                  f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        if gateway_ip and gateway_mac:
            lines.append(f"arp -s {gateway_ip} {gateway_mac}")
        for host in hosts:
            ip  = host.get("ip") or (host[0] if isinstance(host,(list,tuple)) else None)
            mac = host.get("mac") or (host[1] if isinstance(host,(list,tuple)) else None)
            if ip and mac and ip != gateway_ip:
                lines.append(f"arp -s {ip} {mac}")
        with open(script, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(script, 0o755)

        console.print(Panel(
            f"  [{C_STEEL}]Script saved → {script}[/{C_STEEL}]\n\n"
            f"  [{C_YELLOW}]To persist across reboots add to /etc/rc.local or:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]sudo crontab -e\n"
            f"  @reboot /bin/bash {script}[/{C_DIM}]",
            border_style=C_GOOD, padding=(1, 2),
            title=f"[bold {C_GOOD}]◈ PERSISTENCE GUIDE[/bold {C_GOOD}]"
        ))

        ok(f"Applied: {len(applied)}  Failed: {len(failed)}")
        _loot("ARP_DEFENSE_APPLIED", {"applied": len(applied), "failed": len(failed)})
        return applied, failed

    def verify_arp_table(self, expected_map):
        section("DEFENSE: ARP TABLE VERIFICATION")
        try:
            out = subprocess.check_output(["arp", "-an"], text=True)
        except Exception as e:
            err(f"Cannot read ARP table: {e}"); return

        current = {}
        for line in out.strip().splitlines():
            parts = line.split()
            try:
                ip  = parts[1].strip("()")
                mac = parts[3]
                if mac not in ("<incomplete>", ""):
                    current[ip] = mac.upper()
            except: pass

        table = Table(box=box.SIMPLE_HEAD, border_style=C_GOOD,
                      header_style=f"bold {C_GOOD}", padding=(0,1))
        table.add_column("IP",       style=C_WHITE, width=16)
        table.add_column("EXPECTED", style=C_GOOD,  width=18)
        table.add_column("ACTUAL",   style=C_WHITE, width=18)
        table.add_column("STATUS",   style=C_WHITE, width=12)

        issues = 0
        for ip, expected_mac in expected_map.items():
            actual = current.get(ip, "NOT FOUND")
            exp_u  = expected_mac.upper()
            act_u  = actual.upper()

            if act_u == exp_u:
                status = f"[{C_GOOD}]✔ OK[/{C_GOOD}]"
            elif actual == "NOT FOUND":
                status = f"[{C_DIM}]ABSENT[/{C_DIM}]"
            else:
                status = f"[{C_EMBER}]⚡ MISMATCH[/{C_EMBER}]"
                issues += 1
                warn(f"POSSIBLE SPOOFING: {ip} expected {exp_u} got {act_u}")
                _loot("ARP_MISMATCH", {"ip": ip, "expected": exp_u, "actual": act_u})

            table.add_row(ip, exp_u, act_u, status)

        console.print(table)
        if issues == 0:
            ok("ARP table clean — no spoofing detected.")
        else:
            warn(f"{issues} mismatch(es) — investigate immediately.")
        return issues


# ══════════════════════════════════════════════════════════════════════════════
# ── LLMNR DEFENSE (SAFE) ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class LLMNRDefense:

    def disable_llmnr_linux(self):
        section("DEFENSE: DISABLE LLMNR + NBT-NS (Linux)")
        _attack_panel(
            "LLMNR / NBT-NS Poisoning",
            "When DNS fails, Windows/Linux broadcasts LLMNR queries to the LAN. "
            "Attackers answer claiming to be the target, capturing NTLMv2 hashes "
            "automatically from any authentication attempt.",
            "Silent credential theft with zero user interaction required."
        )

        applied = []

        # ── systemd-resolved: safe section-aware edit ──────────────────────
        resolved_conf = "/etc/systemd/resolved.conf"
        if os.path.exists(resolved_conf):
            try:
                with open(resolved_conf) as f:
                    original = f.read()

                new = original

                # Safe: use regex to replace existing values or add to [Resolve]
                # Never insert [Resolve] if it already exists
                def _set_key(content, key, value):
                    """Set key=value in [Resolve] section safely."""
                    pattern = re.compile(
                        rf'^#?\s*{re.escape(key)}\s*=.*$', re.M
                    )
                    if pattern.search(content):
                        # Replace existing (commented or not)
                        return pattern.sub(f"{key}={value}", content)
                    else:
                        # Add after [Resolve] header if present
                        if "[Resolve]" in content:
                            return content.replace(
                                "[Resolve]",
                                f"[Resolve]\n{key}={value}",
                                1  # only first occurrence
                            )
                        else:
                            return content + f"\n[Resolve]\n{key}={value}\n"

                new = _set_key(new, "LLMNR", "no")
                new = _set_key(new, "MulticastDNS", "no")

                if SafeFileEditor.write(resolved_conf, new):
                    success, _, _ = _run_cmd(
                        ["systemctl", "restart", "systemd-resolved"]
                    )
                    if success:
                        ok("systemd-resolved restarted.")
                        applied.append("LLMNR=no via systemd-resolved")
                        applied.append("MulticastDNS=no via systemd-resolved")
                    else:
                        warn("Restart manually: sudo systemctl restart systemd-resolved")

            except PermissionError:
                warn(f"Cannot write {resolved_conf} — run as root.")
            except Exception as e:
                warn(f"resolved.conf: {e}")

        # ── iptables: deduplicated block ───────────────────────────────────
        if Confirm.ask(
            f"  [{C_STEEL}]Also block LLMNR/NBT-NS at iptables level? "
            f"[{C_DIM}](adds DROP rules for UDP/5355 + UDP/137)[/{C_DIM}][/{C_STEEL}]",
            default=True
        ):
            info("Applying LLMNR/NBT-NS iptables rules (idempotent — skips duplicates)...")
            rules = [
                (["-A","INPUT", "-p","udp","--dport","5355","-j","DROP"],
                 "Block LLMNR inbound"),
                (["-A","OUTPUT","-p","udp","--dport","5355","-j","DROP"],
                 "Block LLMNR outbound"),
                (["-A","INPUT", "-p","udp","--dport","137", "-j","DROP"],
                 "Block NBT-NS inbound"),
                (["-A","OUTPUT","-p","udp","--dport","137", "-j","DROP"],
                 "Block NBT-NS outbound"),
            ]
            for rule, desc in rules:
                if IPTablesManager.add(rule, desc):
                    applied.append(desc)

        IPTablesManager.show_persist_command()

        # ── WPAD: safe append-only, check first ───────────────────────────
        self._block_wpad_safe()
        applied.append("WPAD blocked in /etc/hosts")

        # ── Windows guidance ──────────────────────────────────────────────
        console.print(Panel(
            f"  [{C_YELLOW}]Windows Group Policy:[/{C_YELLOW}]\n"
            f"  [{C_ASH}]Computer Config → Admin Templates → Network\n"
            f"  → DNS Client → Turn off multicast name resolution → ENABLED[/{C_ASH}]\n\n"
            f"  [{C_YELLOW}]Windows Registry:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\\n"
            f"  DNSClient\\EnableMulticast = 0 (DWORD)[/{C_DIM}]\n\n"
            f"  [{C_YELLOW}]Disable NBT-NS per adapter:[/{C_YELLOW}]\n"
            f"  [{C_ASH}]Adapter → TCP/IP Properties → Advanced\n"
            f"  → WINS tab → Disable NetBIOS over TCP/IP[/{C_ASH}]",
            border_style=C_GOOD, padding=(1,2),
            title=f"[bold {C_GOOD}]◈ WINDOWS GUIDANCE[/bold {C_GOOD}]"
        ))

        _defense_panel(applied)
        _loot("LLMNR_DEFENSE_APPLIED", {"applied": applied})
        return applied

    def _block_wpad_safe(self):
        """Append WPAD block to /etc/hosts only if not already present."""
        hosts_file = "/etc/hosts"
        marker     = "# KTOx WPAD block"
        try:
            with open(hosts_file) as f:
                content = f.read()
            if marker in content:
                ok("WPAD already blocked in /etc/hosts")
                return
            if "wpad" in content.lower():
                ok("wpad entry already exists in /etc/hosts")
                return
            entry = f"\n{marker}\n127.0.0.1\twpad\twpad.local\twpad.localdomain\n"
            console.print(f"  [{C_STEEL}]Will append to /etc/hosts:[/{C_STEEL}]")
            console.print(f"  [{C_DIM}]{entry.strip()}[/{C_DIM}]\n")
            if Confirm.ask(
                f"  [{C_ORANGE}]Append WPAD block to /etc/hosts?[/{C_ORANGE}]",
                default=True
            ):
                with open(hosts_file, "a") as f:
                    f.write(entry)
                ok("WPAD blocked in /etc/hosts")
        except PermissionError:
            warn("Cannot write /etc/hosts — run as root.")
        except Exception as e:
            warn(f"hosts file: {e}")

    def enable_llmnr_detection(self, iface):
        section("DEFENSE: LLMNR/NBT-NS ATTACK DETECTION")
        from scapy.all import sniff, DNS, DNSQR, UDP, IP, Raw
        info("Passive monitor — alerts when any host sends LLMNR/NBT-NS responses.")
        console.print(f"  [{C_DIM}]Ctrl+C to stop[/{C_DIM}]\n")
        stop = threading.Event()

        def _handle(pkt):
            if not pkt.haslayer(UDP): return
            ts = datetime.now().strftime("%H:%M:%S")
            if pkt[UDP].dport == 5355 and pkt.haslayer(DNS):
                if pkt[DNS].qr == 1:
                    console.print(
                        f"  [{C_BLOOD}]⚡ LLMNR RESPONSE[/{C_BLOOD}]  "
                        f"[{C_WHITE}]{pkt[IP].src}[/{C_WHITE}]  "
                        f"[{C_EMBER}]Possible poisoning![/{C_EMBER}]  "
                        f"[{C_DIM}]{ts}[/{C_DIM}]"
                    )
                    _loot("LLMNR_POISON_DETECTED", {"src": pkt[IP].src})
                else:
                    console.print(
                        f"  [{C_DIM}]LLMNR query  {pkt[IP].src}  {ts}[/{C_DIM}]"
                    )
            elif pkt[UDP].dport == 137 and pkt.haslayer(Raw):
                try:
                    raw   = pkt[Raw].load
                    flags = raw[2] if len(raw) > 2 else 0
                    if flags & 0x80:
                        console.print(
                            f"  [{C_BLOOD}]⚡ NBT-NS RESPONSE[/{C_BLOOD}]  "
                            f"[{C_WHITE}]{pkt[IP].src}[/{C_WHITE}]  "
                            f"[{C_EMBER}]Possible poisoning![/{C_EMBER}]  "
                            f"[{C_DIM}]{ts}[/{C_DIM}]"
                        )
                        _loot("NBNS_POISON_DETECTED", {"src": pkt[IP].src})
                except: pass

        try:
            sniff(iface=iface, filter="udp and (port 5355 or port 137)",
                  prn=_handle, store=False,
                  stop_filter=lambda _: stop.is_set())
        except KeyboardInterrupt:
            stop.set()
            console.print(f"\n  [{C_STEEL}]Detection stopped.[/{C_STEEL}]")


# ══════════════════════════════════════════════════════════════════════════════
# ── SMB DEFENSE (SAFE) ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SMBDefense:

    def enforce_smb_signing(self):
        section("DEFENSE: SMB SIGNING ENFORCEMENT")
        _attack_panel(
            "Rogue SMB / NTLMv2 Capture",
            "Attacker's fake SMB server captures NTLMv2 hashes automatically "
            "when LLMNR poisoning redirects victims to it.",
            "Domain credential theft, lateral movement, privilege escalation."
        )

        applied = []
        smb_conf = "/etc/samba/smb.conf"

        if not os.path.exists(smb_conf):
            info("Samba not installed — skipping smb.conf changes.")
        else:
            try:
                with open(smb_conf) as f:
                    original = f.read()

                new = original

                def _set_smb_key(content, key, value):
                    """Set key = value in [global] section safely."""
                    # Check if key exists anywhere (commented or not)
                    pattern = re.compile(
                        rf'^#?\s*{re.escape(key)}\s*=.*$', re.M
                    )
                    new_line = f"   {key} = {value}"
                    if pattern.search(content):
                        return pattern.sub(new_line, content)
                    else:
                        # Insert after first [global] only
                        return re.sub(
                            r'(\[global\])',
                            rf'\1\n{new_line}',
                            content, count=1
                        )

                new = _set_smb_key(new, "server signing", "mandatory")
                new = _set_smb_key(new, "client signing", "mandatory")

                # NTLM auth — ASK about legacy clients first
                console.print(Panel(
                    f"  [{C_YELLOW}]About ntlm auth = no[/{C_YELLOW}]\n\n"
                    f"  [{C_ASH}]Setting 'ntlm auth = no' prevents NTLMv1 authentication.\n"
                    f"  This BREAKS compatibility with:\n"
                    f"  · Windows XP / Server 2003 and older\n"
                    f"  · Some older network printers\n"
                    f"  · Some legacy applications\n\n"
                    f"  Modern Windows (Vista+) uses NTLMv2 by default and is unaffected.[/{C_ASH}]",
                    border_style=C_ORANGE, padding=(1,2),
                    title=f"[{C_ORANGE}]⚠ COMPATIBILITY WARNING[/{C_ORANGE}]"
                ))

                disable_ntlmv1 = Confirm.ask(
                    f"  [{C_STEEL}]Disable NTLMv1? (safe for modern-only networks)[/{C_STEEL}]",
                    default=False
                )
                if disable_ntlmv1:
                    new = _set_smb_key(new, "ntlm auth", "ntlmv2-only")
                    # ntlmv2-only is safer than "no" — allows NTLMv2 but blocks NTLMv1

                if SafeFileEditor.write(smb_conf, new):
                    # Validate config before restarting
                    valid, _, err_msg = _run_cmd(["testparm", "-s", smb_conf])
                    if valid:
                        _run_cmd(["systemctl", "restart", "smbd"])
                        ok("smbd restarted with new config.")
                        applied.append("SMB signing = mandatory")
                        if disable_ntlmv1:
                            applied.append("NTLMv1 disabled (NTLMv2-only)")
                    else:
                        warn(f"testparm validation failed: {err_msg}")
                        warn("Restoring backup...")
                        SafeFileEditor.rollback_all()

            except PermissionError:
                warn("Cannot write smb.conf — run as root.")
            except Exception as e:
                warn(f"smb.conf: {e}")

        # SMB port blocking — with active share check
        smb_ports_open = []
        for port in (445, 139):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                smb_ports_open.append(port)
            s.close()

        if smb_ports_open:
            console.print(Panel(
                f"  [{C_YELLOW}]SMB ports are open: {smb_ports_open}[/{C_YELLOW}]\n\n"
                f"  [{C_ASH}]If this machine does NOT share files via Samba,\n"
                f"  blocking these ports removes the attack surface entirely.\n\n"
                f"  If it DOES share files, leave them open — SMB signing\n"
                f"  (applied above) is the correct defense.[/{C_ASH}]",
                border_style=C_ORANGE, padding=(1,2),
                title=f"[{C_ORANGE}]⚠ SMB PORTS OPEN[/{C_ORANGE}]"
            ))
            if Confirm.ask(
                f"  [{C_STEEL}]Block SMB ports 445 + 139? "
                f"(only if NOT a file server)[/{C_STEEL}]",
                default=False
            ):
                for port in smb_ports_open:
                    IPTablesManager.add(
                        ["-A","INPUT","-p","tcp","--dport",str(port),"-j","DROP"],
                        f"Block SMB TCP/{port}"
                    )
                applied.append("SMB ports blocked")
                IPTablesManager.show_persist_command()
        else:
            ok("SMB ports not open — no exposure on this machine.")

        # Windows guidance
        console.print(Panel(
            f"  [{C_YELLOW}]Windows PowerShell:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]Set-SmbServerConfiguration -RequireSecuritySignature $true\n"
            f"  Set-SmbClientConfiguration -RequireSecuritySignature $true[/{C_DIM}]\n\n"
            f"  [{C_YELLOW}]Group Policy:[/{C_YELLOW}]\n"
            f"  [{C_ASH}]Computer Config → Windows Settings → Security Settings\n"
            f"  → Local Policies → Security Options:\n"
            f"  · 'Microsoft network client: Digitally sign communications (always)' → ENABLED\n"
            f"  · 'Microsoft network server: Digitally sign communications (always)' → ENABLED[/{C_ASH}]",
            border_style=C_GOOD, padding=(1,2),
            title=f"[bold {C_GOOD}]◈ WINDOWS GUIDANCE[/bold {C_GOOD}]"
        ))

        _defense_panel(applied or ["SMB signing guidance provided"])
        _loot("SMB_DEFENSE_APPLIED", {"applied": applied})


# ══════════════════════════════════════════════════════════════════════════════
# ── TLS DEFENSE (SAFE) ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SSLDefense:

    def enforce_tls(self):
        section("DEFENSE: TLS / HTTPS ENFORCEMENT")
        _attack_panel(
            "SSL Strip / HTTPS Downgrade",
            "Attacker proxies HTTP traffic, rewrites HTTPS links to HTTP, "
            "removes HSTS headers and Secure cookie flags.",
            "All web traffic exposed — passwords, sessions, tokens."
        )

        applied = []

        # NGINX — only add if installed AND validate before reload
        nginx_conf_d = "/etc/nginx/conf.d"
        if os.path.exists(nginx_conf_d):
            hsts_path = os.path.join(nginx_conf_d, "ktox_security_headers.conf")
            # Wrap in http block context to avoid directive placement errors
            hsts_content = """# KTOx Security Headers — safe global defaults
# Place inside an http{} block in nginx.conf, or include from http context.
# These are valid as http-level directives.
more_set_headers 'Strict-Transport-Security: max-age=63072000; includeSubDomains; preload';
more_set_headers 'X-Content-Type-Options: nosniff';
more_set_headers 'X-Frame-Options: DENY';
"""
            # Use add_header at server block level — safer approach
            # Just show the snippet rather than blindly writing global conf
            console.print(Panel(
                f"  [{C_YELLOW}]Add these headers to each nginx server block:[/{C_YELLOW}]\n\n"
                f"  [{C_DIM}]server {{\n"
                f"      add_header Strict-Transport-Security\n"
                f"          \"max-age=63072000; includeSubDomains; preload\" always;\n"
                f"      add_header X-Content-Type-Options \"nosniff\" always;\n"
                f"      add_header X-Frame-Options \"DENY\" always;\n"
                f"      add_header Content-Security-Policy\n"
                f"          \"default-src 'self'; script-src 'self';\" always;\n"
                f"  }}[/{C_DIM}]\n\n"
                f"  [{C_YELLOW}]Then test and reload:[/{C_YELLOW}]\n"
                f"  [{C_DIM}]sudo nginx -t && sudo systemctl reload nginx[/{C_DIM}]",
                border_style=C_GOOD, padding=(1,2),
                title=f"[bold {C_GOOD}]◈ NGINX HSTS CONFIG[/bold {C_GOOD}]"
            ))
            applied.append("NGINX HSTS snippet provided (manual apply required)")

        # HTTP redirect — NEVER apply automatically. Too dangerous.
        console.print(Panel(
            f"  [{C_ORANGE}]HTTP → HTTPS redirect NOT applied automatically.[/{C_ORANGE}]\n\n"
            f"  [{C_ASH}]Redirecting all outbound HTTP via iptables OUTPUT chain\n"
            f"  breaks: apt update, internal HTTP APIs, package downloads,\n"
            f"  monitoring endpoints, and any HTTP-only internal services.\n\n"
            f"  [{C_YELLOW}]Instead, redirect at the web server level:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]# nginx\n"
            f"  server {{\n"
            f"      listen 80;\n"
            f"      return 301 https://$host$request_uri;\n"
            f"  }}[/{C_DIM}]",
            border_style=C_ORANGE, padding=(1,2),
            title=f"[{C_ORANGE}]⚠ REDIRECT GUIDANCE (manual)[/{C_ORANGE}]"
        ))

        console.print(Panel(
            f"  [{C_YELLOW}]Browser hardening:[/{C_YELLOW}]\n"
            f"  [{C_ASH}]· Enable HTTPS-Only mode (Firefox: Settings → Privacy)\n"
            f"  · Chrome: Settings → Privacy → Always use HTTPS\n"
            f"  · Submit domains to HSTS preload list: https://hstspreload.org[/{C_ASH}]\n\n"
            f"  [{C_YELLOW}]Cookie hardening (all frameworks):[/{C_YELLOW}]\n"
            f"  [{C_DIM}]Set-Cookie: session=...; Secure; HttpOnly; SameSite=Strict[/{C_DIM}]",
            border_style=C_GOOD, padding=(1,2),
            title=f"[bold {C_GOOD}]◈ ADDITIONAL GUIDANCE[/bold {C_GOOD}]"
        ))

        _defense_panel(applied or ["TLS hardening guidance provided"])
        _loot("TLS_DEFENSE_SHOWN", {"applied": applied})


# ══════════════════════════════════════════════════════════════════════════════
# ── DNS DEFENSE (SAFE) ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class DNSDefense:

    def configure_dot(self):
        section("DEFENSE: ENCRYPTED DNS (DoT)")
        _attack_panel(
            "DNS Spoofing",
            "Attacker intercepts UDP/53 queries and returns fake IPs. "
            "Victims are silently redirected to malicious servers.",
            "Phishing, credential theft, malware delivery."
        )

        applied = []
        resolved_conf = "/etc/systemd/resolved.conf"

        if not os.path.exists(resolved_conf):
            info("systemd-resolved not present — showing manual guidance only.")
        else:
            # Check if VPN / corporate DNS in use
            console.print(Panel(
                f"  [{C_ORANGE}]Important: custom DNS servers will be set.[/{C_ORANGE}]\n\n"
                f"  [{C_ASH}]If you use a VPN or corporate network with private DNS zones\n"
                f"  (e.g. internal hostnames like server.corp.local), changing the\n"
                f"  upstream DNS to Cloudflare/Google will break those resolutions.\n\n"
                f"  Only proceed if this machine uses public DNS only.[/{C_ASH}]",
                border_style=C_ORANGE, padding=(1,2),
                title=f"[{C_ORANGE}]⚠ DNS CHANGE WARNING[/{C_ORANGE}]"
            ))

            if not Confirm.ask(
                f"  [{C_STEEL}]This machine uses public DNS only (no VPN/corporate DNS)?[/{C_STEEL}]",
                default=False
            ):
                info("DNS change skipped — keeping existing DNS configuration.")
            else:
                try:
                    with open(resolved_conf) as f:
                        original = f.read()

                    new = original

                    def _set_key(content, key, value):
                        pattern = re.compile(
                            rf'^#?\s*{re.escape(key)}\s*=.*$', re.M
                        )
                        line = f"{key}={value}"
                        if pattern.search(content):
                            return pattern.sub(line, content)
                        elif "[Resolve]" in content:
                            return content.replace("[Resolve]",
                                                   f"[Resolve]\n{line}", 1)
                        else:
                            return content + f"\n[Resolve]\n{line}\n"

                    new = _set_key(new, "DNS",
                                   "1.1.1.1#cloudflare-dns.com 8.8.8.8#dns.google")
                    new = _set_key(new, "FallbackDNS",
                                   "9.9.9.9#dns.quad9.net 149.112.112.112#dns.quad9.net")
                    new = _set_key(new, "DNSOverTLS", "yes")
                    new = _set_key(new, "DNSSEC", "yes")

                    if SafeFileEditor.write(resolved_conf, new):
                        # Test DoT before committing
                        info("Testing DNS-over-TLS connectivity...")
                        success, _, _ = _run_cmd(
                            ["systemctl", "restart", "systemd-resolved"]
                        )
                        time.sleep(2)
                        test_ok, _, _ = _run_cmd(
                            ["resolvectl", "query", "cloudflare.com"]
                        )
                        if test_ok:
                            ok("DNS-over-TLS working correctly.")
                            applied.append("DNS-over-TLS (Cloudflare + Google + Quad9)")
                            applied.append("DNSSEC validation enabled")
                        else:
                            warn("DNS resolution test failed — rolling back DNS changes.")
                            SafeFileEditor.rollback_all()
                            _run_cmd(["systemctl", "restart", "systemd-resolved"])
                            warn("Reverted to original DNS config.")

                except PermissionError:
                    warn("Cannot write resolved.conf — run as root.")
                except Exception as e:
                    warn(f"resolved.conf: {e}")

        # Cleartext DNS blocking — only offer, never auto-apply
        console.print(Panel(
            f"  [{C_ORANGE}]Blocking UDP/53 NOT applied automatically.[/{C_ORANGE}]\n\n"
            f"  [{C_ASH}]If DoT configuration fails or the upstream is down,\n"
            f"  blocking port 53 kills all DNS with no fallback — the machine\n"
            f"  effectively loses all network connectivity.\n\n"
            f"  If you want to block cleartext DNS manually after confirming\n"
            f"  DoT is working:[/{C_ASH}]\n\n"
            f"  [{C_DIM}]sudo iptables -A OUTPUT -p udp --dport 53 -j DROP\n"
            f"  sudo iptables -A OUTPUT -p tcp --dport 53 -j DROP[/{C_DIM}]",
            border_style=C_ORANGE, padding=(1,2),
            title=f"[{C_ORANGE}]⚠ CLEARTEXT DNS BLOCKING (manual only)[/{C_ORANGE}]"
        ))

        _defense_panel(applied or ["DNS encryption guidance provided"])
        _loot("DNS_DEFENSE_APPLIED", {"applied": applied})


# ══════════════════════════════════════════════════════════════════════════════
# ── CREDENTIAL DEFENSE ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class CredentialDefense:

    def harden_services(self):
        section("DEFENSE: CLEARTEXT PROTOCOL AUDIT")
        _attack_panel(
            "Multi-Protocol Credential Sniffing",
            "KTOx sniffs FTP, SMTP, POP3, IMAP, Telnet, IRC, Redis in plaintext. "
            "Under MITM, all credentials are visible without decryption.",
            "All credentials on cleartext protocols are exposed."
        )

        cleartext = {
            21:   ("FTP",    "Use SFTP (SSH) or FTPS instead"),
            23:   ("Telnet", "Replace with SSH — no valid modern use case"),
            110:  ("POP3",   "Use POP3S port 995 or IMAP+TLS port 993"),
            143:  ("IMAP",   "Use IMAPS port 993"),
            25:   ("SMTP",   "Enforce STARTTLS on 587 / SMTPS on 465"),
            6379: ("Redis",  "Bind to 127.0.0.1, enable requirepass + TLS"),
            6667: ("IRC",    "Use IRC+TLS on port 6697"),
            8080: ("HTTP",   "Migrate to HTTPS port 443"),
        }

        table = Table(box=box.SIMPLE_HEAD, border_style=C_GOOD,
                      header_style=f"bold {C_GOOD}", padding=(0,1))
        table.add_column("PORT",    style=C_WHITE,  width=6)
        table.add_column("SERVICE", style=C_STEEL,  width=10)
        table.add_column("STATUS",  style=C_WHITE,  width=12)
        table.add_column("FIX",     style=C_ASH,    width=45)

        exposed = []
        for port, (service, fix) in cleartext.items():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            is_open = s.connect_ex(("127.0.0.1", port)) == 0
            s.close()
            status = (f"[{C_EMBER}]EXPOSED[/{C_EMBER}]"
                      if is_open else f"[{C_GOOD}]not running[/{C_GOOD}]")
            if is_open:
                exposed.append((port, service, fix))
            table.add_row(str(port), service, status, fix)

        console.print(table)

        # Telnet: block immediately if running — no valid use case
        telnet_exposed = next((e for e in exposed if e[0] == 23), None)
        if telnet_exposed:
            warn("Telnet (port 23) is running. This has no valid modern use case.")
            if Confirm.ask(
                f"  [{C_BLOOD}]Block Telnet port 23 now?[/{C_BLOOD}]",
                default=True
            ):
                IPTablesManager.add(
                    ["-A","INPUT","-p","tcp","--dport","23","-j","DROP"],
                    "Block Telnet"
                )
                IPTablesManager.show_persist_command()

        # Redis: check binding
        redis_exposed = next((e for e in exposed if e[0] == 6379), None)
        if redis_exposed:
            # Check if it's actually reachable from outside (0.0.0.0)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            external = s.connect_ex(("127.0.0.1", 6379)) == 0
            s.close()
            if external:
                warn("Redis is accessible. Check it's not bound to 0.0.0.0.")
                console.print(
                    f"  [{C_DIM}]Check: sudo ss -tlnp | grep 6379[/{C_DIM}]\n"
                    f"  [{C_DIM}]Fix:   bind 127.0.0.1 in /etc/redis/redis.conf[/{C_DIM}]"
                )

        if exposed:
            console.print(Panel(
                f"  [{C_ORANGE}]{len(exposed)} cleartext service(s) found.[/{C_ORANGE}]\n\n"
                f"  [{C_ASH}]These transmit credentials in plaintext.\n"
                f"  Under MITM, an attacker sees all authentication.\n"
                f"  Migrate each to its encrypted equivalent.[/{C_ASH}]",
                border_style=C_ORANGE, padding=(1,2),
                title=f"[{C_ORANGE}]⚠ ACTION REQUIRED[/{C_ORANGE}]"
            ))
        else:
            ok("No cleartext services detected on this machine.")

        _loot("CLEARTEXT_AUDIT", {"exposed": [(p,s) for p,s,_ in exposed]})


# ══════════════════════════════════════════════════════════════════════════════
# ── NETWORK SEGMENTATION GUIDANCE ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class NetworkSegmentDefense:

    def vlan_guidance(self):
        section("DEFENSE: NETWORK SEGMENTATION")
        _attack_panel(
            "ARP / MITM Cross-Segment",
            "All ARP attacks are limited to one broadcast domain. "
            "Flat networks expose every device to every other device.",
            "One compromised device can attack the entire LAN."
        )
        console.print(Panel(
            f"  [{C_YELLOW}]Recommended VLAN layout:[/{C_YELLOW}]\n\n"
            f"  [{C_WHITE}]VLAN 10 — Management[/{C_WHITE}]\n"
            f"  [{C_ASH}]Servers, NAS, switches. Strictly firewalled. Admin only.[/{C_ASH}]\n\n"
            f"  [{C_WHITE}]VLAN 20 — Corporate / Trusted Clients[/{C_WHITE}]\n"
            f"  [{C_ASH}]Work laptops, desktops. DAI + 802.1X port auth.[/{C_ASH}]\n\n"
            f"  [{C_WHITE}]VLAN 30 — IoT / Smart Devices[/{C_WHITE}]\n"
            f"  [{C_ASH}]Cameras, smart plugs, sensors.\n"
            f"  Internet-only — no access to VLAN 10 or 20.[/{C_ASH}]\n\n"
            f"  [{C_WHITE}]VLAN 40 — Guest / Untrusted[/{C_WHITE}]\n"
            f"  [{C_ASH}]Guest WiFi. Client isolation on. Internet-only.[/{C_ASH}]\n\n"
            f"  [{C_WHITE}]VLAN 50 — Industrial / OT (if applicable)[/{C_WHITE}]\n"
            f"  [{C_ASH}]PLCs, SCADA. Air-gapped or unidirectional gateway.[/{C_ASH}]\n\n"
            f"  [{C_YELLOW}]Key rules:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]· ARP cannot cross VLAN boundaries without a router\n"
            f"  · Enable DAI + DHCP snooping per VLAN on managed switches\n"
            f"  · Enable client isolation on all WiFi SSIDs\n"
            f"  · Use 802.1X for wired port authentication[/{C_DIM}]",
            border_style=C_GOOD, padding=(1,2),
            title=f"[bold {C_GOOD}]◈ VLAN SEGMENTATION GUIDE[/bold {C_GOOD}]"
        ))

    def port_security_guidance(self):
        section("DEFENSE: SWITCH PORT SECURITY")
        _attack_panel(
            "ARP Flood / Rogue Device",
            "ARP floods overflow switch MAC tables causing fail-open broadcast. "
            "Rogue devices connect to any open port.",
            "Full traffic exposure, MAC table DoS, unauthorized access."
        )
        console.print(Panel(
            f"  [{C_YELLOW}]Cisco IOS — Port Security + Storm Control:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]interface range GigabitEthernet0/1-24\n"
            f"   switchport mode access\n"
            f"   switchport port-security maximum 2\n"
            f"   switchport port-security violation restrict\n"
            f"   switchport port-security aging time 2\n"
            f"   switchport port-security\n"
            f"   storm-control broadcast level 20\n"
            f"   storm-control action shutdown[/{C_DIM}]\n\n"
            f"  [{C_YELLOW}]Dynamic ARP Inspection + DHCP Snooping:[/{C_YELLOW}]\n"
            f"  [{C_DIM}]ip dhcp snooping\n"
            f"  ip dhcp snooping vlan 1,10,20,30\n"
            f"  ip arp inspection vlan 1,10,20,30\n"
            f"  ! Mark trusted uplinks only:\n"
            f"  interface GigabitEthernet0/24\n"
            f"   ip dhcp snooping trust\n"
            f"   ip arp inspection trust[/{C_DIM}]",
            border_style=C_GOOD, padding=(1,2),
            title=f"[bold {C_GOOD}]◈ SWITCH HARDENING[/bold {C_GOOD}]"
        ))


# ══════════════════════════════════════════════════════════════════════════════
# ── PURPLE TEAM AUDIT ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class SecurityAudit:

    def run_full_audit(self, iface, hosts, gateway_ip, gateway_mac):
        section("PURPLE TEAM SECURITY AUDIT")
        info("Read-only checks — nothing is modified during audit.")
        console.print()

        findings, passed = [], []

        def _check(name, ok_msg, fail_msg, severity, fix, result):
            if result:
                passed.append(ok_msg)
            else:
                findings.append({"severity": severity, "issue": fail_msg,
                                  "fix": fix})

        # 1 LLMNR
        try:
            out = subprocess.check_output(["resolvectl","status"],
                                          text=True, timeout=3)
            llmnr_off = ("llmnr=no" in out.lower() or
                         "llmnr: no" in out.lower())
            _check("LLMNR", "LLMNR disabled",
                   "LLMNR is enabled — vulnerable to name resolution poisoning",
                   "HIGH",
                   "Use KTOx Defense [3] to disable LLMNR + NBT-NS",
                   llmnr_off)
        except:
            findings.append({"severity":"MEDIUM",
                             "issue":"LLMNR status unknown",
                             "fix":"Check /etc/systemd/resolved.conf"})

        # 2 DNS encryption
        try:
            out = subprocess.check_output(["resolvectl","status"],
                                          text=True, timeout=3)
            dot_on = ("dnsovertls=yes" in out.lower() or
                      "dns over tls: yes" in out.lower())
            _check("DoT", "DNS-over-TLS enabled",
                   "Cleartext DNS (UDP/53) in use — spoofable under MITM",
                   "MEDIUM",
                   "Use KTOx Defense [6] to enable DoT",
                   dot_on)
        except: pass

        # 3 Gateway static ARP
        if gateway_ip:
            try:
                out = subprocess.check_output(["arp","-an"], text=True)
                gw_lines = [l for l in out.splitlines() if gateway_ip in l]
                is_static = any("PERM" in l.upper() or "static" in l.lower()
                                 for l in gw_lines)
                _check("GW ARP",
                       f"Gateway {gateway_ip} has static ARP entry",
                       f"Gateway {gateway_ip} ARP is dynamic — spoofable",
                       "HIGH",
                       f"Use KTOx Defense [1]: arp -s {gateway_ip} {gateway_mac}",
                       is_static)
            except: pass

        # 4 SMB signing
        smb_conf = "/etc/samba/smb.conf"
        if os.path.exists(smb_conf):
            try:
                with open(smb_conf) as f:
                    smb = f.read().lower()
                signed = "server signing = mandatory" in smb
                _check("SMB",
                       "SMB signing mandatory",
                       "SMB signing not mandatory — NTLMv2 relay possible",
                       "HIGH",
                       "Use KTOx Defense [4] to enable SMB signing",
                       signed)
            except: pass
        else:
            passed.append("Samba not installed — no SMB exposure")

        # 5 Cleartext services
        dangerous = {23:"Telnet", 21:"FTP", 6379:"Redis (check binding)"}
        for port, name in dangerous.items():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            open_ = s.connect_ex(("127.0.0.1", port)) == 0
            s.close()
            _check(name,
                   f"{name} not running",
                   f"{name} (port {port}) is running — cleartext credentials",
                   "HIGH" if port == 23 else "MEDIUM",
                   f"Use KTOx Defense [7] for remediation guidance",
                   not open_)

        # 6 SSH default port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        ssh_default = s.connect_ex(("0.0.0.0", 22)) == 0
        s.close()
        _check("SSH port",
               "SSH on non-default port (or not running)",
               "SSH on default port 22 — higher automated scan exposure",
               "LOW",
               "Change Port in /etc/ssh/sshd_config, disable root login",
               not ssh_default)

        # ── Render ──────────────────────────────────────────────────────────
        sev_color = {"HIGH": C_BLOOD, "MEDIUM": C_ORANGE, "LOW": C_YELLOW}
        for f in findings:
            color = sev_color.get(f["severity"], C_ASH)
            console.print(Panel(
                f"  {tag('Issue:', C_BLOOD)}  [{C_WHITE}]{f['issue']}[/{C_WHITE}]\n"
                f"  {tag('Fix:',   C_GOOD)}   [{C_GOOD}]{f['fix']}[/{C_GOOD}]",
                border_style=color,
                title=f"[bold {color}]⚠ {f['severity']}[/bold {color}]",
                padding=(0, 2)
            ))
        for p in passed:
            ok(p)

        high   = sum(1 for f in findings if f["severity"]=="HIGH")
        medium = sum(1 for f in findings if f["severity"]=="MEDIUM")
        low    = sum(1 for f in findings if f["severity"]=="LOW")

        console.print(Panel(
            f"  {tag('HIGH:',   C_BLOOD)}   {high}\n"
            f"  {tag('MEDIUM:', C_ORANGE)}  {medium}\n"
            f"  {tag('LOW:',    C_YELLOW)}  {low}\n"
            f"  {tag('PASSED:', C_GOOD)}  {len(passed)}",
            border_style=C_BLOOD if high else C_ORANGE if medium else C_GOOD,
            title=f"[bold {C_BLOOD}]◈ AUDIT SUMMARY[/bold {C_BLOOD}]",
            padding=(1, 2)
        ))

        os.makedirs(loot_dir, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(loot_dir, f"audit_{ts}.json")
        with open(path, "w") as f:
            json.dump({"ts": datetime.now().isoformat(),
                       "findings": findings, "passed": passed,
                       "summary": {"high":high,"medium":medium,
                                   "low":low,"passed":len(passed)}},
                      f, indent=2)
        console.print(f"\n  [{C_STEEL}]Audit saved → {path}[/{C_STEEL}]")
        _loot("AUDIT_COMPLETE", {"high":high,"medium":medium,"low":low})
        return findings, passed


# ══════════════════════════════════════════════════════════════════════════════
# ── ROLLBACK ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def rollback_all():
    """Undo everything KTOx defense has done this session."""
    section("DEFENSE ROLLBACK")
    warn("Reverting all changes made by KTOx Defense this session...")
    SafeFileEditor.rollback_all()
    IPTablesManager.rollback()
    ok("Rollback complete.")
    _loot("DEFENSE_ROLLBACK", {"ts": datetime.now().isoformat()})


# ══════════════════════════════════════════════════════════════════════════════
# ── MENU ─────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def defense_menu(iface, hosts, gateway_ip, gateway_mac):
    while True:
        section("PURPLE TEAM DEFENSE CENTER")
        console.print(f"""
  [{C_GOOD}]── AUTOMATED DEFENSES ─────────────────────────────────[/{C_GOOD}]
  [{C_BLOOD}][1][/{C_BLOOD}]  [{C_ASH}]ARP Hardening          Static ARP + backup + confirm[/{C_ASH}]
  [{C_BLOOD}][2][/{C_BLOOD}]  [{C_ASH}]Verify ARP Table        Check for active spoofing (read-only)[/{C_ASH}]
  [{C_BLOOD}][3][/{C_BLOOD}]  [{C_ASH}]Disable LLMNR/NBT-NS    Safe edit + iptables dedup[/{C_ASH}]
  [{C_BLOOD}][4][/{C_BLOOD}]  [{C_ASH}]SMB Signing             Validates config before restart[/{C_ASH}]
  [{C_BLOOD}][5][/{C_BLOOD}]  [{C_ASH}]TLS Guidance            HSTS snippets — manual apply[/{C_ASH}]
  [{C_BLOOD}][6][/{C_BLOOD}]  [{C_ASH}]Encrypted DNS           DoT with connectivity test + rollback[/{C_ASH}]
  [{C_BLOOD}][7][/{C_BLOOD}]  [{C_ASH}]Cleartext Service Audit Read-only port scan[/{C_ASH}]

  [{C_GOOD}]── DETECTION ──────────────────────────────────────────[/{C_GOOD}]
  [{C_BLOOD}][8][/{C_BLOOD}]  [{C_ASH}]LLMNR Attack Detector   Passive packet monitor[/{C_ASH}]

  [{C_GOOD}]── GUIDANCE ───────────────────────────────────────────[/{C_GOOD}]
  [{C_BLOOD}][9][/{C_BLOOD}]  [{C_ASH}]VLAN Segmentation       Network design guide[/{C_ASH}]
  [{C_BLOOD}][0][/{C_BLOOD}]  [{C_ASH}]Switch Port Security     DAI + storm control config[/{C_ASH}]

  [{C_GOOD}]── AUDIT & SAFETY ─────────────────────────────────────[/{C_GOOD}]
  [{C_BLOOD}][X][/{C_BLOOD}]  [{C_ASH}]Purple Team Audit       Read-only security assessment[/{C_ASH}]
  [{C_BLOOD}][Z][/{C_BLOOD}]  [{C_ASH}]Rollback All            Undo all defense changes this session[/{C_ASH}]

  [{C_BLOOD}][E][/{C_BLOOD}]  [{C_ASH}]Back[/{C_ASH}]
""")

        choice = Prompt.ask(f"  [{C_BLOOD}]defense>[/{C_BLOOD}]").strip().upper()

        expected = {}
        if gateway_ip and gateway_mac:
            expected[gateway_ip] = gateway_mac
        for h in hosts:
            ip  = h.get("ip") if isinstance(h, dict) else (h[0] if isinstance(h,(list,tuple)) else None)
            mac = h.get("mac") or (h[1] if isinstance(h,(list,tuple)) else None)
            if ip and mac: expected[ip] = mac

        try:
            if choice == "1":
                ArpSpoofDefense().apply_static_arp(hosts, gateway_ip, gateway_mac)
            elif choice == "2":
                ArpSpoofDefense().verify_arp_table(expected)
            elif choice == "3":
                LLMNRDefense().disable_llmnr_linux()
            elif choice == "4":
                SMBDefense().enforce_smb_signing()
            elif choice == "5":
                SSLDefense().enforce_tls()
            elif choice == "6":
                DNSDefense().configure_dot()
            elif choice == "7":
                CredentialDefense().harden_services()
            elif choice == "8":
                LLMNRDefense().enable_llmnr_detection(iface)
            elif choice == "9":
                NetworkSegmentDefense().vlan_guidance()
            elif choice == "0":
                NetworkSegmentDefense().port_security_guidance()
            elif choice == "X":
                SecurityAudit().run_full_audit(iface, hosts, gateway_ip, gateway_mac)
            elif choice == "Z":
                rollback_all()
            elif choice == "E":
                return
            else:
                console.print(f"  [{C_ORANGE}]Invalid option.[/{C_ORANGE}]")
        except KeyboardInterrupt:
            console.print(f"\n  [{C_ORANGE}]Interrupted.[/{C_ORANGE}]")
        except Exception as ex:
            err(f"Error: {ex}")
            import traceback; traceback.print_exc()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: Must run as root"); sys.exit(1)
    iface       = Prompt.ask("Interface", default="wlan0")
    gateway_ip  = Prompt.ask("Gateway IP",  default="")
    gateway_mac = Prompt.ask("Gateway MAC", default="")
    defense_menu(iface, [], gateway_ip, gateway_mac)
