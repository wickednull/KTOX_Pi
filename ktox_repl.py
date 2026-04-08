#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_repl.py — KTOx Interactive REPL Shell + Plugin System v1.0
#
# Interactive console with:
#   · set/get for session variables
#   · module.start / module.stop
#   · status of running modules
#   · tab completion
#   · command history
#   · plugin autodiscovery from modules/ folder

import os, sys, re, time, json, cmd, threading, importlib, inspect, shutil, readline
from datetime import datetime
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich.rule    import Rule
    from rich.syntax  import Syntax
    from rich         import box
except ImportError:
    print("ERROR: pip3 install rich"); sys.exit(1)

console = Console(highlight=False)

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

LOOT_DIR   = "ktox_loot"
PLUGIN_DIR = "modules"


# ══════════════════════════════════════════════════════════════════════════════
# ── PLUGIN SYSTEM ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class KTOxPlugin:
    """
    Base class for KTOx plugins.
    Drop a Python file into modules/ that subclasses this and it's auto-loaded.
    """

    # Plugin metadata — override in subclass
    name        = "unnamed"
    description = "No description"
    version     = "1.0"
    author      = "unknown"

    def __init__(self, session):
        self.session = session   # reference to REPLSession for state access
        self._running = False

    def start(self, *args):
        """Called when user runs: module.start <name> [args]"""
        raise NotImplementedError

    def stop(self):
        """Called when user runs: module.stop <name>"""
        self._running = False

    def status(self):
        """Return status string for display."""
        return "ACTIVE" if self._running else "STOPPED"

    def help(self):
        """Return help text."""
        return self.description


