#!/usr/bin/env python3
# -.- coding: utf-8 -.-
# ktox_dashboard.py — KTOx Live Web Dashboard
# Blood-red cyberpunk browser UI — access at http://localhost:9999

import os, sys, json, time, threading
from datetime import datetime

try:
    from flask import Flask, render_template_string, jsonify, request, Response
except ImportError:
    print("ERROR: pip3 install flask"); sys.exit(1)

import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ── Shared state (populated by engine modules) ─────────────────────────────
dashboard_state = {
    "started":      None,
    "iface":        "—",
    "attacker_ip":  "—",
    "gateway_ip":   "—",
    "hosts":        [],
    "credentials":  [],
    "cookies":      [],
    "dns_queries":  [],
    "ntlm_hashes":  [],
    "sessions":     [],
    "http_requests":[],
    "pcap_file":    None,
    "active_modules": [],
    "events":       [],   # rolling log
}

_event_lock = threading.Lock()

def push_event(event_type, data):
    """Push an event to the dashboard."""
    entry = {
        "ts":   datetime.now().strftime("%H:%M:%S"),
        "type": event_type,
        "data": data
    }
    with _event_lock:
        dashboard_state["events"].insert(0, entry)
        if len(dashboard_state["events"]) > 500:
            dashboard_state["events"] = dashboard_state["events"][:500]

        # Also add to specific lists
        if event_type in ("CREDENTIAL", "JS_CREDS", "HTTP_BASIC_AUTH",
                          "FTP_CRED", "SMTP_AUTH", "POP3_CRED", "IMAP_CRED",
                          "IRC_PASS", "REDIS_AUTH", "TELNET_DATA"):
            dashboard_state["credentials"].insert(0, {**entry, "ts": entry["ts"]})
            dashboard_state["credentials"] = dashboard_state["credentials"][:200]

        elif event_type in ("JS_COOKIE", "COOKIE"):
            dashboard_state["cookies"].insert(0, entry)
            dashboard_state["cookies"] = dashboard_state["cookies"][:200]

        elif event_type == "DNS_QUERY":
            dashboard_state["dns_queries"].insert(0, entry)
            dashboard_state["dns_queries"] = dashboard_state["dns_queries"][:500]

        elif event_type == "NTLM_HASH":
            dashboard_state["ntlm_hashes"].insert(0, entry)

        elif event_type == "SESSION_HIJACK":
            dashboard_state["sessions"].insert(0, entry)
            dashboard_state["sessions"] = dashboard_state["sessions"][:100]

        elif event_type == "HTTP_REQUEST":
            dashboard_state["http_requests"].insert(0, entry)
            dashboard_state["http_requests"] = dashboard_state["http_requests"][:300]

# ── Dashboard HTML ────────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KTOx Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
:root {
  --blood:#C0392B; --ember:#E74C3C; --rust:#7B241C;
  --dark:#070707; --panel:#0F0F0F; --card:#141414;
  --border:#1E0806; --ash:#6E6E6E; --dim:#2A2A2A;
  --white:#F0F0F0; --green:#1E8449; --yellow:#D4AC0D;
  --orange:#CA6F1E; --mono:'Share Tech Mono',monospace;
  --head:'Orbitron',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--dark);color:var(--white);font-family:var(--mono);font-size:12px;overflow-x:hidden;}
body::before{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.06) 2px,rgba(0,0,0,0.06) 4px);pointer-events:none;z-index:999;}

/* NAV */
nav{position:sticky;top:0;z-index:100;background:rgba(7,7,7,0.97);border-bottom:1px solid var(--rust);display:flex;align-items:center;justify-content:space-between;padding:0 1.5rem;height:48px;}
.brand{font-family:var(--head);font-size:1rem;color:var(--blood);letter-spacing:.15em;}
.nav-info{display:flex;gap:1.5rem;}
.nav-badge{display:flex;gap:.4rem;align-items:center;}
.nav-badge span:first-child{color:var(--blood);font-size:.65rem;letter-spacing:.1em;}
.nav-badge span:last-child{color:var(--ash);}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.3;}}

/* GRID */
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--rust);padding:1px;margin:1px;}
.stat-card{background:var(--panel);padding:1rem;text-align:center;}
.stat-num{font-family:var(--head);font-size:1.8rem;color:var(--blood);}
.stat-label{color:var(--ash);font-size:.65rem;letter-spacing:.15em;margin-top:.3rem;}

