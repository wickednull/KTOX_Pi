(function(){
  const DEBUG = false;
  const log = (...args) => { if (DEBUG) console.log('[KTOx]', ...args); };
  const warn = (...args) => { if (DEBUG) console.warn('[KTOx]', ...args); };

  const shared = window.RJShared || {};

  // DOM Cache System - lazy initialization to reduce startup overhead
  const DOM = {
    _cache: {},
    _listeners: [],

    get(id) {
      if (!this._cache[id]) {
        const el = document.getElementById(id);
        if (el) this._cache[id] = el;
        return el;
      }
      return this._cache[id];
    },

    all(selector) {
      return Array.from(document.querySelectorAll(selector));
    },

    on(el, event, handler) {
      if (!el) return;
      el.addEventListener(event, handler);
      this._listeners.push({ el, event, handler });
    },

    off(el, event, handler) {
      if (!el) return;
      el.removeEventListener(event, handler);
      this._listeners = this._listeners.filter(l => !(l.el === el && l.event === event && l.handler === handler));
    },

    cleanup() {
      this._listeners.forEach(({ el, event, handler }) => {
        try { el.removeEventListener(event, handler); } catch(e) {}
      });
      this._listeners = [];
    }
  };

  // Mobile detection utilities
  const Mobile = {
    isMobile: () => window.matchMedia('(max-width: 768px)').matches,
    isSmallPhone: () => window.matchMedia('(max-width: 480px)').matches,
    isPortrait: () => window.matchMedia('(orientation: portrait)').matches,
    isLandscape: () => window.matchMedia('(orientation: landscape)').matches,

    onOrientationChange(callback) {
      window.addEventListener('orientationchange', callback);
      window.matchMedia('(orientation: portrait)').addEventListener('change', callback);
    }
  };

  // Utility functions
  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function encodeData(value) {
    return encodeURIComponent(value || '');
  }

  function decodeData(value) {
    try { return decodeURIComponent(value || ''); } catch { return value || ''; }
  }

  function formatBytes(bytes) {
    const b = Number(bytes || 0);
    if (b === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return (b / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
  }

  function formatDuration(totalSec) {
    const s = Number(totalSec || 0);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return (d > 0 ? `${d}d ` : '') + (h > 0 ? `${h}h ` : '') + (m > 0 ? `${m}m ` : '') + `${sec}s`;
  }

  function formatTime(timestamp) {
    const t = Number(timestamp || 0);
    if (t === 0) return '-';
    return new Date(t * 1000).toLocaleString();
  }

  function pct(used, total) {
    return total > 0 ? (used / total) * 100 : 0;
  }

  function bar(el, value) {
    if (el) el.style.width = Math.max(0, Math.min(100, value)).toFixed(1) + '%';
  }

  // Debounce helper for resize and input events
  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  // Touch/Swipe gesture detection for mobile navigation
  const GestureHandler = {
    startX: 0,
    startY: 0,
    threshold: 50,

    onSwipeLeft: null,
    onSwipeRight: null,

    init() {
      document.addEventListener('touchstart', (e) => {
        const touch = e.touches[0];
        this.startX = touch.clientX;
        this.startY = touch.clientY;
      });

      document.addEventListener('touchend', (e) => {
        if (!this.startX) return;
        const touch = e.changedTouches[0];
        const diffX = this.startX - touch.clientX;
        const diffY = Math.abs(this.startY - touch.clientY);

        if (diffY > 50) { this.startX = 0; return; } // Vertical swipe

        if (diffX > this.threshold && this.onSwipeLeft) this.onSwipeLeft();
        else if (diffX < -this.threshold && this.onSwipeRight) this.onSwipeRight();

        this.startX = 0;
      });
    }
  };

  // Canvas setup with Hi-DPI support
  let canvas, canvasGb, canvasPager, canvasSyndicate;
  let ctx, ctxGb, ctxPager, ctxSyndicate;

  function setupCanvases() {
    canvas = DOM.get('screen');
    canvasGb = DOM.get('screen-gb');
    canvasPager = DOM.get('screen-pager');
    canvasSyndicate = DOM.get('screen-syndicate');

    if (!canvas) return;
    ctx = canvas.getContext('2d');
    ctxGb = canvasGb ? canvasGb.getContext('2d') : null;
    ctxPager = canvasPager ? canvasPager.getContext('2d') : null;
    ctxSyndicate = canvasSyndicate ? canvasSyndicate.getContext('2d') : null;
  }

  function setupHiDPI() {
    if (!canvas) return;
    const DPR = Math.max(1, Math.floor(window.devicePixelRatio || 1));
    const logical = 128;

    for (const c of [canvas, canvasGb, canvasPager, canvasSyndicate]) {
      if (!c) continue;
      c.width = logical * DPR;
      c.height = logical * DPR;
      const ctxLocal = c.getContext('2d');
      if (ctxLocal) {
        ctxLocal.imageSmoothingEnabled = true;
        try { ctxLocal.imageSmoothingQuality = 'high'; } catch(e) {}
      }
    }
  }

  setupCanvases();
  setupHiDPI();
  DOM.on(window, 'resize', debounce(setupHiDPI, 200));

  // Auth management
  let authToken = '';
  let wsTicket = '';
  let wsAuthenticated = false;
  let authPromiseResolve = null;

  function saveAuthToken(token) {
    authToken = token;
    try {
      localStorage.setItem('ktox_token', JSON.stringify({ token, time: Date.now() }));
    } catch(e) {}
  }

  function loadAuthToken() {
    try {
      const stored = localStorage.getItem('ktox_token');
      if (stored) {
        const obj = JSON.parse(stored);
        const maxAge = 7 * 24 * 60 * 60 * 1000;
        if (Date.now() - obj.time < maxAge) {
          authToken = obj.token || '';
          return authToken;
        }
        localStorage.removeItem('ktox_token');
      }
    } catch(e) {}
    return '';
  }

  loadAuthToken();

  function getManualWsUrl() {
    try {
      return localStorage.getItem('ktox_ws_override') || '';
    } catch(e) {
      return '';
    }
  }

  function setManualWsUrl(url) {
    try {
      if (url) localStorage.setItem('ktox_ws_override', url);
      else localStorage.removeItem('ktox_ws_override');
    } catch(e) {}
  }

  // WebSocket connection management
  let ws = null;
  let wsCandidates = [];
  let wsCandidateIndex = 0;
  let connectTimeoutTimer = null;
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  let lastServerMessage = Date.now();

  const WS_CONNECT_TIMEOUT = 5000;
  const AUTH_TICKET_REFRESH_INTERVAL = 4 * 60 * 1000;
  const SERVER_HEARTBEAT_TIMEOUT = 45000;
  const HEARTBEAT_CHECK_INTERVAL = 15000;
  const REQUEST_MAX_BYTES = 10 * 1024 * 1024;

  function getWsCandidates() {
    const candidates = [];
    const manualUrl = getManualWsUrl();
    if (manualUrl) candidates.push(manualUrl);

    if (shared.getWsUrlCandidates) {
      const fromShared = shared.getWsUrlCandidates(location);
      if (Array.isArray(fromShared) && fromShared.length) {
        candidates.push(...fromShared.map(v => String(v || '').trim()).filter(Boolean));
      }
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    candidates.push(`${proto}//${location.host}/ws`);

    return candidates.filter((v, i, a) => a.indexOf(v) === i);
  }

  function getApiUrl(path, params = {}) {
    const p = new URLSearchParams(params);
    return `/api${path}${p.size > 0 ? '?' + p : ''}`;
  }

  function getForwardSearch() {
    return location.search ? location.search : '';
  }

  async function apiFetch(url, options = {}) {
    const headers = { ...options.headers, ...authHeaders() };
    return fetch(url, { ...options, headers });
  }

  function authHeaders(extra = {}) {
    const h = { 'Content-Type': 'application/json', ...extra };
    if (authToken) h['Authorization'] = `Bearer ${authToken}`;
    if (wsTicket) h['X-WebSocket-Ticket'] = wsTicket;
    return h;
  }

  // Status updates
  function setStatus(txt) {
    const statusEl = DOM.get('status');
    if (statusEl) {
      const raw = txt || '';
      statusEl.innerHTML = escapeHtml(raw);
      applyStatusTone(statusEl, raw);
    }
    for (const el of DOM.all('.status-text')) {
      el.innerHTML = escapeHtml(txt || '');
      applyStatusTone(el, txt || '');
    }
  }

  function applyStatusTone(el, txt) {
    const t = String(txt || '').toLowerCase();
    el.classList.remove('text-green-400', 'text-red-500', 'text-yellow-400');
    if (t.includes('error') || t.includes('failed')) el.classList.add('text-red-500');
    else if (t.includes('connecting')) el.classList.add('text-yellow-400');
    else if (t.includes('connected') || t.includes('ok') || t.includes('ready')) el.classList.add('text-green-400');
  }

  // Modal and UI management
  let activeTab = 'device';
  let shellOpen = false;
  let shellWanted = false;
  let systemOpen = false;
  let term = null;
  let fitAddon = null;
  let terminalHasFocus = false;
  let pressed = new Set();

  function closeSidebar() {
    const sidebar = DOM.get('sidebar');
    const backdrop = DOM.get('sidebarBackdrop');
    if (sidebar) sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('visible');
  }

  function setSidebarOpen(open) {
    const sidebar = DOM.get('sidebar');
    const backdrop = DOM.get('sidebarBackdrop');
    if (open) {
      if (sidebar) sidebar.classList.add('open');
      if (backdrop) backdrop.classList.add('visible');
    } else {
      if (sidebar) sidebar.classList.remove('open');
      if (backdrop) backdrop.classList.remove('visible');
    }
  }

  function setNavActive(btn, active) {
    if (btn) {
      if (active) btn.classList.add('active');
      else btn.classList.remove('active');
    }
  }

  function setActiveTab(tab) {
    const prevTab = activeTab;
    activeTab = tab;

    const tabs = ['device', 'system', 'loot', 'settings', 'terminal'];
    for (const t of tabs) {
      const el = DOM.get(t + 'Tab');
      if (el) el.classList.toggle('hidden', t !== tab);
    }

    // Update nav buttons
    for (const btnId of ['navDevice', 'navSystem', 'navLoot', 'navSettings']) {
      const btn = DOM.get(btnId);
      const isActive = (btnId === 'nav' + tab.charAt(0).toUpperCase() + tab.slice(1));
      setNavActive(btn, isActive);
    }

    // Auto-close sidebar on mobile when navigating
    if (Mobile.isMobile()) closeSidebar();

    // Apply responsive classes
    applyResponsiveTabClasses(tab);

    // Handle terminal-specific setup
    if (tab === 'terminal' && fitAddon) {
      requestAnimationFrame(() => { try { fitAddon.fit(); } catch(e) {} });
    }
  }

  function applyResponsiveTabClasses(tab) {
    const deviceTab = DOM.get('deviceTab');
    const systemStatus = DOM.get('systemStatus');

    if (Mobile.isMobile()) {
      if (deviceTab) deviceTab.style.display = tab === 'device' ? 'block' : 'none';
      if (systemStatus) systemStatus.style.display = tab === 'system' ? 'block' : 'none';
    } else {
      if (deviceTab) deviceTab.style.display = 'block';
    }
  }

  function setSystemOpen(open) {
    systemOpen = open;
    const dropdown = DOM.get('systemDropdown');
    if (dropdown) {
      if (open) {
        dropdown.classList.remove('hidden');
        dropdown.style.display = 'block';
      } else {
        dropdown.classList.add('hidden');
        dropdown.style.display = 'none';
      }
    }
  }

  function setLayoutVisible(el, visible) {
    if (el) el.style.display = visible ? 'block' : 'none';
  }

  // Theme management
  let currentTheme = 'neon';

  function loadThemePreference() {
    try {
      const saved = localStorage.getItem('ktox_theme');
      if (saved) currentTheme = saved;
    } catch(e) {}
    applyTheme();
  }

  function saveThemePreference(themeId) {
    currentTheme = themeId;
    try {
      localStorage.setItem('ktox_theme', themeId);
    } catch(e) {}
    applyTheme();
  }

  function applyTheme() {
    document.body.className = document.body.className.replace(/theme-\w+/g, '') + ` theme-${currentTheme}`;
    const themeNameEl = DOM.get('themeName');
    if (themeNameEl) themeNameEl.textContent = currentTheme || 'neon';
  }

  function setThemeById(id) {
    if (id) saveThemePreference(id);
  }

  loadThemePreference();

  // Loot management
  let lootState = { path: '', parent: '' };

  function buildLootPath(base, name) {
    if (!base) return encodeData(name);
    return base.split('/').concat(name).map(p => encodeData(decodeData(p))).join('/');
  }

  function setLootPath(path) {
    const lootPathEl = DOM.get('lootPath');
    if (lootPathEl) lootPathEl.textContent = path ? `/${path}` : '/';
  }

  function updateLootUp() {
    const lootUpBtn = DOM.get('lootUp');
    if (lootUpBtn) lootUpBtn.disabled = !lootState.parent;
  }

  function isNmapLootXml(path, name) {
    return /\.xml$/i.test(name) && (path || '').toLowerCase().includes('nmap');
  }

  function setLootStatus(txt) {
    const el = DOM.get('lootStatus');
    if (el) el.innerHTML = escapeHtml(txt);
    applyStatusTone(el, txt);
  }

  // Payload management
  let payloadState = { open: {} };

  function setPayloadStatus(txt) {
    const el = DOM.get('payloadStatus');
    if (el) {
      el.innerHTML = escapeHtml(txt);
      applyStatusTone(el, txt);
    }
    const dot = DOM.get('payloadStatusDot');
    if (dot) {
      dot.classList.remove('bg-red-500', 'bg-green-400', 'bg-yellow-400');
      const t = String(txt || '').toLowerCase();
      if (t.includes('error') || t.includes('failed')) dot.classList.add('bg-red-500');
      else if (t.includes('running')) dot.classList.add('bg-green-400');
      else dot.classList.add('bg-yellow-400');
    }
  }

  // System monitoring
  let systemMonitorTimer = null;

  function setSystemStatus(txt) {
    const el = DOM.get('systemStatus');
    if (el) {
      el.innerHTML = escapeHtml(txt);
      applyStatusTone(el, txt);
    }
  }

  // Shell management
  let shellStatusEl = DOM.get('shellStatus');

  function setShellStatus(txt) {
    if (shellStatusEl) {
      shellStatusEl.innerHTML = escapeHtml(txt);
      applyStatusTone(shellStatusEl, txt);
    }
  }

  function ensureTerminal() {
    if (term) return;
    const terminalEl = DOM.get('terminal');
    if (!terminalEl) return;

    try {
      term = new Terminal({ rows: 24, cols: 80 });
      term.open(terminalEl);

      if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        fitAddon.fit();
      }

      DOM.on(terminalEl, 'focusin', () => { terminalHasFocus = true; });
      DOM.on(terminalEl, 'focusout', () => { terminalHasFocus = false; });
      DOM.on(terminalEl, 'mousedown', () => { shellWanted = true; });
    } catch(e) {
      warn('Terminal init failed:', e);
    }
  }

  function sendShellInput(data) {
    if (ws && ws.readyState === WebSocket.OPEN && shellOpen) {
      try {
        ws.send(JSON.stringify({ type: 'shell_input', data }));
      } catch(e) {}
    }
  }

  function sendShellOpen() {
    shellWanted = true;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'shell_open' }));
        shellOpen = true;
        setShellStatus('Opening...');
      } catch(e) {}
    }
  }

  function sendShellClose() {
    shellWanted = false;
    if (ws && ws.readyState === WebSocket.OPEN && shellOpen) {
      try {
        ws.send(JSON.stringify({ type: 'shell_close' }));
      } catch(e) {}
    }
  }

  function sendShellResize() {
    if (!shellOpen || !fitAddon) return;
    try {
      const { cols, rows } = fitAddon.proposeDimensions();
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'shell_resize', cols, rows }));
      }
    } catch(e) {}
  }

  // Settings management
  function setSettingsStatus(txt) {
    const el = DOM.get('settingsStatus');
    if (el) {
      el.innerHTML = escapeHtml(txt);
      applyStatusTone(el, txt);
    }
  }

  function loadDiscordWebhook() {
    const el = DOM.get('discordWebhookInput');
    if (!el) return;
    try {
      const saved = localStorage.getItem('ktox_discord_webhook');
      if (saved) el.value = saved;
    } catch(e) {}
  }

  function saveDiscordWebhook(url) {
    try {
      localStorage.setItem('ktox_discord_webhook', url);
    } catch(e) {}
  }

  function getManualWsUrl() {
    try {
      return localStorage.getItem('ktox_ws_override') || '';
    } catch(e) {
      return '';
    }
  }

  function setManualWsUrl(url) {
    try {
      if (url) localStorage.setItem('ktox_ws_override', url);
      else localStorage.removeItem('ktox_ws_override');
    } catch(e) {}
  }

  // Tailscale management
  let tailscaleState = { installing: false };

  function setTailscaleStatus(txt) {
    const el = DOM.get('tailscaleSettingsStatus');
    if (el) {
      el.innerHTML = escapeHtml(txt);
      applyStatusTone(el, txt);
    }
  }

  function loadTailscaleSettings() {
    setTailscaleStatus('Loading...');
    apiFetch(getApiUrl('/api/tailscale/status'), { cache: 'no-store' })
      .then(r => r.json())
      .then(data => {
        setTailscaleStatus(data.status || 'Unknown');
      })
      .catch(e => setTailscaleStatus('Failed to load'));
  }

  function openTailscaleModal() {
    const modal = DOM.get('tailscaleModal');
    if (modal) modal.classList.remove('hidden');
  }

  function closeTailscaleModal() {
    const modal = DOM.get('tailscaleModal');
    if (modal) modal.classList.add('hidden');
  }

  // Loot preview modal
  function openPreview(opts) {
    const modal = DOM.get('lootPreview');
    const title = DOM.get('lootPreviewTitle');
    const body = DOM.get('lootPreviewBody');
    const meta = DOM.get('lootPreviewMeta');
    const dl = DOM.get('lootPreviewDownload');

    if (title) title.textContent = opts.title || '';
    if (meta) meta.textContent = opts.meta || '';
    if (body) {
      try {
        body.innerHTML = escapeHtml(opts.content || '').replace(/\n/g, '<br>');
      } catch(e) {
        body.innerHTML = '<pre>' + escapeHtml(opts.content || '') + '</pre>';
      }
    }
    if (dl && opts.downloadUrl) {
      dl.href = opts.downloadUrl;
      dl.download = opts.title || 'file';
    }
    if (modal) modal.classList.remove('hidden');
  }

  function closePreview() {
    const modal = DOM.get('lootPreview');
    if (modal) modal.classList.add('hidden');
  }

  // Nmap visualization
  let nmapVizState = { data: null, jsonUrl: null };

  function setNmapVizStatus(txt) {
    const el = DOM.get('nmapVizStatus');
    if (el) {
      el.innerHTML = escapeHtml(txt);
      applyStatusTone(el, txt);
    }
  }

  function setNmapVizError(txt) {
    const el = DOM.get('nmapVizError');
    if (el) el.innerHTML = escapeHtml(txt);
  }

  function closeNmapViz() {
    const modal = DOM.get('nmapVizModal');
    if (modal) modal.classList.add('hidden');
  }

  async function loadNmapVisualization(path, name) {
    const modal = DOM.get('nmapVizModal');
    if (modal) modal.classList.remove('hidden');

    try {
      const url = getApiUrl('/api/loot/nmap', { path, include_raw: '1' });
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.error ? data.error : 'Parse failed');

      nmapVizState.data = data;
      const title = DOM.get('nmapVizTitle');
      if (title) title.textContent = name || 'Nmap Visualization';

      const metaBits = [
        path ? `/${path}` : '',
        data && data.scan && data.scan.version ? `Nmap ${data.scan.version}` : '',
        data && data.stats && data.stats.time_str ? data.stats.time_str : '',
      ].filter(Boolean);

      const metaEl = DOM.get('nmapVizMeta');
      if (metaEl) metaEl.textContent = metaBits.join(' · ');

      if (data.raw_xml) {
        const xmlBlob = new Blob([data.raw_xml], { type: 'application/xml' });
        const xmlUrl = URL.createObjectURL(xmlBlob);
        const xmlDl = DOM.get('nmapVizDownloadXml');
        if (xmlDl) {
          xmlDl.href = xmlUrl;
          xmlDl.download = String(name || 'nmap').replace(/\.xml$/i, '.xml');
        }
      }

      if (data) {
        const jsonBlob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        nmapVizState.jsonUrl = URL.createObjectURL(jsonBlob);
        const jsonDl = DOM.get('nmapVizDownloadJson');
        if (jsonDl) {
          jsonDl.href = nmapVizState.jsonUrl;
          jsonDl.download = String(name || 'nmap').replace(/\.xml$/i, '.json');
        }
      }

      setNmapVizStatus('Ready');
    } catch(e) {
      setNmapVizStatus('Parse failed');
      setNmapVizError(e && e.message ? e.message : 'Failed to parse');
    }
  }

  // Rendering functions
  function renderLoot(items) {
    const list = DOM.get('lootList');
    if (!list) return;

    if (!items.length) {
      list.innerHTML = '<div class="px-3 py-4 text-sm text-slate-400">No files found.</div>';
      return;
    }

    const rows = items.map(item => {
      const itemType = item && item.type === 'dir' ? 'dir' : 'file';
      const icon = itemType === 'dir' ? '📁' : '📄';
      const meta = itemType === 'dir' ? 'Folder' : `${formatBytes(item.size)} · ${formatTime(item.mtime)}`;
      const safeName = escapeHtml(item.name || '');
      const encodedName = encodeData(item.name || '');
      const vizAction = isNmapLootXml(lootState.path, item.name)
        ? `<span role="button" tabindex="0" title="Visualize" aria-label="Visualize Nmap" data-visualize-nmap="${encodedName}" class="ml-2 inline-flex h-6 w-6 items-center justify-center rounded-md border border-red-400/20 bg-red-800/10 text-emerald-200 hover:bg-red-800/20 transition"><i class="fa-solid fa-network-wired text-[11px]"></i></span>`
        : '';
      return `
        <button class="w-full text-left px-3 py-3 flex items-center gap-3 hover:bg-slate-800/60 transition loot-item touch-target" data-type="${itemType}" data-name="${encodedName}">
          <span class="text-lg">${icon}</span>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-slate-100 truncate"><span>${safeName}</span>${vizAction}</div>
            <div class="text-[11px] text-slate-400">${escapeHtml(meta)}</div>
          </div>
          <div class="text-xs text-slate-400">${itemType === 'dir' ? 'Open' : 'Download'}</div>
        </button>
      `;
    }).join('');
    list.innerHTML = rows;
  }

  async function loadLoot(path = '') {
    setLootStatus('Loading...');
    try {
      const url = getApiUrl('/api/loot/list', { path });
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.error ? data.error : 'Failed to load');

      lootState = { path: data.path || '', parent: data.parent || '' };
      setLootPath(lootState.path);
      updateLootUp();
      renderLoot(data.items || []);
      setLootStatus('Ready');
    } catch(e) {
      setLootStatus('Failed to load');
      renderLoot([]);
    }
  }

  async function previewLootFile(path, name) {
    setLootStatus('Loading preview...');
    try {
      const url = getApiUrl('/api/loot/view', { path });
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.error ? data.error : 'Preview failed');

      const meta = `${formatBytes(data.size || 0)} · ${formatTime(data.mtime || 0)}${data.truncated ? ' · truncated' : ''}`;
      const downloadUrl = getApiUrl('/api/loot/download', { path });
      openPreview({
        title: name,
        content: data.content || '',
        meta,
        downloadUrl
      });
      setLootStatus('Ready');
    } catch(e) {
      setLootStatus('Preview failed');
    }
  }

  // Payload rendering
  function renderPayloadSidebar() {
    const sidebar = DOM.get('payloadSidebar');
    const mobileList = DOM.get('payloadsMobileList');

    if (!sidebar && !mobileList) return;

    const renderCats = (cats) => {
      return (cats || []).map(cat => {
        const encodedId = encodeData(cat.id || '');
        const isOpen = payloadState.open[cat.id];
        const payloads = (cat.payloads || []).map(p => {
          const encodedPath = encodeData(p.path || '');
          const name = escapeHtml(p.name || '');
          return `
            <button class="w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 transition touch-target" data-start="${encodedPath}" title="${name}">
              ▶ ${name}
            </button>
          `;
        }).join('');

        return `
          <div class="border-t border-slate-700">
            <button class="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-slate-800 transition font-semibold text-sm" data-cat="${encodedId}">
              <span class="transition" style="transform: rotate(${isOpen ? '90' : '0'}deg)">▶</span>
              ${escapeHtml(cat.id || '')}
            </button>
            ${isOpen ? payloads : ''}
          </div>
        `;
      }).join('');
    };

    const renderPayload = (payload) => {
      if (!payload.running) {
        const encodedPath = encodeData(payload.path || '');
        const name = escapeHtml(payload.name || '');
        return `
          <button class="px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded transition touch-target" data-start="${encodedPath}">
            ▶ Start
          </button>
        `;
      }
      return `
        <button class="px-3 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded transition touch-target" data-stop="true">
          ⏹ Stop
        </button>
      `;
    };

    // Will be populated from WebSocket messages
  }

  async function loadPayloads() {
    try {
      const url = getApiUrl('/api/payloads/list');
      const res = await apiFetch(url);
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.error ? data.error : 'Failed');

      payloadState.list = data.payloads || [];
      payloadState.open = {};
      renderPayloadSidebar();
    } catch(e) {
      warn('Load payloads failed:', e);
    }
  }

  function schedulePayloadPoll() {
    if (payloadState.pollTimer) clearInterval(payloadState.pollTimer);
    payloadState.pollTimer = setInterval(() => {
      if (activeTab === 'settings') loadPayloads();
    }, 5000);
  }

  function scheduleSystemPoll() {
    if (systemMonitorTimer) clearInterval(systemMonitorTimer);
    systemMonitorTimer = setInterval(() => {
      window.loadMobileSystemStatus && window.loadMobileSystemStatus();
    }, 3000);
  }

  // WebSocket connection
  function connect() {
    log('Connect called, ws state=' + (ws ? ws.readyState : 'null'));

    if (ws && ws.readyState !== WebSocket.OPEN && ws.readyState !== WebSocket.CONNECTING) {
      try { ws.close(); } catch(e) {}
      ws = null;
    }
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      log('WebSocket already connecting/open');
      return;
    }

    wsCandidates = getWsCandidates();
    log('WS candidates (' + wsCandidates.length + '):', wsCandidates);

    if (!wsCandidates.length) {
      setStatus('ERROR: No WebSocket URL candidates');
      scheduleReconnect();
      return;
    }

    if (wsCandidateIndex >= wsCandidates.length) wsCandidateIndex = 0;
    const url = wsCandidates[wsCandidateIndex];
    log('[' + (wsCandidateIndex + 1) + '/' + wsCandidates.length + '] Attempting: ' + url);

    if (!authToken && shared.refreshWsTicket) {
      shared.refreshWsTicket(getApiUrl, wsTicket)
        .then(newTicket => { if (newTicket) wsTicket = newTicket; })
        .catch(e => warn('Ticket refresh failed:', e));
    }

    let opened = false;
    try {
      ws = new WebSocket(url);
      setStatus(`Connecting ${wsCandidateIndex + 1}/${wsCandidates.length}`);

      if (connectTimeoutTimer) clearTimeout(connectTimeoutTimer);
      connectTimeoutTimer = setTimeout(() => {
        if (ws && ws.readyState === WebSocket.CONNECTING) {
          warn('WebSocket connect timeout');
          try { ws.close(); } catch(e) {}
        }
      }, WS_CONNECT_TIMEOUT);
    } catch(e) {
      setStatus('WebSocket failed');
      wsCandidateIndex = (wsCandidateIndex + 1) % wsCandidates.length;
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      log('WebSocket onopen event fired');
      opened = true;
      if (connectTimeoutTimer) {
        clearTimeout(connectTimeoutTimer);
        connectTimeoutTimer = null;
      }
      setStatus('Connected');
      reconnectAttempts = 0;
      lastServerMessage = Date.now();
      wsAuthenticated = true;
      log('WebSocket connected - resetting backoff');

      if (!authToken && shared.refreshWsTicket) {
        setTimeout(() => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            shared.refreshWsTicket(getApiUrl, wsTicket)
              .then(newTicket => {
                if (newTicket) {
                  wsTicket = newTicket;
                  try { ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket })); } catch(e) {}
                }
              })
              .catch(e => warn('Ticket refresh failed:', e));
          }
        }, AUTH_TICKET_REFRESH_INTERVAL);
      }

      if (wsTicket) {
        try { ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket })); } catch(e) {}
      } else if (authToken) {
        try { ws.send(JSON.stringify({ type: 'auth', token: authToken })); } catch(e) {}
      }

      if (shellWanted) sendShellOpen();
    };

    ws.onmessage = (ev) => {
      try {
        lastServerMessage = Date.now();
        const msg = JSON.parse(ev.data);

        if (msg.type === 'frame' && msg.data) {
          const img = new Image();
          img.onload = () => {
            try {
              for (const [c, cx] of [[canvas, ctx], [canvasGb, ctxGb], [canvasPager, ctxPager], [canvasSyndicate, ctxSyndicate]]) {
                if (!c || !cx) continue;
                cx.clearRect(0, 0, c.width, c.height);
                cx.drawImage(img, 0, 0, c.width, c.height);
              }
            } catch(e) {}
          };
          img.src = 'data:image/jpeg;base64,' + msg.data;
          return;
        }

        if (msg.type === 'auth_required') {
          wsAuthenticated = false;
          if (wsTicket) {
            try { ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket })); } catch(e) {}
            return;
          }
          if (authToken) {
            try { ws.send(JSON.stringify({ type: 'auth', token: authToken })); } catch(e) {}
            return;
          }
          ensureAuthenticated('Authentication required')
            .then(() => {
              if (!ws || ws.readyState !== WebSocket.OPEN) return;
              if (wsTicket) {
                try { ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket })); } catch(e) {}
              } else if (authToken) {
                try { ws.send(JSON.stringify({ type: 'auth', token: authToken })); } catch(e) {}
              }
            });
          return;
        }

        if (msg.type === 'shell_output' && term && shellOpen) {
          try { term.write(msg.data || ''); } catch(e) {}
          return;
        }

        if (msg.type === 'shell_open_response') {
          shellOpen = msg.ok !== false;
          setShellStatus(shellOpen ? 'Connected' : 'Failed');
          return;
        }

        if (msg.type === 'shell_close_response') {
          shellOpen = false;
          setShellStatus('Disconnected');
          if (term) term.reset();
          return;
        }

        if (msg.type === 'system' && msg.data) {
          const d = msg.data;
          const cpu = Number(d.cpu_percent || 0);
          const mem = pct(Number(d.mem_used || 0), Number(d.mem_total || 0));
          const disk = pct(Number(d.disk_used || 0), Number(d.disk_total || 0));

          const sysCpuValue = DOM.get('sysCpuValue');
          if (sysCpuValue) sysCpuValue.textContent = cpu.toFixed(1) + '%';
          bar(DOM.get('sysCpuBar'), cpu);

          if (d.temp_c !== null && d.temp_c !== undefined) {
            const sysTempValue = DOM.get('sysTempValue');
            if (sysTempValue) sysTempValue.textContent = Number(d.temp_c).toFixed(1) + ' C';
          }

          const sysMemValue = DOM.get('sysMemValue');
          if (sysMemValue) sysMemValue.textContent = mem.toFixed(1) + '%';
          const sysMemMeta = DOM.get('sysMemMeta');
          if (sysMemMeta) sysMemMeta.textContent = formatBytes(d.mem_used || 0) + ' / ' + formatBytes(d.mem_total || 0);
          bar(DOM.get('sysMemBar'), mem);

          const sysDiskValue = DOM.get('sysDiskValue');
          if (sysDiskValue) sysDiskValue.textContent = disk.toFixed(1) + '%';
          const sysDiskMeta = DOM.get('sysDiskMeta');
          if (sysDiskMeta) sysDiskMeta.textContent = formatBytes(d.disk_used || 0) + ' / ' + formatBytes(d.disk_total || 0);
          bar(DOM.get('sysDiskBar'), disk);

          const sysUptime = DOM.get('sysUptime');
          if (sysUptime) sysUptime.textContent = formatDuration(d.uptime_s || 0);

          const sysLoad = DOM.get('sysLoad');
          if (sysLoad) sysLoad.textContent = Array.isArray(d.load) ? d.load.map(v => Number(v).toFixed(2)).join(', ') : '-';

          const sysPayload = DOM.get('sysPayload');
          if (sysPayload) sysPayload.textContent = d.payload_running ? (d.payload_path || 'running') : 'none';

          const sysInterfaces = DOM.get('sysInterfaces');
          if (sysInterfaces) {
            const ifaces = Array.isArray(d.interfaces) ? d.interfaces : [];
            if (!ifaces.length) {
              sysInterfaces.innerHTML = '<div class="text-slate-500">No active interfaces</div>';
            } else {
              sysInterfaces.innerHTML = ifaces.map(i => `<div><span class="text-red-400">${escapeHtml(String(i.name || '-'))}</span>: ${escapeHtml(String(i.ipv4 || '-'))}</div>`).join('');
            }
          }
          return;
        }

        if (msg.type === 'payload' && msg.data) {
          const d = msg.data;
          setPayloadStatus(d.status || 'Unknown');
          return;
        }

        if (msg.type === 'auth_ok') {
          wsAuthenticated = true;
          saveAuthToken(msg.token || '');
          authToken = msg.token || '';
          setStatus('Authenticated');
          return;
        }
      } catch(e) {
        warn('WebSocket message parse error:', e);
      }
    };

    ws.onerror = (ev) => {
      log('WebSocket onerror event:', ev);
      wsAuthenticated = false;
    };

    ws.onclose = () => {
      log('WebSocket onclose event');
      shellOpen = false;
      setShellStatus('Disconnected');
      wsAuthenticated = false;
      scheduleReconnect('connection closed');
    };
  }

  function scheduleReconnect(reason = '') {
    if (reconnectTimer) clearTimeout(reconnectTimer);

    const baseDelay = 1000;
    const maxDelay = 30000;
    const delayMs = Math.min(baseDelay * Math.pow(2, reconnectAttempts), maxDelay);
    reconnectAttempts++;

    log(`Reconnect attempt ${reconnectAttempts} in ${delayMs}ms${reason ? ' (' + reason + ')' : ''}`);

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (!document.hidden) {
        connect();
      }
    }, delayMs);
  }

  function ensureSocketLive(reason = '') {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    log('Socket not live, reconnecting: ' + reason);
    connect();
  }

  // Auth modal
  let authModalOpen = false;
  let authModalResolve = null;

  async function ensureAuthenticated(message = 'Log in') {
    if (authToken) return true;

    return new Promise((resolve) => {
      authModalResolve = resolve;
      showAuthModal('login', message);
    });
  }

  function showAuthModal(mode, message) {
    const modal = DOM.get('authModal');
    if (!modal) return;

    modal.classList.remove('hidden');
    authModalOpen = true;

    const title = DOM.get('authModalTitle');
    const msg = DOM.get('authModalMessage');
    if (title) title.textContent = mode === 'login' ? 'Login' : 'Create Account';
    if (msg) msg.textContent = message || '';

    for (const id of ['authModalUsername', 'authModalPassword', 'authModalPasswordConfirm', 'authModalToken']) {
      const el = DOM.get(id);
      if (el) el.value = '';
    }
  }

  function closeAuthModal() {
    const modal = DOM.get('authModal');
    if (modal) modal.classList.add('hidden');
    authModalOpen = false;
  }

  async function submitAuthForm() {
    const username = DOM.get('authModalUsername');
    const password = DOM.get('authModalPassword');
    const token = DOM.get('authModalToken');

    const u = (username && username.value) || '';
    const p = (password && password.value) || '';
    const t = (token && token.value) || '';

    if (!u || !p) {
      const error = DOM.get('authModalError');
      if (error) error.textContent = 'Username and password required';
      return;
    }

    try {
      const res = await fetch(getApiUrl('/api/auth/login'), {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ username: u, password: p })
      });

      const data = await res.json();
      if (!res.ok) {
        const error = DOM.get('authModalError');
        if (error) error.textContent = data && data.error ? data.error : 'Login failed';
        return;
      }

      if (data.token) {
        saveAuthToken(data.token);
        authToken = data.token;
        closeAuthModal();
        if (authModalResolve) authModalResolve(true);
        return;
      }
    } catch(e) {
      const error = DOM.get('authModalError');
      if (error) error.textContent = 'Network error';
    }
  }

  // Logout
  function logoutUser() {
    authToken = '';
    wsTicket = '';
    try { localStorage.removeItem('ktox_token'); } catch(e) {}
    closeAuthModal();
    if (ws) {
      try { ws.close(); } catch(e) {}
      ws = null;
    }
    setStatus('Logged out');
    setTimeout(() => startAfterAuth(), 1000);
  }

  // Mobile system status
  window.loadMobileSystemStatus = async function() {
    const status = DOM.get('mobileSystemStatus');
    if (status) status.textContent = 'Loading...';

    try {
      const url = getApiUrl('/api/system/status');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.error ? data.error : 'Failed');

      const cpu = Number(data.cpu_percent || 0);
      const mem = pct(Number(data.mem_used || 0), Number(data.mem_total || 0));
      const disk = pct(Number(data.disk_used || 0), Number(data.disk_total || 0));

      for (const [id, val] of [
        ['mobSysCpuValue', cpu.toFixed(1) + '%'],
        ['mobSysTempValue', data.temp_c === null || data.temp_c === undefined ? '--.- C' : Number(data.temp_c).toFixed(1) + ' C'],
        ['mobSysMemValue', mem.toFixed(1) + '%'],
        ['mobSysMemMeta', formatBytes(data.mem_used || 0) + ' / ' + formatBytes(data.mem_total || 0)],
        ['mobSysDiskValue', disk.toFixed(1) + '%'],
        ['mobSysDiskMeta', formatBytes(data.disk_used || 0) + ' / ' + formatBytes(data.disk_total || 0)],
        ['mobSysUptime', formatDuration(data.uptime_s || 0)],
        ['mobSysLoad', Array.isArray(data.load) ? data.load.map(v => Number(v).toFixed(2)).join(', ') : '-'],
        ['mobSysPayload', data.payload_running ? (data.payload_path || 'running') : 'none'],
      ]) {
        const el = DOM.get(id);
        if (el) el.textContent = val;
      }

      bar(DOM.get('mobSysCpuBar'), cpu);
      bar(DOM.get('mobSysMemBar'), mem);
      bar(DOM.get('mobSysDiskBar'), disk);

      const ifaces = Array.isArray(data.interfaces) ? data.interfaces : [];
      const ifacesEl = DOM.get('mobSysInterfaces');
      if (ifacesEl) {
        ifacesEl.innerHTML = ifaces.length ? ifaces.map(i => `<div><span class="text-red-400">${escapeHtml(String(i.name || '-'))}</span>: ${escapeHtml(String(i.ipv4 || '-'))}</div>`).join('') : '<div class="text-slate-500">No active interfaces</div>';
      }

      if (status) status.textContent = 'Live';
    } catch(e) {
      if (status) status.textContent = 'Unavailable';
    }
  };

  // Heartbeat monitor
  function startHeartbeatMonitor() {
    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        const timeSinceLastMessage = Date.now() - lastServerMessage;
        if (timeSinceLastMessage > SERVER_HEARTBEAT_TIMEOUT) {
          warn('Server heartbeat timeout');
          try { ws.close(); } catch(e) {}
          scheduleReconnect('heartbeat timeout');
        }
      } else if (!document.hidden && (!ws || ws.readyState !== WebSocket.OPEN)) {
        warn('PWA: Disconnected while visible');
        ensureSocketLive('heartbeat-check-pwa');
      }
    }, HEARTBEAT_CHECK_INTERVAL);
  }

  // Event listeners setup
  function setupEventListeners() {
    // Navigation
    DOM.on(DOM.get('navDevice'), 'click', () => setActiveTab('device'));
    DOM.on(DOM.get('navSystem'), 'click', () => setSystemOpen(!systemOpen));
    DOM.on(DOM.get('navLoot'), 'click', () => {
      setActiveTab('loot');
      const lootList = DOM.get('lootList');
      if (lootList && !lootList.dataset.loaded) {
        loadLoot('');
        lootList.dataset.loaded = '1';
      }
    });
    DOM.on(DOM.get('navSettings'), 'click', () => {
      setActiveTab('settings');
      loadDiscordWebhook();
      loadTailscaleSettings();
    });

    const navPayloadStudio = DOM.get('navPayloadStudio');
    if (navPayloadStudio) navPayloadStudio.href = './ide.html' + getForwardSearch();

    // Theme buttons
    for (const btn of DOM.all('[data-theme]')) {
      DOM.on(btn, 'click', () => {
        const id = btn.getAttribute('data-theme');
        if (id) setThemeById(id);
      });
    }

    // Menu toggle
    DOM.on(DOM.get('menuToggle'), 'click', () => setSidebarOpen(true));
    DOM.on(DOM.get('sidebarBackdrop'), 'click', () => setSidebarOpen(false));

    // Loot management
    DOM.on(DOM.get('lootUpBtn'), 'click', () => {
      if (lootState.parent !== undefined) loadLoot(lootState.parent || '');
    });

    const lootList = DOM.get('lootList');
    DOM.on(lootList, 'click', (e) => {
      const vizBtn = e.target.closest('[data-visualize-nmap]');
      if (vizBtn) {
        e.preventDefault();
        const encodedViz = vizBtn.getAttribute('data-visualize-nmap') || '';
        const vizName = decodeData(encodedViz);
        const vizPath = buildLootPath(lootState.path, vizName);
        loadNmapVisualization(vizPath, vizName);
        return;
      }
      const btn = e.target.closest('.loot-item');
      if (!btn) return;
      const encoded = btn.getAttribute('data-name') || '';
      const name = decodeData(encoded);
      const type = btn.getAttribute('data-type');
      const nextPath = buildLootPath(lootState.path, name);
      if (type === 'dir') {
        loadLoot(nextPath);
      } else {
        previewLootFile(nextPath, name);
      }
    });

    // Payload management
    const payloadSidebar = DOM.get('payloadSidebar');
    DOM.on(payloadSidebar, 'click', (e) => {
      const catBtn = e.target.closest('[data-cat]');
      if (catBtn) {
        const encodedId = catBtn.getAttribute('data-cat') || '';
        const id = decodeData(encodedId);
        if (id) {
          payloadState.open[id] = !payloadState.open[id];
          renderPayloadSidebar();
        }
        return;
      }
      const startBtn = e.target.closest('[data-start]');
      if (startBtn) {
        const encodedPath = startBtn.getAttribute('data-start') || '';
        const path = decodeData(encodedPath);
        if (path && ws && ws.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ type: 'payload_start', path })); } catch(e) {}
        }
        return;
      }
      const stopBtn = e.target.closest('[data-stop]');
      if (stopBtn) {
        setPayloadStatus('Stopping...');
        if (ws && ws.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ type: 'payload_stop' })); } catch(e) {}
        }
      }
    });

    const payloadsMobileList = DOM.get('payloadsMobileList');
    DOM.on(payloadsMobileList, 'click', (e) => {
      const catBtn = e.target.closest('[data-cat]');
      if (catBtn) {
        const id = decodeData(catBtn.getAttribute('data-cat') || '');
        if (id) { payloadState.open[id] = !payloadState.open[id]; renderPayloadSidebar(); }
        return;
      }
      const startBtn = e.target.closest('[data-start]');
      if (startBtn) {
        const path = decodeData(startBtn.getAttribute('data-start') || '');
        if (path && ws && ws.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ type: 'payload_start', path })); } catch(e) {}
        }
        return;
      }
      const stopBtn = e.target.closest('[data-stop]');
      if (stopBtn) {
        setPayloadStatus('Stopping...');
        if (ws && ws.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ type: 'payload_stop' })); } catch(e) {}
        }
      }
    });

    const payloadsRefresh = DOM.get('payloadsRefresh');
    DOM.on(payloadsRefresh, 'click', () => loadPayloads());
    const payloadsMobRefresh = DOM.get('payloadsMobRefresh');
    DOM.on(payloadsMobRefresh, 'click', () => loadPayloads());

    // Settings
    const settingsToggle = DOM.get('settingsToggle');
    DOM.on(settingsToggle, 'click', () => {
      setActiveTab('settings');
      loadDiscordWebhook();
      loadTailscaleSettings();
    });

    DOM.on(DOM.get('wsUrlOverrideSave'), 'click', () => {
      const el = DOM.get('wsUrlOverrideInput');
      if (el) {
        setManualWsUrl(el.value);
        const status = DOM.get('wsUrlStatus');
        if (status) status.textContent = 'Saved. Reconnect to use.';
        setSettingsStatus('WebSocket URL saved');
      }
    });

    DOM.on(DOM.get('wsUrlOverrideClear'), 'click', () => {
      const el = DOM.get('wsUrlOverrideInput');
      if (el) el.value = '';
      setManualWsUrl('');
      const status = DOM.get('wsUrlStatus');
      if (status) status.textContent = 'Cleared';
      setSettingsStatus('WebSocket URL cleared');
    });

    DOM.on(DOM.get('discordWebhookSave'), 'click', () => {
      const el = DOM.get('discordWebhookInput');
      if (el) {
        saveDiscordWebhook(el.value);
        setSettingsStatus('Discord webhook saved');
      }
    });

    DOM.on(DOM.get('discordWebhookClear'), 'click', () => {
      const el = DOM.get('discordWebhookInput');
      if (el) el.value = '';
      saveDiscordWebhook('');
      setSettingsStatus('Discord webhook cleared');
    });

    DOM.on(DOM.get('tailscaleInstallBtn'), 'click', () => openTailscaleModal());
    DOM.on(DOM.get('tailscaleReauthBtn'), 'click', () => openTailscaleModal());
    DOM.on(DOM.get('tailscaleModalSave'), 'click', () => {
      const keyInput = DOM.get('tailscaleKeyInput');
      if (keyInput && keyInput.value) {
        setTailscaleStatus('Installing...');
        apiFetch(getApiUrl('/api/tailscale/install'), {
          method: 'POST',
          body: JSON.stringify({ auth_key: keyInput.value })
        }).then(r => r.json())
          .then(d => {
            setTailscaleStatus(d.status || 'Installed');
            closeTailscaleModal();
          })
          .catch(e => setTailscaleStatus('Installation failed'));
      }
    });

    DOM.on(DOM.get('tailscaleModalCancel'), 'click', closeTailscaleModal);
    DOM.on(DOM.get('tailscaleModalClose'), 'click', closeTailscaleModal);

    const tailscaleModal = DOM.get('tailscaleModal');
    DOM.on(tailscaleModal, 'click', (e) => {
      if (e.target === tailscaleModal) closeTailscaleModal();
    });

    // Preview modal
    DOM.on(DOM.get('lootPreviewClose'), 'click', closePreview);
    const lootPreview = DOM.get('lootPreview');
    DOM.on(lootPreview, 'click', (e) => {
      if (e.target === lootPreview) closePreview();
    });

    // Nmap modal
    DOM.on(DOM.get('nmapVizClose'), 'click', closeNmapViz);
    const nmapVizModal = DOM.get('nmapVizModal');
    DOM.on(nmapVizModal, 'click', (e) => {
      if (e.target === nmapVizModal) closeNmapViz();
    });

    const nmapVizFilterVuln = DOM.get('nmapVizFilterVuln');
    DOM.on(nmapVizFilterVuln, 'change', () => {
      // Re-render visualization with filter
    });

    // Auth modal
    const authModal = DOM.get('authModal');
    DOM.on(authModal, 'click', (e) => {
      if (e.target === authModal) closeAuthModal();
    });
    DOM.on(DOM.get('authModalConfirm'), 'click', submitAuthForm);
    DOM.on(DOM.get('authModalCancel'), 'click', () => {
      closeAuthModal();
      if (authModalResolve) authModalResolve(false);
    });
    DOM.on(DOM.get('authModalClose'), 'click', () => {
      closeAuthModal();
      if (authModalResolve) authModalResolve(false);
    });

    for (const id of ['authModalUsername', 'authModalPassword', 'authModalPasswordConfirm', 'authModalToken']) {
      DOM.on(DOM.get(id), 'keydown', (e) => {
        if (e.key === 'Enter') submitAuthForm();
      });
    }

    // Shell
    DOM.on(DOM.get('shellConnectBtn'), 'click', sendShellOpen);
    DOM.on(DOM.get('shellDisconnectBtn'), 'click', sendShellClose);

    for (const btn of DOM.all('.shell-key-btn')) {
      DOM.on(btn, 'click', () => {
        const key = btn.getAttribute('data-shell-key');
        if (key) sendShellInput(key);
        if (term) try { term.focus(); } catch(e) {}
      });
    }

    // Logout
    DOM.on(DOM.get('settingsLogoutBtn'), 'click', logoutUser);

    // Resize for terminal
    DOM.on(window, 'resize', debounce(() => {
      if (shellOpen) sendShellResize();
    }, 200));

    // Resize for responsive tabs
    DOM.on(window, 'resize', debounce(() => {
      applyResponsiveTabClasses(activeTab);
      if (activeTab === 'terminal' && fitAddon) {
        requestAnimationFrame(() => { try { fitAddon.fit(); } catch(e) {} });
      }
    }, 200));

    // Mobile nav buttons
    for (const btn of DOM.all('[data-mobnav]')) {
      DOM.on(btn, 'click', () => {
        const tab = btn.dataset.mobnav;
        if (tab === 'system') {
          setSystemOpen(!systemOpen);
          if (!systemOpen) setActiveTab('system');
        } else if (tab === 'terminal') {
          setActiveTab('terminal');
          ensureTerminal();
        } else {
          setActiveTab(tab);
        }
      });
    }

    // Network events
    DOM.on(window, 'online', () => {
      log('Network online');
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      ensureSocketLive('network recovered');
    });

    DOM.on(window, 'offline', () => {
      log('Network offline');
      if (ws) try { ws.close(); } catch(e) {}
    });

    // Page visibility
    DOM.on(document, 'visibilitychange', () => {
      log('Visibility changed, hidden=' + document.hidden);
      if (!document.hidden) {
        applyResponsiveTabClasses(activeTab);
        if (activeTab === 'system') window.loadMobileSystemStatus && window.loadMobileSystemStatus();
      }
    });

    // PWA page lifecycle
    DOM.on(window, 'pageshow', (e) => {
      log('Pageshow fired (persisted=' + (e && e.persisted) + ')');
      ensureSocketLive('pageshow');
    });

    DOM.on(window, 'pagehide', () => {
      log('Pagehide fired');
      if (ws) try { ws.close(); } catch(e) {}
    });

    DOM.on(window, 'focus', () => {
      log('Window focus gained');
      ensureSocketLive('window-focus');
    });

    DOM.on(window, 'blur', () => {
      log('Window lost focus');
    });

    // Swipe gestures for navigation (mobile)
    GestureHandler.onSwipeRight = () => {
      if (Mobile.isMobile() && activeTab !== 'device') {
        const prev = ['device', 'system', 'loot', 'settings', 'terminal'];
        const idx = prev.indexOf(activeTab);
        if (idx > 0) setActiveTab(prev[idx - 1]);
      }
    };

    GestureHandler.onSwipeLeft = () => {
      if (Mobile.isMobile() && activeTab !== 'terminal') {
        const next = ['device', 'system', 'loot', 'settings', 'terminal'];
        const idx = next.indexOf(activeTab);
        if (idx < next.length - 1) setActiveTab(next[idx + 1]);
      }
    };

    GestureHandler.init();
  }

  // Initialization
  function startAfterAuth() {
    log('startAfterAuth: checking authentication, hidden=' + document.hidden);
    ensureAuthenticated('Log in to access KTOx WebUI').then((ok) => {
      if (!ok) {
        log('Authentication required');
        setTimeout(startAfterAuth, 0);
        return;
      }
      log('Authenticated - starting');
      setupEventListeners();
      applyResponsiveTabClasses(activeTab);
      startHeartbeatMonitor();

      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      reconnectAttempts = 0;

      connect();
      ensureTerminal();
      loadPayloads();
      schedulePayloadPoll();
      scheduleSystemPoll();
    });
  }

  // Cleanup on unload
  DOM.on(window, 'beforeunload', () => {
    DOM.cleanup();
    if (ws) try { ws.close(); } catch(e) {}
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (connectTimeoutTimer) clearTimeout(connectTimeoutTimer);
  });

  log('Page loaded, starting initialization');
  startAfterAuth();
})();
