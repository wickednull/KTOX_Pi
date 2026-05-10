# 🔥 KTOX Kali Pentest Suite - Quick Start Guide 🔥

## Launch

```bash
cd /root/KTOx/payloads/offensive
python3 kali_pentest_webui.py
```

Access at: **http://127.0.0.1:9000** (or your configured HOST/PORT)

## First Steps

### 1. Create an Engagement
```bash
curl -X POST http://localhost:9000/api/engagements \
  -H "Content-Type: application/json" \
  -d '{
    "id": "acme_2024",
    "name": "ACME Corp Pentest",
    "scope": "192.168.0.0/24\n10.0.0.0/8\nacme.com"
  }'
```

### 2. Store Credentials (Optional)
```bash
curl -X POST http://localhost:9000/api/vault/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "name": "admin_ssh",
    "type": "password",
    "username": "admin",
    "password": "MyPassword123"
  }'
```

### 3. Run a Tool
**Via UI:** Navigate to Nmap section, enter target, click "Run Nmap"

**Via API:**
```bash
curl -X POST http://localhost:9000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "nmap",
    "engagement_id": "acme_2024",
    "params": {
      "target": "192.168.1.1",
      "scan_type": "quick"
    }
  }'
```

Response:
```json
{"success": true, "job_id": "550e8400-e29b-41d4-a716-446655440000"}
```

### 4. Stream Job Output
```bash
curl -N http://localhost:9000/api/jobs/550e8400-e29b-41d4-a716-446655440000/stream
```

### 5. View Findings
```bash
curl http://localhost:9000/api/findings?engagement_id=acme_2024
```

### 6. Generate Report
```bash
# HTML report
curl http://localhost:9000/api/reports/acme_2024/html > report.html

# JSON export
curl http://localhost:9000/api/reports/acme_2024/json > report.json

# CSV for spreadsheets
curl http://localhost:9000/api/reports/acme_2024/csv > findings.csv
```

## Tools By Category

### Reconnaissance (5 tools)
- `nmap` — Port scanning
- `masscan` — Ultra-fast scanning
- `gobuster` — Directory enumeration
- `ffuf` — Web fuzzing
- `searchsploit` — Exploit search

### Web Application (6 tools)
- `nikto` — Web server scanner
- `wpscan` — WordPress scanner
- `sqlmap` — SQL injection tester
- `feroxbuster` — Recursive fuzzer
- `gobuster` — Web enumeration
- `ffuf` — Fast fuzzer

### Credential Attacks (6 tools)
- `hydra` — Brute force
- `hashcat` — GPU cracking
- `john` — CPU cracking
- `crackmapexec` — SMB lateral movement
- `impacket-secretsdump` — Extract NTLM hashes
- `impacket-psexec` — Remote execution

### Wireless (3 tools)
- `aircrack-ng` — WiFi password cracking
- `wifite` — Automated WiFi attacks
- `responder` — LLMNR spoofing

### MITM / Interception (3 tools)
- `bettercap` — ARP spoofing, DNS hijacking
- `responder` — Credential capture
- `tcpdump` — Packet capture

### Exploitation (3 tools)
- `msfvenom` — Payload generation
- `searchsploit` — Exploit search
- `impacket-psexec` — Remote code execution

## Common Workflows

### Recon → Exploitation Chain
```
1. Run Nmap scan          (identify open ports)
2. Run Nikto scan         (identify web servers)
3. Run SQLmap scan        (test SQL injection)
4. Run Hydra brute force  (credentials)
5. Run msfvenom payload   (exploitation)
6. Export HTML report     (findings)
```

### WiFi Attack Workflow
```
1. Run Wifite2            (target selection + auto-crack)
   OR
2. Run Aircrack-ng        (manual password cracking)
3. Export findings        (password + BSSID)
```

### Lateral Movement (Windows)
```
1. Run CrackMapExec       (enumerate SMB)
2. Run Impacket Secrets   (extract hashes)
3. Run Hydra              (crack hashes)
4. Run Impacket PSExec    (remote execution)
```

## Database Locations

- **Findings**: `/root/KTOx/loot/kali_pentest/pentest.db`
- **Job logs**: `/root/KTOx/loot/kali_pentest/jobs/<job_id>/output.log`
- **Artifacts**: `/root/KTOx/loot/kali_pentest/jobs/<job_id>/`
- **Vault**: `/root/KTOx/loot/kali_pentest/vault.db`

## Troubleshooting

### Port already in use
```bash
KALI_PENTEST_PORT=9001 python3 kali_pentest_webui.py
```

### Tool not found
```bash
apt update && apt install -y nmap hydra gobuster masscan
```

### Permission denied
```bash
sudo python3 kali_pentest_webui.py
```

### Database locked
```bash
rm /root/KTOx/loot/kali_pentest/pentest.db
# DB recreates on restart
```

## Key Features

✅ **22 Kali tools** wrapped with proper subprocess handling  
✅ **Server-Sent Events** streaming for real-time output  
✅ **Scope enforcement** prevents out-of-scope targeting  
✅ **Credential vault** with audit trail  
✅ **Multi-format reports** (HTML, JSON, CSV, Text)  
✅ **Job management** with UUID tracking  
✅ **SQLite persistence** for findings  
✅ **Cyberpunk UI** matching KTOX aesthetic  
✅ **LCD display** integration for hardware status  
✅ **API-first design** for automation  

## Advanced Usage

### Automate with cURL
```bash
#!/bin/bash
TARGET="192.168.1.1"
ENGAGEMENT="auto_$(date +%s)"

# Create engagement
curl -X POST http://localhost:9000/api/engagements \
  -d "{\"id\":\"$ENGAGEMENT\",\"name\":\"Auto Scan\",\"scope\":\"$TARGET\"}"

# Run Nmap
curl -X POST http://localhost:9000/api/jobs \
  -d "{\"tool\":\"nmap\",\"engagement_id\":\"$ENGAGEMENT\",\"params\":{\"target\":\"$TARGET\"}}"

# Generate report when done
sleep 30  # Wait for job completion
curl http://localhost:9000/api/reports/$ENGAGEMENT/html > /tmp/report.html
```

### Custom Tool Wrapper
See `KALI_PENTEST_README.md` for implementing new tool runners.

## API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/status` | GET | System status |
| `/api/tools` | GET | List available tools |
| `/api/jobs` | GET/POST | List/create jobs |
| `/api/jobs/<id>/stream` | GET | Stream job output (SSE) |
| `/api/jobs/<id>/stop` | POST | Stop running job |
| `/api/findings` | GET | List findings with filters |
| `/api/findings/summary` | GET | Summary statistics |
| `/api/reports/<id>/<fmt>` | GET | Download report |
| `/api/vault/credentials` | GET/POST | Credential management |
| `/api/engagements` | GET/POST | Engagement management |

## Environment Variables

```bash
KALI_PENTEST_HOST=0.0.0.0          # Bind address
KALI_PENTEST_PORT=9000             # Port
KTOX_ROOT=/root/KTOx               # KTOX installation path
```

## Performance Tips

- Use **quick** scans for speed, **full** scans for thoroughness
- Set **rate limits** on Masscan/FFUF to avoid network issues
- Use **threads** parameter on Hydra (4-8 for safe brute force)
- Store **large wordlists** in /root/wordlists/ for quick access
- Use **credential vault** to avoid re-entering passwords

---

**Ready to pentest?** Navigate to **http://127.0.0.1:9000** and start orchestrating!
