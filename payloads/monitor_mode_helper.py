import os
import sys
import time
import signal
import subprocess
import re

# Log function for debugging within the helper
def log(message):
    """Write message to log file (for helper debugging)."""
    timestamp = time.strftime("%H:%M:%S")
    log_file = "/tmp/monitor_mode_helper.log" # Use a temporary log file for the helper
    try:
        with open(log_file, 'a') as f:
            f.write(f"[{timestamp}] [HELPER] {message}\n")
            f.flush()
    except:
        pass

def _run_command(cmd_parts, description="command", timeout=10):
    """
    Runs a shell command and logs its output and errors.
    Returns (stdout, success_boolean)
    """
    try:
        log(f"Executing {description}: {' '.join(cmd_parts)}")
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False # Do not raise CalledProcessError automatically
        )
        if result.returncode != 0:
            log(f"ERROR: {description} failed with exit code {result.returncode}")
            if result.stdout:
                log(f"  STDOUT: {result.stdout.strip()}")
            if result.stderr:
                log(f"  STDERR: {result.stderr.strip()}")
            return result.stdout, False
        else:
            if result.stderr: # Log stderr even on success, it might contain warnings
                log(f"WARNING: {description} STDERR: {result.stderr.strip()}")
            return result.stdout, True
    except subprocess.TimeoutExpired:
        log(f"ERROR: {description} timed out after {timeout} seconds")
        return "", False
    except FileNotFoundError:
        log(f"ERROR: {description} command not found: {cmd_parts[0]}")
        return "", False
    except Exception as e:
        log(f"CRITICAL ERROR during {description}: {e}")
        return "", False

def _interface_exists(interface):
    """Checks if an interface exists."""
    stdout, success = _run_command(['ip', 'link', 'show', interface], f"check existence {interface}")
    return success

def _is_in_monitor_mode(interface):
    """Checks if an interface is in monitor mode."""
    stdout, success = _run_command(['iwconfig', interface], f"check mode {interface}")
    return success and 'Mode:Monitor' in stdout

def activate_monitor_mode(interface):
    """
    Activates monitor mode on the specified interface.
    Returns the name of the monitor interface (e.g., wlan0mon) or None on failure.
    """
    log(f"Attempting to activate monitor mode on {interface}...")
    
    # Check for onboard Raspberry Pi WiFi (Broadcom 43430)
    driver_check_cmd = ['sudo', 'ethtool', '-i', interface]
    stdout, success = _run_command(driver_check_cmd, f"check driver for {interface}")
    if success and "brcmfmac" in stdout:
        log("DETECTED: Onboard Raspberry Pi WiFi (Broadcom 43430) - Monitor mode not reliably supported.")
        return None # Indicate failure for onboard WiFi

    # 1. Stop conflicting services
    log("Stopping NetworkManager and wpa_supplicant...")
    _run_command(['sudo', 'systemctl', 'stop', 'NetworkManager'], "stop NetworkManager")
    _run_command(['sudo', 'systemctl', 'stop', 'wpa_supplicant'], "stop wpa_supplicant")
    time.sleep(1) # Give services time to stop

    # 2. Kill interfering processes
    log("Killing interfering processes with airmon-ng check kill...")
    _run_command(['sudo', 'airmon-ng', 'check', 'kill'], "airmon-ng check kill")
    time.sleep(1)

    # 3. Bring interface down
    log(f"Bringing {interface} down...")
    _run_command(['sudo', 'ip', 'link', 'set', interface, 'down'], f"bring {interface} down")
    time.sleep(1)

    # 4. Try airmon-ng to start monitor mode
    log(f"Trying airmon-ng start {interface}...")
    stdout, success = _run_command(['sudo', 'airmon-ng', 'start', interface], f"airmon-ng start {interface}", timeout=20)
    
    monitor_interface = None
    if success:
        # airmon-ng usually outputs the new monitor interface name
        match = re.search(r'\(monitor mode enabled on (.*?)\)', stdout)
        if match:
            monitor_interface = match.group(1)
            log(f"airmon-ng successfully created monitor interface: {monitor_interface}")
        else:
            # Fallback if output format changes, try to guess
            log("Could not parse monitor interface name from airmon-ng output, trying to guess...")
            if interface.endswith('mon'):
                monitor_interface = interface
            else:
                monitor_interface = interface + 'mon' # Common naming convention
            log(f"Guessed monitor interface name: {monitor_interface}")
    
    if not monitor_interface or not _interface_exists(monitor_interface):
        log(f"airmon-ng failed or monitor interface not found. Trying iwconfig...")
        # Fallback to iwconfig
        _run_command(['sudo', 'iwconfig', interface, 'mode', 'monitor'], f"iwconfig {interface} mode monitor")
        monitor_interface = interface # iwconfig usually renames the original interface
        
        if not _interface_exists(monitor_interface) or not _is_in_monitor_mode(monitor_interface):
            log(f"Failed to activate monitor mode on {interface} using iwconfig.")
            return None

    # 5. Bring the monitor interface up
    log(f"Bringing {monitor_interface} up...")
    _run_command(['sudo', 'ip', 'link', 'set', monitor_interface, 'up'], f"bring {monitor_interface} up")
    time.sleep(1)
    
    log(f"Monitor mode activated on {monitor_interface}")
    return monitor_interface

def deactivate_monitor_mode(monitor_interface):
    """
    Deactivates monitor mode on the specified interface and restores original state.
    Returns True on success, False on failure.
    """
    log(f"Attempting to deactivate monitor mode on {monitor_interface}...")
    
    original_interface = monitor_interface.replace('mon', '') if monitor_interface.endswith('mon') else monitor_interface

    # 1. Bring monitor interface down
    log(f"Bringing {monitor_interface} down...")
    _run_command(['sudo', 'ip', 'link', 'set', monitor_interface, 'down'], f"bring {monitor_interface} down")
    time.sleep(1)

    # 2. Try airmon-ng stop
    log(f"Trying airmon-ng stop {monitor_interface}...")
    _run_command(['sudo', 'airmon-ng', 'stop', monitor_interface], f"airmon-ng stop {monitor_interface}", timeout=20)
    time.sleep(1)
    
    # 3. Restore original interface mode if it still exists
    if _interface_exists(original_interface):
        log(f"Restoring {original_interface} to managed mode...")
        _run_command(['sudo', 'iwconfig', original_interface, 'mode', 'managed'], f"iwconfig {original_interface} mode managed")
        _run_command(['sudo', 'ip', 'link', 'set', original_interface, 'up'], f"bring {original_interface} up")
        
        # Attempt to restart NetworkManager for the original interface
        log(f"Attempting to restart NetworkManager for {original_interface}...")
        _run_command(['sudo', 'nmcli', 'device', 'set', original_interface, 'managed', 'yes'], f"set {original_interface} managed")
        _run_command(['sudo', 'nmcli', 'device', 'connect', original_interface], f"connect {original_interface}")
            
    # 4. Restart conflicting services
    log("Restarting NetworkManager and wpa_supplicant...")
    _run_command(['sudo', 'systemctl', 'start', 'NetworkManager'], "start NetworkManager")
    _run_command(['sudo', 'systemctl', 'start', 'wpa_supplicant'], "start wpa_supplicant")
    time.sleep(2) # Give services time to start

    log(f"Monitor mode deactivated on {monitor_interface}")
    return True