class PluginLoader:
    """
    Scans the modules/ directory and loads any KTOxPlugin subclasses found.
    Hot-reloads if a file changes.
    """

    def __init__(self, plugin_dir=PLUGIN_DIR):
        self.plugin_dir = plugin_dir
        self.plugins    = {}     # name → plugin class
        self._mtimes    = {}     # path → mtime for hot-reload
        self._load_all()

    def _load_file(self, path):
        """Load plugins from a single file."""
        try:
            spec   = importlib.util.spec_from_file_location(
                Path(path).stem, path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            loaded = 0
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (issubclass(obj, KTOxPlugin) and
                        obj is not KTOxPlugin and
                        hasattr(obj, "name") and obj.name != "unnamed"):
                    self.plugins[obj.name] = obj
                    loaded += 1

            return loaded

        except Exception as e:
            console.print(
                f"  [{C_ORANGE}]Plugin load error [{path}]: {e}[/{C_ORANGE}]"
            )
            return 0

    def _load_all(self):
        """Load all plugins from plugin_dir."""
        os.makedirs(self.plugin_dir, exist_ok=True)
        count = 0
        for f in Path(self.plugin_dir).glob("*.py"):
            if f.name.startswith("_"): continue
            loaded = self._load_file(str(f))
            self._mtimes[str(f)] = f.stat().st_mtime
            count += loaded
        return count

    def reload(self):
        """Check for changed/new files and hot-reload them."""
        reloaded = 0
        for f in Path(self.plugin_dir).glob("*.py"):
            if f.name.startswith("_"): continue
            mtime = f.stat().st_mtime
            if self._mtimes.get(str(f)) != mtime:
                self._load_file(str(f))
                self._mtimes[str(f)] = mtime
                reloaded += 1
        return reloaded

    def list_plugins(self):
        return dict(self.plugins)

    def get(self, name):
        return self.plugins.get(name)

    def write_example(self):
        """Write an example plugin to modules/."""
        os.makedirs(self.plugin_dir, exist_ok=True)
        path    = os.path.join(self.plugin_dir, "example_plugin.py")
        content = '''#!/usr/bin/env python3
# Example KTOx Plugin
# Drop files like this into modules/ — KTOx loads them automatically.

from ktox_repl import KTOxPlugin
import threading, time

class ExamplePlugin(KTOxPlugin):
    name        = "example"
    description = "Example plugin — prints a counter every N seconds"
    version     = "1.0"
    author      = "wickednull"

    def start(self, interval="5"):
        self._running = True
        interval = float(interval)

        def _loop():
            count = 0
            while self._running:
                count += 1
                print(f"  [example] tick {count}")
                time.sleep(interval)

        threading.Thread(target=_loop, daemon=True).start()
        return f"Example plugin running (interval={interval}s)"

    def stop(self):
        self._running = False
        return "Example plugin stopped."

    def help(self):
        return "Usage: module.start example [interval_seconds]"
'''
        with open(path, "w") as f:
            f.write(content)
        return path


# ══════════════════════════════════════════════════════════════════════════════
# ── SESSION STATE ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class REPLSession:
    """
    Holds all mutable session state for the REPL.
    Passed to plugins so they can read/write shared state.
    """

    def __init__(self, iface="", gateway_ip="", gateway_mac="",
                 attacker_ip="", hosts=None):
        self.vars = {
            "IFACE":       iface,
            "GATEWAY_IP":  gateway_ip,
            "GATEWAY_MAC": gateway_mac,
            "ATTACKER_IP": attacker_ip,
            "LOOT_DIR":    LOOT_DIR,
            "STEALTH":     "off",
            "VERBOSE":     "on",
        }
        self.hosts         = hosts or []
        self.active_modules= {}   # name → plugin instance
        self.history       = []   # command history
        self.plugin_loader = PluginLoader()
        self._log_path     = os.path.join(LOOT_DIR, "repl.log")
        os.makedirs(LOOT_DIR, exist_ok=True)

    def get(self, key):
        return self.vars.get(key.upper(), "")

    def set(self, key, value):
        self.vars[key.upper()] = value

    def log(self, cmd, result=""):
        entry = {
            "ts":     datetime.now().isoformat(),
            "cmd":    cmd,
            "result": result
        }
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except: pass

    def substitute_vars(self, text):
        """Replace $VAR references with session values."""
        for k, v in self.vars.items():
            text = text.replace(f"${k}", v)
        return text


# ══════════════════════════════════════════════════════════════════════════════
# ── REPL SHELL ────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

HELP_TEXT = """
[bold #C0392B]KTOx Interactive Shell[/bold #C0392B]

[#717D7E]VARIABLES[/#717D7E]
  set <VAR> <value>          Set a session variable
  get <VAR>                  Get a variable value
  get *                      Show all variables
  env                        Alias for get *

[#717D7E]MODULES[/#717D7E]
  module.start <name> [args] Start a loaded module
  module.stop  <name>        Stop a running module
  module.list                List all available modules
  module.status              Show running modules
  module.reload              Hot-reload plugins from modules/

[#717D7E]BUILT-IN COMMANDS[/#717D7E]
  scan                       Run network scan
  hosts                      Show discovered hosts
  loot                       Show loot directory contents
  exec <shell command>       Run a shell command
  sleep <seconds>            Pause execution
  clear                      Clear the screen
  help                       Show this help
  exit / quit / back         Return to main menu

[#717D7E]EXAMPLES[/#717D7E]
  set IFACE wlan0
  set GATEWAY_IP 192.168.1.1
  module.start mitm
  module.status
  exec cat ktox_loot/ntlm_hashes.txt
"""

BUILTIN_MODULES = {
    "mitm":        "ktox_mitm.mitm_menu",
    "advanced":    "ktox_advanced.advanced_menu",
    "extended":    "ktox_extended.extended_menu",
    "wifi":        "ktox_wifi.wifi_menu",
    "netattack":   "ktox_netattack.netattack_menu",
    "stealth":     "ktox_stealth.stealth_menu",
    "defense":     "ktox_defense.defense_menu",
    "dashboard":   "ktox_dashboard.start_dashboard",
    "fingerprint": "ktox_stealth.fingerprint_menu",
}


class KTOxREPL(cmd.Cmd):
    """
    Interactive REPL shell for KTOx.
    Supports variables, module control, tab completion, command history.
    """

    intro   = ""
    prompt  = ""   # overridden in cmdloop

    def __init__(self, session: REPLSession):
        super().__init__()
        self.session = session
        self._setup_readline()

    def _setup_readline(self):
        """Configure tab completion and history."""
        readline.set_completer_delims(' \t\n')
        readline.parse_and_bind("tab: complete")

        # Load history
        hist_path = os.path.join(LOOT_DIR, ".repl_history")
        try:
            readline.read_history_file(hist_path)
        except: pass

        import atexit
        atexit.register(readline.write_history_file, hist_path)

    def _prompt(self):
        iface = self.session.get("IFACE") or "?"
        gw    = self.session.get("GATEWAY_IP") or "?"
        mods  = len(self.session.active_modules)
        mod_s = f" [{mods}▶]" if mods else ""
        return f"\x1b[31m ktox\x1b[0m(\x1b[33m{iface}\x1b[0m)> "

    def cmdloop(self, intro=None):
        """Override to use rich rendering and custom prompt."""
        self._print_banner()
        stop = False
        while not stop:
            try:
                line = input(self._prompt()).strip()
                if not line: continue
                self.session.history.append(line)
                self.session.log(line)

                # Variable substitution
                line = self.session.substitute_vars(line)

                result = self.onecmd(line)
                if result:
                    stop = True

            except KeyboardInterrupt:
                console.print(f"\n  [\x1b[33m]\x1b[0m Type 'exit' to quit.")
            except EOFError:
                break

    def _print_banner(self):
        mods    = len(self.session.plugin_loader.list_plugins())
        plugins = mods
        console.print(Panel(
            f"  [{C_BLOOD}]KTOx Interactive Shell[/{C_BLOOD}]  "
            f"[{C_DIM}]Type 'help' for commands[/{C_DIM}]\n\n"
            f"  [{C_STEEL}]Interface:   [{C_WHITE}]{self.session.get('IFACE') or 'not set'}[/{C_WHITE}][/{C_STEEL}]\n"
            f"  [{C_STEEL}]Gateway:     [{C_WHITE}]{self.session.get('GATEWAY_IP') or 'not set'}[/{C_WHITE}][/{C_STEEL}]\n"
            f"  [{C_STEEL}]Attacker IP: [{C_WHITE}]{self.session.get('ATTACKER_IP') or 'not set'}[/{C_WHITE}][/{C_STEEL}]\n"
            f"  [{C_STEEL}]Plugins:     [{C_ASH}]{plugins} loaded from modules/[/{C_ASH}][/{C_STEEL}]",
            border_style=C_RUST,
            title=f"[bold {C_BLOOD}]◈ KTOX SHELL[/bold {C_BLOOD}]",
            padding=(1,2)
        ))

    # ── VARIABLE COMMANDS ────────────────────────────────────────────────
    def do_set(self, line):
        """set <VAR> <value> — set a session variable"""
        parts = line.split(None, 1)
        if len(parts) < 2:
            console.print(f"  [{C_ORANGE}]Usage: set <VAR> <value>[/{C_ORANGE}]")
            return
        key, val = parts[0], parts[1]
        self.session.set(key, val)
        console.print(f"  [{C_GOOD}]{key.upper()} = {val}[/{C_GOOD}]")

    def do_get(self, line):
        """get <VAR> or get * — show variable(s)"""
        key = line.strip()
        if not key or key == "*":
            self.do_env("")
            return
        val = self.session.get(key)
        console.print(
            f"  [{C_STEEL}]{key.upper()}[/{C_STEEL}] = [{C_WHITE}]{val or '(not set)'}[/{C_WHITE}]"
        )

    def do_env(self, line):
        """env — show all session variables"""
        table = Table(box=box.SIMPLE, border_style=C_RUST,
                      show_header=False, padding=(0,1))
        table.add_column("key",   style=C_BLOOD,  width=16)
        table.add_column("value", style=C_WHITE)
        for k, v in sorted(self.session.vars.items()):
            table.add_row(k, v or "(not set)")
        console.print(table)

    # ── MODULE COMMANDS ──────────────────────────────────────────────────
    def do_module(self, line):
        """module.start/stop/list/status/reload"""
        # Handled by default via do_module_start etc.
        console.print(f"  [{C_ORANGE}]Use: module.start / module.stop / module.list / module.status / module.reload[/{C_ORANGE}]")

    def _dispatch_module(self, action, name, args=""):
        """Route module commands."""
        if action == "list":
            self._module_list()
        elif action == "status":
            self._module_status()
        elif action == "reload":
            n = self.session.plugin_loader.reload()
            console.print(f"  [{C_GOOD}]{n} plugin(s) reloaded.[/{C_GOOD}]")
        elif action == "start" and name:
            self._module_start(name, args)
        elif action == "stop" and name:
            self._module_stop(name)
        else:
            console.print(f"  [{C_ORANGE}]Unknown module command: {action}[/{C_ORANGE}]")

    def _module_list(self):
        """Show all available modules."""
        table = Table(box=box.SIMPLE_HEAD, border_style=C_RUST,
                      header_style=f"bold {C_BLOOD}", padding=(0,1))
        table.add_column("NAME",    style=C_WHITE,  width=18)
        table.add_column("TYPE",    style=C_DIM,    width=10)
        table.add_column("STATUS",  style=C_WHITE,  width=10)
        table.add_column("DESC",    style=C_ASH)

        for name in sorted(BUILTIN_MODULES):
            status = "ACTIVE" if name in self.session.active_modules else "—"
            color  = C_GOOD if status == "ACTIVE" else C_DIM
            table.add_row(
                name, "built-in",
                f"[{color}]{status}[/{color}]",
                BUILTIN_MODULES[name].split(".")[0]
            )

        for name, cls in sorted(self.session.plugin_loader.list_plugins().items()):
            inst = self.session.active_modules.get(name)
            status = inst.status() if inst else "—"
            color  = C_GOOD if "ACTIVE" in status else C_DIM
            table.add_row(
                name, "plugin",
                f"[{color}]{status}[/{color}]",
                cls.description
            )

        console.print(table)

    def _module_status(self):
        """Show running modules."""
        if not self.session.active_modules:
            console.print(f"  [{C_DIM}]No active modules.[/{C_DIM}]")
            return
        for name, inst in self.session.active_modules.items():
            status = inst.status() if hasattr(inst, "status") else "RUNNING"
            console.print(
                f"  [{C_GOOD}]●[/{C_GOOD}]  [{C_WHITE}]{name:20s}[/{C_WHITE}]  "
                f"[{C_ASH}]{status}[/{C_ASH}]"
            )

    def _module_start(self, name, args=""):
        """Start a module by name."""
        # Try plugin first
        plugin_cls = self.session.plugin_loader.get(name)
        if plugin_cls:
            inst = plugin_cls(self.session)
            result = inst.start(*args.split() if args else [])
            self.session.active_modules[name] = inst
            console.print(
                f"  [{C_GOOD}]✔ [{name}] started[/{C_GOOD}]"
                + (f": {result}" if result else "")
            )
            return

        # Try built-in
        if name in BUILTIN_MODULES:
            fn_path = BUILTIN_MODULES[name]
            mod_name, fn_name = fn_path.rsplit(".", 1)
            try:
                mod = importlib.import_module(mod_name)
                fn  = getattr(mod, fn_name)

                # Run in thread
                s   = self.session
                gw  = s.get("GATEWAY_IP")
                gwm = s.get("GATEWAY_MAC")
                ip  = s.get("ATTACKER_IP")
                ifc = s.get("IFACE")

                def _run():
                    try:
                        # Different functions take different args
                        if "menu" in fn_name:
                            if name in ("mitm", "advanced", "extended"):
                                fn(ifc, ip, gw)
                            elif name == "netattack":
                                fn(ifc, gw, gwm)   # iface, gateway_ip, gateway_mac
                            elif name in ("defense",):
                                fn(ifc, s.hosts, gw, gwm)
                            elif name == "wifi":
                                fn()
                            elif name == "stealth":
                                fn(ifc)
                            elif name == "fingerprint":
                                fn(ifc, s.hosts)
                            else:
                                fn()
                        elif name == "dashboard":
                            fn(port=9999, iface=ifc,
                               attacker_ip=ip, gateway_ip=gw)
                        else:
                            fn()
                    except Exception as e:
                        console.print(f"  [{C_BLOOD}]{name} error: {e}[/{C_BLOOD}]")

                t = threading.Thread(target=_run, daemon=True)
                t.start()
                # Store a minimal wrapper
                class _Wrapper:
                    def status(self): return "RUNNING"
                    def stop(self): pass
                self.session.active_modules[name] = _Wrapper()
                console.print(f"  [{C_GOOD}]✔ [{name}] launched in background[/{C_GOOD}]")

            except ImportError as e:
                console.print(f"  [{C_ORANGE}]{mod_name} not found: {e}[/{C_ORANGE}]")
            except Exception as e:
                console.print(f"  [{C_BLOOD}]Error: {e}[/{C_BLOOD}]")
        else:
            console.print(
                f"  [{C_ORANGE}]Unknown module: {name}. Run 'module.list'[/{C_ORANGE}]"
            )

    def _module_stop(self, name):
        """Stop a running module."""
        inst = self.session.active_modules.pop(name, None)
        if inst and hasattr(inst, "stop"):
            inst.stop()
            console.print(f"  [{C_GOOD}]✔ [{name}] stopped[/{C_GOOD}]")
        else:
            console.print(f"  [{C_ORANGE}]{name} is not active.[/{C_ORANGE}]")

    def default(self, line):
        """Handle module.start/stop/list/status shorthand."""
        # module.action [name] [args]
        m = re.match(r'^module\.(start|stop|list|status|reload)\s*(\S+)?\s*(.*)?$',
                     line.strip())
        if m:
            action = m.group(1)
            name   = m.group(2) or ""
            args   = m.group(3) or ""
            self._dispatch_module(action, name, args)
            return

        console.print(
            f"  [{C_ORANGE}]Unknown command: {line.split()[0]}  "
            f"(type 'help')[/{C_ORANGE}]"
        )

    # ── BUILT-IN COMMANDS ────────────────────────────────────────────────
    def do_scan(self, line):
        """scan — discover hosts on the network"""
        iface = self.session.get("IFACE")
        if not iface:
            console.print(f"  [{C_ORANGE}]Set interface first: set IFACE eth0[/{C_ORANGE}]")
            return
        console.print(f"  [{C_STEEL}]Scanning on {iface}...[/{C_STEEL}]")
        try:
            import scan as _scan
            gw    = self.session.get("GATEWAY_IP")
            net   = gw.rsplit(".", 1)[0] + ".0/24" if gw else "192.168.1.0/24"
            hosts = _scan.scanNetwork(net)
            self.session.hosts = hosts
            console.print(f"  [{C_GOOD}]{len(hosts)} host(s) found.[/{C_GOOD}]")
        except Exception as e:
            console.print(f"  [{C_BLOOD}]Scan error: {e}[/{C_BLOOD}]")

    def do_hosts(self, line):
        """hosts — show discovered hosts"""
        if not self.session.hosts:
            console.print(f"  [{C_DIM}]No hosts. Run 'scan' first.[/{C_DIM}]")
            return
        table = Table(box=box.SIMPLE, border_style=C_RUST,
                      header_style=f"bold {C_BLOOD}", padding=(0,1))
        table.add_column("#",        style=C_DIM,   width=4)
        table.add_column("IP",       style=C_WHITE, width=16)
        table.add_column("MAC",      style=C_STEEL, width=18)
        table.add_column("VENDOR",   style=C_DIM,   width=14)
        table.add_column("HOSTNAME", style=C_DIM,   width=16)
        for i, h in enumerate(self.session.hosts):
            if isinstance(h, (list, tuple)):
                ip       = h[0] if len(h) > 0 else "?"
                mac      = h[1] if len(h) > 1 else ""
                vendor   = h[2] if len(h) > 2 else ""
                hostname = h[3] if len(h) > 3 else ""
            else:
                ip       = h.get("ip", "?")
                mac      = h.get("mac", "")
                vendor   = h.get("vendor", "")
                hostname = h.get("hostname", "")
            table.add_row(str(i), ip, mac, vendor or "—", hostname or "—")
        console.print(table)

    def do_loot(self, line):
        """loot — show loot directory contents"""
        if not os.path.exists(LOOT_DIR):
            console.print(f"  [{C_DIM}]No loot directory yet.[/{C_DIM}]")
            return
        files = sorted(os.listdir(LOOT_DIR))
        for f in files:
            path = os.path.join(LOOT_DIR, f)
            size = os.path.getsize(path)
            console.print(
                f"  [{C_STEEL}]{f:45s}[/{C_STEEL}]  "
                f"[{C_DIM}]{size:>8} bytes[/{C_DIM}]"
            )

    def do_exec(self, line):
        """exec <cmd> — run a shell command"""
        import subprocess
        try:
            result = subprocess.run(
                line, shell=True, capture_output=True, text=True
            )
            if result.stdout:
                console.print(f"[{C_ASH}]{result.stdout.strip()}[/{C_ASH}]")
            if result.stderr:
                console.print(f"[{C_ORANGE}]{result.stderr.strip()}[/{C_ORANGE}]")
        except Exception as e:
            console.print(f"  [{C_BLOOD}]{e}[/{C_BLOOD}]")

    def do_sleep(self, line):
        """sleep <seconds> — pause"""
        try:
            time.sleep(float(line.strip()))
        except ValueError:
            console.print(f"  [{C_ORANGE}]Usage: sleep <seconds>[/{C_ORANGE}]")

    def do_clear(self, line):
        """clear — clear the screen"""
        os.system("clear")

    def do_help(self, line):
        """help — show command reference"""
        console.print(HELP_TEXT)

    def do_exit(self, line):
        """exit — return to main menu"""
        return True

    def do_quit(self, line):
        """quit — return to main menu"""
        return True

    def do_back(self, line):
        """back — return to main menu"""
        return True

    def do_EOF(self, line):
        return True

    # ── TAB COMPLETION ───────────────────────────────────────────────────
    def complete_set(self, text, line, begidx, endidx):
        return [k for k in self.session.vars if k.startswith(text.upper())]

    def complete_get(self, text, line, begidx, endidx):
        return [k for k in self.session.vars if k.startswith(text.upper())] + ["*"]

    def completedefault(self, text, line, begidx, endidx):
        """Complete module names."""
        names = (list(BUILTIN_MODULES.keys()) +
                 list(self.session.plugin_loader.list_plugins().keys()))
        return [n for n in names if n.startswith(text)]


# ══════════════════════════════════════════════════════════════════════════════
# ── ENTRY POINT ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def launch_repl(iface="", gateway_ip="", gateway_mac="",
                attacker_ip="", hosts=None):
    """Launch the interactive REPL shell."""
    session = REPLSession(
        iface=iface,
        gateway_ip=gateway_ip,
        gateway_mac=gateway_mac,
        attacker_ip=attacker_ip,
        hosts=hosts or []
    )

    # Write example plugin if modules/ is empty
    if not list(Path(PLUGIN_DIR).glob("*.py")):
        path = session.plugin_loader.write_example()
        console.print(
            f"  [{C_DIM}]Example plugin written → {path}[/{C_DIM}]"
        )
        session.plugin_loader.reload()

    repl = KTOxREPL(session)
    repl.cmdloop()


if __name__ == "__main__":
    launch_repl()