/* MAIN LAYOUT */
.main{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--rust);margin:1px;}
.panel-full{grid-column:1/-1;}

/* PANELS */
.panel{background:var(--card);display:flex;flex-direction:column;}
.panel-header{background:var(--panel);padding:.6rem 1rem;border-bottom:1px solid var(--rust);display:flex;align-items:center;gap:.6rem;}
.panel-title{color:var(--blood);font-size:.75rem;letter-spacing:.12em;}
.panel-count{background:var(--rust);color:var(--white);padding:.1rem .4rem;font-size:.65rem;border-radius:2px;}
.panel-body{flex:1;overflow-y:auto;max-height:300px;padding:.5rem;}

/* TABLE */
table{width:100%;border-collapse:collapse;}
th{color:var(--blood);text-align:left;padding:.3rem .5rem;font-size:.65rem;letter-spacing:.1em;border-bottom:1px solid var(--rust);position:sticky;top:0;background:var(--card);}
td{padding:.3rem .5rem;border-bottom:1px solid #1a1a1a;color:var(--ash);font-size:.7rem;word-break:break-all;}
tr:hover td{background:var(--panel);}
.val-red{color:var(--ember);}
.val-green{color:var(--green);}
.val-yellow{color:var(--yellow);}
.val-white{color:var(--white);}
.val-dim{color:#444;}

/* EVENT LOG */
.log-line{padding:.2rem .5rem;border-bottom:1px solid #111;font-size:.7rem;display:flex;gap:.8rem;align-items:baseline;}
.log-ts{color:var(--dim);white-space:nowrap;min-width:56px;}
.log-type{min-width:90px;font-size:.65rem;}
.log-data{color:var(--ash);word-break:break-all;}
.log-cred{color:var(--ember);}
.log-ntlm{color:var(--blood);}
.log-session{color:var(--yellow);}
.log-dns{color:var(--ash);}
.log-http{color:#555;}
.log-info{color:var(--green);}

/* MODULES */
.module-grid{display:flex;flex-wrap:wrap;gap:.5rem;padding:.8rem;}
.mod-badge{padding:.3rem .8rem;border:1px solid;font-size:.65rem;letter-spacing:.1em;}
.mod-active{border-color:var(--green);color:var(--green);}
.mod-off{border-color:#222;color:#333;}

/* SCROLLBAR */
::-webkit-scrollbar{width:4px;}
::-webkit-scrollbar-track{background:#0a0a0a;}
::-webkit-scrollbar-thumb{background:var(--rust);}

/* RESPONSIVE */
@media(max-width:700px){
  .main{grid-template-columns:1fr;}
  .grid{grid-template-columns:repeat(2,1fr);}
}
</style>
</head>
<body>

<nav>
  <div class="brand">▐ KTOX ▌</div>
  <div class="nav-info">
    <div class="nav-badge"><span>IFACE</span><span id="n-iface">—</span></div>
    <div class="nav-badge"><span>IP</span><span id="n-ip">—</span></div>
    <div class="nav-badge"><span>GW</span><span id="n-gw">—</span></div>
    <div class="nav-badge"><span>UPTIME</span><span id="n-uptime">00:00</span></div>
    <div class="nav-badge"><div class="status-dot"></div><span id="n-status" style="color:var(--green)">LIVE</span></div>
  </div>
</nav>

<!-- Stats row -->
<div class="grid">
  <div class="stat-card"><div class="stat-num" id="s-creds">0</div><div class="stat-label">CREDENTIALS</div></div>
  <div class="stat-card"><div class="stat-num" id="s-sessions">0</div><div class="stat-label">SESSIONS</div></div>
  <div class="stat-card"><div class="stat-num" id="s-ntlm">0</div><div class="stat-label">NTLM HASHES</div></div>
  <div class="stat-card"><div class="stat-num" id="s-dns">0</div><div class="stat-label">DNS QUERIES</div></div>
</div>

<!-- Active modules -->
<div class="panel" style="margin:1px;background:var(--card);">
  <div class="panel-header"><span class="panel-title">◈ ACTIVE MODULES</span></div>
  <div class="module-grid" id="modules"></div>
</div>

<!-- Main panels -->
<div class="main">

  <!-- Credentials -->
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title">◈ CREDENTIALS</span>
      <span class="panel-count" id="c-creds">0</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr><th>TIME</th><th>PROTO</th><th>SOURCE</th><th>DATA</th></tr></thead>
        <tbody id="t-creds"></tbody>
      </table>
    </div>
  </div>

  <!-- Session Cookies -->
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title">◈ SESSION HIJACKS</span>
      <span class="panel-count" id="c-sessions">0</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr><th>TIME</th><th>HOST</th><th>SRC</th><th>COOKIE</th></tr></thead>
        <tbody id="t-sessions"></tbody>
      </table>
    </div>
  </div>

  <!-- NTLM Hashes -->
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title">◈ NTLM HASHES</span>
      <span class="panel-count" id="c-ntlm">0</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr><th>TIME</th><th>PROTO</th><th>USER</th><th>HASH</th></tr></thead>
        <tbody id="t-ntlm"></tbody>
      </table>
    </div>
  </div>

  <!-- DNS -->
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title">◈ DNS QUERIES</span>
      <span class="panel-count" id="c-dns">0</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr><th>TIME</th><th>QUERY</th><th>SPOOFED</th></tr></thead>
        <tbody id="t-dns"></tbody>
      </table>
    </div>
  </div>

  <!-- HTTP Requests -->
  <div class="panel panel-full">
    <div class="panel-header">
      <span class="panel-title">◈ HTTP TRAFFIC</span>
      <span class="panel-count" id="c-http">0</span>
    </div>
    <div class="panel-body" style="max-height:180px;">
      <table>
        <thead><tr><th>TIME</th><th>METHOD</th><th>HOST</th><th>PATH</th><th>SRC</th></tr></thead>
        <tbody id="t-http"></tbody>
      </table>
    </div>
  </div>

  <!-- Event log -->
  <div class="panel panel-full">
    <div class="panel-header">
      <span class="panel-title">◈ EVENT LOG</span>
      <span class="panel-count" id="c-events">0</span>
    </div>
    <div class="panel-body" style="max-height:240px;" id="log-body"></div>
  </div>

</div>

<script>
var startTime = Date.now();

function uptime(){
  var s = Math.floor((Date.now()-startTime)/1000);
  var m = Math.floor(s/60); s = s%60;
  return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
}

function esc(s){
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function typeClass(t){
  if(['CREDENTIAL','JS_CREDS','FTP_CRED','SMTP_AUTH','POP3_CRED','IMAP_CRED','IRC_PASS','REDIS_AUTH'].includes(t)) return 'log-cred';
  if(t==='NTLM_HASH') return 'log-ntlm';
  if(t==='SESSION_HIJACK') return 'log-session';
  if(t==='DNS_QUERY'||t==='DNS_SPOOF') return 'log-dns';
  if(t==='HTTP_REQUEST') return 'log-http';
  return 'log-info';
}

function poll(){
  fetch('/api/state').then(r=>r.json()).then(d=>{

    // Nav
    document.getElementById('n-iface').textContent   = d.iface||'—';
    document.getElementById('n-ip').textContent      = d.attacker_ip||'—';
    document.getElementById('n-gw').textContent      = d.gateway_ip||'—';
    document.getElementById('n-uptime').textContent  = uptime();

    // Stats
    document.getElementById('s-creds').textContent   = d.credentials.length;
    document.getElementById('s-sessions').textContent= d.sessions.length;
    document.getElementById('s-ntlm').textContent    = d.ntlm_hashes.length;
    document.getElementById('s-dns').textContent     = d.dns_queries.length;

    // Module badges
    var mods = d.active_modules||[];
    document.getElementById('modules').innerHTML = mods.map(m=>
      `<div class="mod-badge mod-active">${esc(m)}</div>`
    ).join('') || '<div style="color:#333;padding:.5rem;font-size:.7rem;">No active modules</div>';

    // Credentials table
    document.getElementById('c-creds').textContent = d.credentials.length;
    document.getElementById('t-creds').innerHTML = d.credentials.slice(0,50).map(e=>`
      <tr>
        <td class="val-dim">${esc(e.ts)}</td>
        <td class="val-white">${esc(e.type)}</td>
        <td class="val-dim">${esc((e.data||{}).src||'')}</td>
        <td class="val-red">${esc(JSON.stringify(e.data||{}).slice(0,120))}</td>
      </tr>`).join('');

    // Sessions table
    document.getElementById('c-sessions').textContent = d.sessions.length;
    document.getElementById('t-sessions').innerHTML = d.sessions.slice(0,30).map(e=>{
      var dat = e.data||{};
      return `<tr>
        <td class="val-dim">${esc(e.ts)}</td>
        <td class="val-white">${esc(dat.host||'')}</td>
        <td class="val-dim">${esc(dat.src||'')}</td>
        <td class="val-yellow">${esc((dat.cookie||'').slice(0,80))}</td>
      </tr>`;
    }).join('');

    // NTLM table
    document.getElementById('c-ntlm').textContent = d.ntlm_hashes.length;
    document.getElementById('t-ntlm').innerHTML = d.ntlm_hashes.slice(0,20).map(e=>{
      var dat = e.data||{};
      return `<tr>
        <td class="val-dim">${esc(e.ts)}</td>
        <td class="val-white">${esc(dat.proto||'')}</td>
        <td class="val-green">${esc(dat.domain+'\\\\'+(dat.username||''))}</td>
        <td class="val-red">${esc((dat.nt_hash||'').slice(0,40))}...</td>
      </tr>`;
    }).join('');

    // DNS table
    document.getElementById('c-dns').textContent = d.dns_queries.length;
    document.getElementById('t-dns').innerHTML = d.dns_queries.slice(0,50).map(e=>{
      var dat = e.data||{};
      return `<tr>
        <td class="val-dim">${esc(e.ts)}</td>
        <td class="val-white">${esc(dat.query||'')}</td>
        <td class="${dat.spoofed?'val-red':'val-dim'}">${esc(dat.spoofed||'pass')}</td>
      </tr>`;
    }).join('');

    // HTTP table
    document.getElementById('c-http').textContent = d.http_requests.length;
    document.getElementById('t-http').innerHTML = d.http_requests.slice(0,40).map(e=>{
      var dat = e.data||{};
      return `<tr>
        <td class="val-dim">${esc(e.ts)}</td>
        <td class="val-red">${esc(dat.method||'')}</td>
        <td class="val-white">${esc(dat.host||'')}</td>
        <td class="val-dim">${esc((dat.path||'').slice(0,60))}</td>
        <td class="val-dim">${esc(dat.src||'')}</td>
      </tr>`;
    }).join('');

    // Event log
    document.getElementById('c-events').textContent = d.events.length;
    var lb = document.getElementById('log-body');
    lb.innerHTML = d.events.slice(0,100).map(e=>`
      <div class="log-line">
        <span class="log-ts">${esc(e.ts)}</span>
        <span class="log-type ${typeClass(e.type)}">${esc(e.type)}</span>
        <span class="log-data">${esc(JSON.stringify(e.data||{}).slice(0,120))}</span>
      </div>`).join('');

  }).catch(()=>{});
}

setInterval(poll, 1500);
poll();
</script>
</body>
</html>"""

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/state")
def state():
    return jsonify(dashboard_state)

@app.route("/api/event", methods=["POST"])
def recv_event():
    data = request.get_json(silent=True) or {}
    push_event(data.get("type","INFO"), data.get("data",{}))
    return jsonify({"ok": True})

@app.route("/api/clear", methods=["POST"])
def clear():
    for key in ("credentials","cookies","dns_queries","ntlm_hashes",
                "sessions","http_requests","events"):
        dashboard_state[key] = []
    return jsonify({"ok": True})


def start_dashboard(port=9999, iface="—", attacker_ip="—",
                    gateway_ip="—", active_modules=None):
    """Start the dashboard in a background thread."""
    dashboard_state["started"]        = datetime.now().isoformat()
    dashboard_state["iface"]          = iface
    dashboard_state["attacker_ip"]    = attacker_ip
    dashboard_state["gateway_ip"]     = gateway_ip
    dashboard_state["active_modules"] = active_modules or []

    def _run():
        app.run(host="0.0.0.0", port=port,
                debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    print(f"KTOx Dashboard starting on http://0.0.0.0:9999")
    start_dashboard()
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        pass
