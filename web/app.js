(function(){
  const shared = window.RJShared || {};
  const canvas = document.getElementById('screen');
  const canvasGb = document.getElementById('screen-gb');
  const canvasPager = document.getElementById('screen-pager');
  const canvasSyndicate = document.getElementById('screen-syndicate');
  const ctx = canvas.getContext('2d');
  const ctxGb = canvasGb ? canvasGb.getContext('2d') : null;
  const ctxPager = canvasPager ? canvasPager.getContext('2d') : null;
  const ctxSyndicate = canvasSyndicate ? canvasSyndicate.getContext('2d') : null;
  // Enable high-DPI backing store and high-quality smoothing
  function setupHiDPI(){
    const DPR = Math.max(1, Math.floor(window.devicePixelRatio || 1));
    const logical = 128;
    canvas.width = logical * DPR;
    canvas.height = logical * DPR;
    ctx.imageSmoothingEnabled = true;
    try { ctx.imageSmoothingQuality = 'high'; } catch {}
    if (canvasGb && ctxGb) {
      canvasGb.width = logical * DPR;
      canvasGb.height = logical * DPR;
      ctxGb.imageSmoothingEnabled = true;
      try { ctxGb.imageSmoothingQuality = 'high'; } catch {}
    }
    if (canvasPager && ctxPager) {
      canvasPager.width = logical * DPR;
      canvasPager.height = logical * DPR;
      ctxPager.imageSmoothingEnabled = true;
      try { ctxPager.imageSmoothingQuality = 'high'; } catch {}
    }
    if (canvasSyndicate && ctxSyndicate) {
      canvasSyndicate.width = logical * DPR;
      canvasSyndicate.height = logical * DPR;
      ctxSyndicate.imageSmoothingEnabled = true;
      try { ctxSyndicate.imageSmoothingQuality = 'high'; } catch {}
    }
  }
  setupHiDPI();
  window.addEventListener('resize', setupHiDPI);
  const statusEl = document.getElementById('status');
  const statusEls = document.querySelectorAll('.status-text');
  const deviceShell = document.getElementById('deviceShell');
  const themeNameEl = document.getElementById('themeName');
  const navDevice = document.getElementById('navDevice');
  const navSystem = document.getElementById('navSystem');
  const navPentest = document.getElementById('navPentest');
  const navLoki = document.getElementById('navLoki');
  const navSdr = document.getElementById('navSdr');
  const sdrServiceToggle = document.getElementById('sdrServiceToggle');
  const sdrServiceState = document.getElementById('sdrServiceState');
  const sdrServiceStatus = document.getElementById('sdrServiceStatus');
  const sdrServiceStart = document.getElementById('sdrServiceStart');
  const sdrServiceOpen = document.getElementById('sdrServiceOpen');
  const sdrServiceStop = document.getElementById('sdrServiceStop');
  const sdrServiceRefresh = document.getElementById('sdrServiceRefresh');
  const navLoot = document.getElementById('navLoot');
  const navSettings = document.getElementById('navSettings');
  const navPayloadStudio = document.getElementById('navPayloadStudio');
  const themeButtons = document.querySelectorAll('[data-theme]');
  const sidebar = document.getElementById('sidebar');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');
  const menuToggle = document.getElementById('menuToggle');
  const deviceTab = document.getElementById('deviceTab');
  const systemDropdown = document.getElementById('systemDropdown');
  const settingsTab = document.getElementById('settingsTab');
  const pentestTab = document.getElementById('pentestTab');
  const lokiTab = document.getElementById('lokiTab');
  const lootTab = document.getElementById('lootTab');
  const systemStatus = document.getElementById('systemStatus');
  const sysCpuValue = document.getElementById('sysCpuValue');
  const sysCpuBar = document.getElementById('sysCpuBar');
  const sysTempValue = document.getElementById('sysTempValue');
  const sysMemValue = document.getElementById('sysMemValue');
  const sysMemMeta = document.getElementById('sysMemMeta');
  const sysMemBar = document.getElementById('sysMemBar');
  const sysDiskValue = document.getElementById('sysDiskValue');
  const sysDiskMeta = document.getElementById('sysDiskMeta');
  const sysDiskBar = document.getElementById('sysDiskBar');
  const sysUptime = document.getElementById('sysUptime');
  const sysLoad = document.getElementById('sysLoad');
  const sysPayload = document.getElementById('sysPayload');
  const sysInterfaces = document.getElementById('sysInterfaces');
  const mobileSystemStatus = document.getElementById('mobileSystemStatus');
  const mobSysCpuValue = document.getElementById('mobSysCpuValue');
  const mobSysCpuBar = document.getElementById('mobSysCpuBar');
  const mobSysTempValue = document.getElementById('mobSysTempValue');
  const mobSysMemValue = document.getElementById('mobSysMemValue');
  const mobSysMemMeta = document.getElementById('mobSysMemMeta');
  const mobSysMemBar = document.getElementById('mobSysMemBar');
  const mobSysDiskValue = document.getElementById('mobSysDiskValue');
  const mobSysDiskMeta = document.getElementById('mobSysDiskMeta');
  const mobSysDiskBar = document.getElementById('mobSysDiskBar');
  const mobSysUptime = document.getElementById('mobSysUptime');
  const mobSysLoad = document.getElementById('mobSysLoad');
  const mobSysPayload = document.getElementById('mobSysPayload');
  const mobSysInterfaces = document.getElementById('mobSysInterfaces');
  const mobSysHostname = document.getElementById('mobSysHostname');
  const mobSysKernel = document.getElementById('mobSysKernel');
  const mobSysTailscale = document.getElementById('mobSysTailscale');
  const pentestStatus = document.getElementById('pentestStatus');
  const pentestUrl = document.getElementById('pentestUrl');
  const pentestStart = document.getElementById('pentestStart');
  const pentestStop = document.getElementById('pentestStop');
  const pentestOpen = document.getElementById('pentestOpen');
  const pentestFrame = document.getElementById('pentestFrame');
  const pentestFrameStatus = document.getElementById('pentestFrameStatus');
  const pentestFrameStart = document.getElementById('pentestFrameStart');
  const pentestFrameReload = document.getElementById('pentestFrameReload');
  const pentestFrameStop = document.getElementById('pentestFrameStop');
  const pentestFrameExternal = document.getElementById('pentestFrameExternal');
  const desktopFrame = document.getElementById('desktopFrame');
  const desktopFrameStatus = document.getElementById('desktopFrameStatus');
  const desktopFrameInstallDeps = document.getElementById('desktopFrameInstallDeps');
  const desktopFrameStart = document.getElementById('desktopFrameStart');
  const desktopFrameReload = document.getElementById('desktopFrameReload');
  const desktopFrameStop = document.getElementById('desktopFrameStop');
  const desktopFrameExternal = document.getElementById('desktopFrameExternal');
  const mobPentestStatus = document.getElementById('mobPentestStatus');
  const mobPentestUrl = document.getElementById('mobPentestUrl');
  const mobPentestStart = document.getElementById('mobPentestStart');
  const mobPentestStop = document.getElementById('mobPentestStop');
  const lokiStatus = document.getElementById('lokiStatus');
  const lokiUrl = document.getElementById('lokiUrl');
  const lokiStart = document.getElementById('lokiStart');
  const lokiStop = document.getElementById('lokiStop');
  const lokiOpen = document.getElementById('lokiOpen');
  const lokiFrame = document.getElementById('lokiFrame');
  const lokiFrameEmpty = document.getElementById('lokiFrameEmpty');
  const lokiFrameEmptyStart = document.getElementById('lokiFrameEmptyStart');
  const lokiFrameStatus = document.getElementById('lokiFrameStatus');
  const lokiFrameStart = document.getElementById('lokiFrameStart');
  const lokiFrameReload = document.getElementById('lokiFrameReload');
  const lokiFrameStop = document.getElementById('lokiFrameStop');
  const lokiFrameExternal = document.getElementById('lokiFrameExternal');
  const mobileSystemRefresh = document.getElementById('mobileSystemRefresh');
  const lootList = document.getElementById('lootList');
  const lootPathEl = document.getElementById('lootPath');
  const lootUpBtn = document.getElementById('lootUp');
  const lootStatus = document.getElementById('lootStatus');
  const lootPreview = document.getElementById('lootPreview');
  const lootPreviewTitle = document.getElementById('lootPreviewTitle');
  const lootPreviewBody = document.getElementById('lootPreviewBody');
  const lootPreviewClose = document.getElementById('lootPreviewClose');
  const lootPreviewDownload = document.getElementById('lootPreviewDownload');
  const lootPreviewMeta = document.getElementById('lootPreviewMeta');
  const nmapVizModal = document.getElementById('nmapVizModal');
  const nmapVizTitle = document.getElementById('nmapVizTitle');
  const nmapVizMeta = document.getElementById('nmapVizMeta');
  const nmapVizStatus = document.getElementById('nmapVizStatus');
  const nmapVizBody = document.getElementById('nmapVizBody');
  const nmapVizError = document.getElementById('nmapVizError');
  const nmapVizClose = document.getElementById('nmapVizClose');
  const nmapVizDownloadXml = document.getElementById('nmapVizDownloadXml');
  const nmapVizDownloadJson = document.getElementById('nmapVizDownloadJson');
  const nmapVizFilterVuln = document.getElementById('nmapVizFilterVuln');
  const payloadSidebar = document.getElementById('payloadSidebar');
  const payloadsMobileList = document.getElementById('payloadsMobileList');
  const payloadStatus = document.getElementById('payloadStatus');
  const payloadStatusDot = document.getElementById('payloadStatusDot');
  const payloadsRefresh = document.getElementById('payloadsRefresh');
  const gameCenterStatus = document.getElementById('gameCenterStatus');
  const gameCenterRefresh = document.getElementById('gameCenterRefresh');
  const gameCenterInstall = document.getElementById('gameCenterInstall');
  const gameCenterEmulator = document.getElementById('gameCenterEmulator');
  const gameCenterRom = document.getElementById('gameCenterRom');
  const gameCenterPlay = document.getElementById('gameCenterPlay');
  const settingsStatus = document.getElementById('settingsStatus');
  const discordWebhookInput = document.getElementById('discordWebhookInput');
  const discordWebhookSave = document.getElementById('discordWebhookSave');
  const discordWebhookClear = document.getElementById('discordWebhookClear');
  const tailscaleSettingsStatus = document.getElementById('tailscaleSettingsStatus');
  const tailscaleInstallBtn = document.getElementById('tailscaleInstallBtn');
  const tailscaleReauthBtn = document.getElementById('tailscaleReauthBtn');
  const tailscaleModal = document.getElementById('tailscaleModal');
  const tailscaleKeyInput = document.getElementById('tailscaleKeyInput');
  const tailscaleModalError = document.getElementById('tailscaleModalError');
  const tailscaleModalStatus = document.getElementById('tailscaleModalStatus');
  const tailscaleModalSave = document.getElementById('tailscaleModalSave');
  const tailscaleModalCancel = document.getElementById('tailscaleModalCancel');
  const tailscaleModalClose = document.getElementById('tailscaleModalClose');
  const terminalEl = document.getElementById('terminal');
  const shellStatusEl = document.getElementById('shellStatus');
  const shellConnectBtn = document.getElementById('shellConnect');
  const shellDisconnectBtn = document.getElementById('shellDisconnect');
  const logoutBtn = document.getElementById('logoutBtn');
  const authModal = document.getElementById('authModal');
  const authModalTitle = document.getElementById('authModalTitle');
  const authModalMessage = document.getElementById('authModalMessage');
  const authModalUsername = document.getElementById('authModalUsername');
  const authModalPassword = document.getElementById('authModalPassword');
  const authModalPasswordConfirm = document.getElementById('authModalPasswordConfirm');
  const authModalToken = document.getElementById('authModalToken');
  const authModalRules = document.getElementById('authModalRules');
  const authModalError = document.getElementById('authModalError');
  const authModalToggleRecovery = document.getElementById('authModalToggleRecovery');
  const authModalConfirm = document.getElementById('authModalConfirm');
  const authModalCancel = document.getElementById('authModalCancel');
  const authModalClose = document.getElementById('authModalClose');

  let wsCandidates = [];
  let wsCandidateIndex = 0;
  let gameCenterState = { emulators: [], roms: [] };

  function getWsCandidates(){
    if (shared.getWsUrlCandidates){
      const candidates = shared.getWsUrlCandidates(location);
      if (Array.isArray(candidates) && candidates.length){
        return Array.from(new Set(candidates.map(v => String(v || '').trim()).filter(Boolean)));
      }
    }
    const candidates = [];
    const p = new URLSearchParams(location.search);
    const explicit = String(p.get('ws') || '').trim();
    if (explicit) candidates.push(explicit);
    if (location.protocol === 'https:'){
      candidates.push(`${location.origin.replace(/^https:/, 'wss:')}/ws`);
      return Array.from(new Set(candidates));
    }
    const host = location.hostname || 'raspberrypi.local';
    const explicitPort = String(p.get('port') || p.get('wsport') || '').trim();
    const originPort = String(location.port || '').trim();
    const sameOriginWs = `${location.origin.replace(/^https?:/, 'ws:')}/ws`;
    candidates.push(sameOriginWs);
    candidates.push(`ws://${host}:${explicitPort || originPort || '8765'}/`.replace(/\/\/\//,'//'));
    return Array.from(new Set(candidates));
  }

  function getWsUrl(){
    wsCandidates = getWsCandidates();
    if (!wsCandidates.length && shared.getWsUrl) return shared.getWsUrl(location);
    return wsCandidates[Math.min(wsCandidateIndex, wsCandidates.length - 1)] || '';
  }

  function getApiUrl(path, params = {}){
    if (shared.getApiUrl) return shared.getApiUrl(path, params, location);
    const qs = new URLSearchParams(params).toString();
    const base = location.origin;
    return `${base}${path}${qs ? `?${qs}` : ''}`;
  }

  function getForwardSearch(){
    try{
      const u = new URL(window.location.href);
      u.searchParams.delete('token');
      const qs = u.searchParams.toString();
      return qs ? `?${qs}` : '';
    }catch{
      return '';
    }
  }

  function escapeHtml(value){
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function encodeData(value){
    return encodeURIComponent(String(value ?? ''));
  }

  const AUTH_STORAGE_KEY = 'rj.authToken';
  let authToken = '';
  let wsTicket = '';
  let authPromptResolver = null;
  let authInFlight = null;
  let authMode = 'login';
  let authRecoveryMode = false;
  let tailscaleReauthMode = false;

  function saveAuthToken(token){
    if (shared.saveToken){
      authToken = shared.saveToken(AUTH_STORAGE_KEY, token);
      return;
    }
    authToken = String(token || '').trim();
    try{
      if (authToken){
        sessionStorage.setItem(AUTH_STORAGE_KEY, authToken);
      } else {
        sessionStorage.removeItem(AUTH_STORAGE_KEY);
      }
    }catch{}
  }

  function loadAuthToken(){
    if (shared.loadToken){
      const stored = shared.loadToken(AUTH_STORAGE_KEY);
      if (stored) authToken = stored;
    } else {
      try{
        const stored = (sessionStorage.getItem(AUTH_STORAGE_KEY) || '').trim();
        if (stored) authToken = stored;
      }catch{}
    }

    const migrated = shared.migrateTokenFromUrl ? shared.migrateTokenFromUrl(AUTH_STORAGE_KEY, 'token') : '';
    if (migrated) authToken = migrated;
    if (migrated) return;

    // One-time migration: accept token from URL, then remove it.
    try{
      const u = new URL(window.location.href);
      const token = (u.searchParams.get('token') || '').trim();
      if (token){
        saveAuthToken(token);
        u.searchParams.delete('token');
        window.history.replaceState({}, '', u.toString());
      }
    }catch{}
  }

  function setAuthError(msg){
    if (!authModalError) return;
    const text = String(msg || '').trim();
    authModalError.textContent = text;
    authModalError.classList.toggle('hidden', !text);
  }

  function setAuthMode(mode, message){
    authMode = mode;
    if (authModalTitle){
      authModalTitle.textContent = mode === 'bootstrap' ? 'Create Admin Account' : 'Login Required';
    }
    if (authModalMessage){
      authModalMessage.textContent = message || (mode === 'bootstrap'
        ? 'Set the first admin account for this device.'
        : 'Log in to continue.');
    }
    const isBootstrap = mode === 'bootstrap';
    if (authModalRules) authModalRules.classList.toggle('hidden', !isBootstrap);
    if (authModalPasswordConfirm) authModalPasswordConfirm.classList.toggle('hidden', !isBootstrap);
    if (authModalUsername) authModalUsername.classList.toggle('hidden', authRecoveryMode);
    if (authModalPassword) authModalPassword.classList.toggle('hidden', authRecoveryMode);
    if (authModalToken) authModalToken.classList.toggle('hidden', !authRecoveryMode);
    if (authModalToggleRecovery){
      authModalToggleRecovery.classList.toggle('hidden', isBootstrap);
      authModalToggleRecovery.textContent = authRecoveryMode ? 'Use username/password login' : 'Use recovery token instead';
    }
    if (authModalConfirm) authModalConfirm.textContent = isBootstrap ? 'Create Admin' : 'Login';
  }

  function setRecoveryMode(enabled){
    authRecoveryMode = !!enabled;
    setAuthMode(authMode, authModalMessage ? authModalMessage.textContent : '');
    setAuthError('');
    if (authRecoveryMode){
      if (authModalToken) authModalToken.focus();
    } else if (authModalUsername) {
      authModalUsername.focus();
    }
  }

  function resolveAuthPrompt(payload){
    if (!authPromptResolver) return;
    const resolver = authPromptResolver;
    authPromptResolver = null;
    if (authModal) authModal.classList.add('hidden');
    resolver(payload || null);
  }

  function promptForAuth(message, mode = 'login'){
    if (!authModal || !authModalConfirm || !authModalCancel || !authModalClose){
      return Promise.resolve(null);
    }
    if (authPromptResolver){
      return Promise.resolve(null);
    }
    if (authModalUsername) authModalUsername.value = '';
    if (authModalPassword) authModalPassword.value = '';
    if (authModalPasswordConfirm) authModalPasswordConfirm.value = '';
    if (authModalToken) authModalToken.value = authToken || '';
    authRecoveryMode = false;
    setAuthMode(mode, message);
    setAuthError('');
    authModal.classList.remove('hidden');
    setTimeout(() => {
      try {
        if (mode === 'bootstrap'){
          authModalUsername && authModalUsername.focus();
        } else if (authModalUsername) {
          authModalUsername.focus();
        }
      } catch {}
    }, 10);
    return new Promise(resolve => {
      authPromptResolver = resolve;
    });
  }

  function authHeaders(extra){
    if (shared.authHeaders) return shared.authHeaders(authToken, extra);
    const headers = Object.assign({}, extra || {});
    if (authToken){
      headers.Authorization = `Bearer ${authToken}`;
    }
    return headers;
  }

  async function apiFetch(url, options = {}, allowRetry = true){
    const merged = Object.assign({}, options);
    merged.headers = authHeaders(merged.headers);
    merged.credentials = 'include';
    const res = await fetch(url, merged);
    if (res.status === 401 && allowRetry){
      const ok = await ensureAuthenticated('Session expired. Log in again.');
      if (ok){
        return apiFetch(url, options, false);
      }
    }
    return res;
  }

  async function fetchBootstrapStatus(){
    if (shared.fetchBootstrapStatus){
      return shared.fetchBootstrapStatus(getApiUrl.bind(null));
    }
    try{
      const res = await fetch(getApiUrl('/api/auth/bootstrap-status'), { cache: 'no-store' });
      const data = await res.json();
      return !!(res.ok && data && data.initialized);
    }catch{
      return true;
    }
  }

  async function fetchAuthMe(){
    if (shared.fetchAuthMe){
      return shared.fetchAuthMe(getApiUrl.bind(null), authToken);
    }
    try{
      const res = await fetch(getApiUrl('/api/auth/me'), {
        cache: 'no-store',
        credentials: 'include',
        headers: authHeaders({}),
      });
      if (!res.ok) return null;
      const data = await res.json();
      return data && data.authenticated ? data : null;
    }catch{
      return null;
    }
  }

  async function attemptBootstrap(message){
    const input = await promptForAuth(message || 'Set the first admin account for this device.', 'bootstrap');
    if (!input) return false;
    const username = String(input.username || '').trim();
    const password = String(input.password || '');
    const confirm = String(input.confirm || '');
    if (!username || !password){
      setAuthError('Username and password are required.');
      return attemptBootstrap(message);
    }
    if (username.length < 3){
      setAuthError('username must be at least 3 characters');
      return attemptBootstrap(message);
    }
    if (username.length > 32){
      setAuthError('username too long');
      return attemptBootstrap(message);
    }
    if (password.length < 8){
      setAuthError('password must be at least 8 characters');
      return attemptBootstrap(message);
    }
    if (password !== confirm){
      setAuthError('Passwords do not match.');
      return attemptBootstrap(message);
    }
    try{
      const res = await fetch(getApiUrl('/api/auth/bootstrap'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok){
        if (res.status === 409){
          return attemptLogin('Admin already exists. Log in to continue.');
        }
        setAuthError(data && data.error ? data.error : 'Bootstrap failed');
        return attemptBootstrap(message);
      }
      // Save the signed session token returned in the body as a Bearer
      // fallback in case the browser dropped the Set-Cookie header.
      if (data && data.token) saveAuthToken(data.token);
      else saveAuthToken('');
      return true;
    }catch{
      setAuthError('Bootstrap request failed.');
      return attemptBootstrap(message);
    }
  }

  async function attemptLogin(message){
    const input = await promptForAuth(message || 'Log in to continue.', 'login');
    if (!input) return false;

    if (input.recovery){
      const token = String(input.token || '').trim();
      if (!token){
        setAuthError('Recovery token is required.');
        return attemptLogin(message);
      }
      saveAuthToken(token);
      try{
        const meRes = await fetch(getApiUrl('/api/auth/me'), {
          cache: 'no-store',
          headers: authHeaders({}),
          credentials: 'include',
        });
        if (!meRes.ok){
          setAuthError('Invalid recovery token.');
          return attemptLogin(message);
        }
        return true;
      }catch{
        setAuthError('Recovery auth failed.');
        return attemptLogin(message);
      }
    }

    const username = String(input.username || '').trim();
    const password = String(input.password || '');
    if (!username || !password){
      setAuthError('Username and password are required.');
      return attemptLogin(message);
    }
    try{
      const res = await fetch(getApiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok){
        setAuthError(data && data.error ? data.error : 'Login failed');
        return attemptLogin(message);
      }
      if (data && data.token) saveAuthToken(data.token);
      else saveAuthToken('');
      return true;
    }catch{
      setAuthError('Login request failed.');
      return attemptLogin(message);
    }
  }

  async function refreshWsTicket(){
    wsTicket = '';
    if (shared.refreshWsTicket){
      wsTicket = await shared.refreshWsTicket(getApiUrl.bind(null), authToken);
      return;
    }
    if (authToken) return;
    try{
      const res = await fetch(getApiUrl('/api/auth/ws-ticket'), {
        method: 'POST',
        credentials: 'include',
      });
      const data = await res.json();
      if (res.ok && data && data.ticket){
        wsTicket = String(data.ticket);
      }
    }catch{}
  }

  async function ensureAuthenticated(message){
    if (authInFlight){
      return authInFlight;
    }
    authInFlight = (async () => {
      const me = await fetchAuthMe();
      if (me){
        await refreshWsTicket();
        return true;
      }

    const initialized = await fetchBootstrapStatus();
    if (!initialized){
      const bootOk = await attemptBootstrap(message);
      if (!bootOk) return false;
      await refreshWsTicket();
      return true;
    }
    const loginOk = await attemptLogin(message);
    if (!loginOk) return false;
    await refreshWsTicket();
    return true;
    })();
    try{
      return await authInFlight;
    } finally {
      authInFlight = null;
    }
  }

  async function logoutUser(){
    try{
      await fetch(getApiUrl('/api/auth/logout'), { method: 'POST', credentials: 'include' });
    }catch{}
    saveAuthToken('');
    wsTicket = '';
    try{
      if (ws) ws.close();
    }catch{}
    window.location.reload();
  }

  let ws = null;
  let reconnectTimer = null;
  let wsConnectTimer = null;
  let lastServerMessage = Date.now();
  let reconnectAttempts = 0;
  const WS_CONNECT_TIMEOUT = 5000;
  const SERVER_HEARTBEAT_TIMEOUT = 15000;
  const HEARTBEAT_CHECK_INTERVAL = 5000;
  const pressed = new Set(); // keyboard pressed state
  let activeTab = 'device';
  let lootState = { path: '', parent: '' };
  let nmapVizState = { data: null, jsonUrl: '' };
  let payloadState = { categories: [], open: {}, activePath: null };
  let term = null;
  let fitAddon = null;
  let shellOpen = false;
  let terminalHasFocus = false;
  let shellWanted = false;
  let systemOpen = false;
  let mobileSystemTabActive = false;
  let wsAuthenticated = true;

  function applyStatusTone(el, txt){
    if (!el) return;
    const s = String(txt || '').toLowerCase();
    el.classList.remove('status-tone-ok', 'status-tone-warn', 'status-tone-bad');
    if (/connected|authenticated|ready|live|saved|configured|launched|running/.test(s)) {
      el.classList.add('status-tone-ok');
    } else if (/loading|connecting|opening|reconnecting|stopping/.test(s)) {
      el.classList.add('status-tone-warn');
    } else if (/failed|unavailable|disconnected|error|denied/.test(s)) {
      el.classList.add('status-tone-bad');
    }
  }

  function setStatus(txt){
    const s = String(txt || '').toLowerCase();
    let state = 'bad';
    if (/connected|authenticated|ready|live/.test(s)) state = 'ok';
    else if (/loading|connecting|opening|reconnecting|stopping/.test(s)) state = 'connecting';
    if (statusEl) {
      statusEl.textContent = '';
      statusEl.dataset.state = state;
      statusEl.title = txt;
      applyStatusTone(statusEl, txt);
    }
    if (statusEls && statusEls.length) {
      statusEls.forEach(el => {
        el.textContent = '';
        el.dataset.state = state;
        el.title = txt;
        applyStatusTone(el, txt);
      });
    }
  }

  function setPayloadStatus(txt){
    if (payloadStatus) {
      payloadStatus.textContent = txt;
      applyStatusTone(payloadStatus, txt);
    }
    if (payloadStatusDot){
      const active = /running|starting|stopping|launched/i.test(String(txt || ''));
      payloadStatusDot.classList.toggle('running', active);
    }
  }

  function setSystemStatus(txt){
    if (systemStatus) {
      systemStatus.textContent = txt;
      applyStatusTone(systemStatus, txt);
    }
  }

  function resolveSdrUrl(){
    const host = window.location.hostname || window.location.host.split(':')[0];
    const targetHost = host || 'ktox.local';
    return `http://${targetHost}:8081/`;
  }

  function setShellStatus(txt){
    if (shellStatusEl) {
      shellStatusEl.textContent = txt;
      applyStatusTone(shellStatusEl, txt);
    }
  }

  function setSettingsStatus(txt){
    if (settingsStatus) {
      settingsStatus.textContent = txt;
      applyStatusTone(settingsStatus, txt);
    }
  }

  function setTailscaleStatus(txt){
    if (tailscaleSettingsStatus){
      tailscaleSettingsStatus.textContent = txt;
      applyStatusTone(tailscaleSettingsStatus, txt);
    }
  }

  // Handheld themes (frontend-only)
  const layoutDefault = document.querySelector('.layout-default');
  const layoutGameboy = document.querySelector('.layout-gameboy');
  const layoutPager = document.querySelector('.layout-pager');
  const layoutSyndicate = document.querySelector('.layout-syndicate');
  const themes = [
    { id: 'neon', label: 'Neon' },
    { id: 'syndicate', label: 'Syndicate' },
    { id: 'gameboy', label: 'Game Boy' },
    { id: 'pager', label: 'Pager' },
  ];
  const THEME_STORAGE_KEY = 'rj.defaultTheme';
  let themeIndex = 0;

  function saveThemePreference(themeId){
    try{
      localStorage.setItem(THEME_STORAGE_KEY, themeId);
    }catch{}
  }

  function loadThemePreference(){
    try{
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      if (!saved) return;
      const idx = themes.findIndex(t => t.id === saved);
      if (idx >= 0) themeIndex = idx;
    }catch{}
  }

  function applyTheme(){
    const t = themes[themeIndex];
    if (!deviceShell) return;
    ensureDeviceShellChild(layoutSyndicate);
    deviceShell.classList.remove('theme-neon', 'theme-syndicate', 'theme-gameboy', 'theme-pager');
    deviceShell.classList.add(`theme-${t.id}`);
    deviceShell.setAttribute('data-theme', t.id);
    setLayoutVisible(layoutDefault, t.id === 'neon');
    setLayoutVisible(layoutSyndicate, t.id === 'syndicate');
    setLayoutVisible(layoutGameboy, t.id === 'gameboy');
    setLayoutVisible(layoutPager, t.id === 'pager');
    if (themeNameEl) themeNameEl.textContent = t.label;
    themeButtons.forEach(btn => {
      const isActive = btn.getAttribute('data-theme') === t.id;
      btn.classList.toggle('bg-red-800/20', isActive);
      btn.classList.toggle('text-red-400', isActive);
      btn.classList.toggle('border-red-400/40', isActive);
      btn.classList.toggle('bg-slate-900/40', !isActive);
      btn.classList.toggle('text-slate-300', !isActive);
      btn.classList.toggle('border-slate-500/20', !isActive);
    });
  }

  // Screen rotation support
  const ROTATION_STORAGE_KEY = 'rj.screenRotation';
  let currentRotation = 0;

  function loadRotationPreference(){
    try {
      const saved = localStorage.getItem(ROTATION_STORAGE_KEY);
      if (saved) currentRotation = parseInt(saved, 10);
    } catch {}
  }

  function applyRotation(){
    if (!deviceShell) return;
    deviceShell.classList.remove('rotate-0', 'rotate-90', 'rotate-180', 'rotate-270');
    deviceShell.classList.add(`rotate-${currentRotation}`);
    applyButtonRotation();
  }

  function applyButtonRotation(){
    const buttons = document.querySelectorAll('[data-btn]');
    buttons.forEach(btn => {
      btn.dataset.rotation = currentRotation;
    });
  }

  function setRotation(degrees){
    currentRotation = degrees;
    try {
      localStorage.setItem(ROTATION_STORAGE_KEY, degrees);
    } catch {}
    applyRotation();
  }

  function setLayoutVisible(layout, visible){
    if (!layout) return;
    layout.classList.toggle('hidden', !visible);
  }

  function ensureDeviceShellChild(node){
    if (!deviceShell || !node || node.parentElement === deviceShell) return;
    deviceShell.appendChild(node);
  }

  function setSidebarOpen(open){
    if (!sidebar) return;
    sidebar.classList.toggle('-translate-x-full', !open);
    sidebar.classList.toggle('translate-x-0', open);
    if (sidebarBackdrop) {
      sidebarBackdrop.classList.toggle('hidden', !open);
    }
  }

  function setNavActive(btn, active){
    if (!btn) return;
    btn.classList.toggle('nav-active', active);
    btn.classList.toggle('bg-red-800/10', active);
    btn.classList.toggle('text-red-400', active);
    btn.classList.toggle('border-red-400/30', active);
    btn.classList.toggle('shadow-[0_0_16px_rgba(139,0,0,0.2)]', active);
    btn.classList.toggle('bg-slate-800/40', !active);
    btn.classList.toggle('text-slate-300', !active);
    btn.classList.toggle('border-slate-400/20', !active);
  }

  function setActiveTab(tab){
    activeTab = tab;
    const isDevice = tab === 'device' || tab === 'terminal';
    if (deviceTab) {
      deviceTab.classList.toggle('hidden', !isDevice);
      deviceTab.classList.toggle('terminal-mode', tab === 'terminal');
      deviceTab.classList.toggle('mobile-device-focus', tab === 'device');
      deviceTab.classList.toggle('mobile-terminal-focus', tab === 'terminal');
    }
    if (settingsTab) settingsTab.classList.toggle('hidden', tab !== 'settings');
    if (pentestTab) pentestTab.classList.toggle('hidden', tab !== 'pentest');
    if (tab === 'pentest') { ensureDesktopConsole(); ensurePentestConsole(); }
    if (lokiTab) lokiTab.classList.toggle('hidden', tab !== 'loki');
    if (tab === 'loki') ensureLokiConsole();
    if (lootTab) lootTab.classList.toggle('hidden', tab !== 'loot');
    const systemTabEl = document.getElementById('systemTab');
    if (systemTabEl) systemTabEl.classList.toggle('hidden', tab !== 'system');
    const payloadsTabEl = document.getElementById('payloadsTab');
    if (payloadsTabEl) payloadsTabEl.classList.toggle('hidden', tab !== 'payloads');
    if (tab === 'payloads') loadGameCenter();
    setNavActive(navDevice, tab === 'device');
    setNavActive(navPentest, tab === 'pentest');
    setNavActive(navLoki, tab === 'loki');
    setNavActive(navLoot, tab === 'loot');
    setNavActive(navSettings, tab === 'settings');
    setSidebarOpen(false);
    // Sync mobile bottom nav active state
    document.querySelectorAll('[data-mobnav]').forEach(btn => {
      btn.classList.toggle('mob-nav-active', btn.dataset.mobnav === tab);
    });
    // Track mobile system tab state for polling
    mobileSystemTabActive = (tab === 'system');
    // Refit terminal when switching to terminal tab
    if (tab === 'terminal' && fitAddon) {
      requestAnimationFrame(() => { try { fitAddon.fit(); } catch{} });
    }
  }

  function setGameCenterStatus(text){
    if (gameCenterStatus) gameCenterStatus.textContent = text;
  }

  function fillSelect(el, items, mapper){
    if (!el) return;
    el.innerHTML = '';
    items.forEach((item, idx) => {
      const opt = document.createElement('option');
      const mapped = mapper(item, idx);
      opt.value = mapped.value;
      opt.textContent = mapped.label;
      el.appendChild(opt);
    });
  }

  async function loadGameCenter(){
    setGameCenterStatus('Loading Game Center…');
    try{
      const [centerRes, healthRes] = await Promise.all([
        apiFetch(getApiUrl('/api/games/center'), { cache: 'no-store' }),
        apiFetch(getApiUrl('/api/games/emulators/health'), { cache: 'no-store' }),
      ]);
      if (!centerRes.ok || !healthRes.ok) throw new Error(`HTTP ${centerRes.status}/${healthRes.status}`);
      const center = await centerRes.json();
      const health = await healthRes.json();
      gameCenterState = {
        emulators: Array.isArray(center.emulators) ? center.emulators : [],
        roms: Array.isArray(center.roms) ? center.roms : [],
      };
      fillSelect(gameCenterEmulator, gameCenterState.emulators, (e) => ({
        value: String(e.id || ''),
        label: `${e.label || e.id || 'emulator'} (${e.id || 'unknown'})`
      }));
      fillSelect(gameCenterRom, gameCenterState.roms, (r) => ({
        value: String(r.path || ''),
        label: `${r.name || r.path || 'rom'}`
      }));
      const installedCount = Array.isArray(health.emulators)
        ? health.emulators.filter(e => e && e.installed).length
        : 0;
      const total = Array.isArray(health.emulators) ? health.emulators.length : 0;
      setGameCenterStatus(`Emulators installed: ${installedCount}/${total} • ROMs: ${gameCenterState.roms.length} • WebUI Port: ${health.webui_port || 'unknown'}`);
    } catch (err){
      setGameCenterStatus(`Game Center error: ${err.message || err}`);
    }
  }

  async function installGameCenterEmulators(){
    setGameCenterStatus('Installing missing emulators…');
    try{
      const res = await apiFetch(getApiUrl('/api/games/emulators/install'), { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      const count = Array.isArray(data.installed) ? data.installed.length : 0;
      setGameCenterStatus(count ? `Installed: ${data.installed.join(', ')}` : 'No packages needed.');
      await loadGameCenter();
    } catch (err){
      setGameCenterStatus(`Install failed: ${err.message || err}`);
    }
  }

  async function playSelectedGame(){
    const emulator = gameCenterEmulator ? String(gameCenterEmulator.value || '').trim() : '';
    const rom = gameCenterRom ? String(gameCenterRom.value || '').trim() : '';
    if (!emulator || !rom){
      setGameCenterStatus('Choose emulator + ROM first.');
      return;
    }
    setGameCenterStatus('Queueing game launch…');
    try{
      const res = await apiFetch(getApiUrl('/api/games/play'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emulator, rom }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      setGameCenterStatus(`Launch queued: ${emulator} -> ${rom}`);
    } catch (err){
      setGameCenterStatus(`Play failed: ${err.message || err}`);
    }
  }

  function setSystemOpen(open){
    systemOpen = !!open;
    if (systemDropdown){
      systemDropdown.classList.toggle('hidden', !systemOpen);
    }
    setNavActive(navSystem, systemOpen);
    if (systemOpen){
      loadSystemStatus();
    }
  }

  function setThemeById(id){
    const idx = themes.findIndex(t => t.id === id);
    if (idx >= 0){
      themeIndex = idx;
      applyTheme();
      saveThemePreference(id);
    }
  }

  function connect(){
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const url = getWsUrl();
    if (!url){
      setStatus('Disconnected');
      scheduleReconnect();
      return;
    }
    setStatus('Connecting');
    try{
      ws = new WebSocket(url);
    } catch(e){
      setStatus('WebSocket failed to construct');
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      if (wsConnectTimer) clearTimeout(wsConnectTimer);
      wsConnectTimer = null;
      lastServerMessage = Date.now();
      reconnectAttempts = 0;
      wsCandidateIndex = 0;
      setStatus('Connected');
      wsAuthenticated = true;
      if (wsTicket){
        try{
          ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket }));
        }catch{}
      } else if (authToken){
        try{
          ws.send(JSON.stringify({ type: 'auth', token: authToken }));
        }catch{}
      }
      if (shellWanted) {
        sendShellOpen();
      }
    };

    wsConnectTimer = setTimeout(() => {
      if (ws && ws.readyState === WebSocket.CONNECTING){
        try { ws.close(); } catch {}
      }
    }, WS_CONNECT_TIMEOUT);

    ws.onmessage = (ev) => {
      lastServerMessage = Date.now();
      try{
        const msg = JSON.parse(ev.data);
        if (msg.type === 'frame' && msg.data){
          const img = new Image();
          img.onload = () => {
            try {
              ctx.clearRect(0,0,canvas.width,canvas.height);
              ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
              if (ctxGb && canvasGb) {
                ctxGb.clearRect(0,0,canvasGb.width,canvasGb.height);
                ctxGb.drawImage(img, 0, 0, canvasGb.width, canvasGb.height);
              }
              if (ctxPager && canvasPager) {
                ctxPager.clearRect(0,0,canvasPager.width,canvasPager.height);
                ctxPager.drawImage(img, 0, 0, canvasPager.width, canvasPager.height);
              }
              if (ctxSyndicate && canvasSyndicate) {
                ctxSyndicate.clearRect(0,0,canvasSyndicate.width,canvasSyndicate.height);
                ctxSyndicate.drawImage(img, 0, 0, canvasSyndicate.width, canvasSyndicate.height);
              }
            } catch {}
          };
          img.src = 'data:image/jpeg;base64,' + msg.data;
          return;
        }
        if (msg.type === 'auth_required'){
          wsAuthenticated = false;
          if (wsTicket){
            try{
              ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket }));
            }catch{}
            return;
          }
          if (authToken){
            try{
              ws.send(JSON.stringify({ type: 'auth', token: authToken }));
            }catch{}
            return;
          }
          ensureAuthenticated('Authentication required to use WebSocket.')
            .then(() => {
              if (!ws || ws.readyState !== WebSocket.OPEN) return;
              if (wsTicket){
                try{
                  ws.send(JSON.stringify({ type: 'auth_session', ticket: wsTicket }));
                }catch{}
              } else if (authToken){
                try{
                  ws.send(JSON.stringify({ type: 'auth', token: authToken }));
                }catch{}
              }
            });
          return;
        }
        if (msg.type === 'auth_ok'){
          wsAuthenticated = true;
          setStatus('Authenticated');
          if (shellWanted) sendShellOpen();
          return;
        }
        if (msg.type === 'auth_error'){
          wsAuthenticated = false;
          setStatus('Auth failed');
          return;
        }
        if (msg.type === 'shell_ready'){
          shellOpen = true;
          setShellStatus('Connected');
          sendShellResize();
          return;
        }
        if (msg.type === 'shell_out' && msg.data){
          ensureTerminal();
          if (term) term.write(msg.data);
          return;
        }
        if (msg.type === 'shell_exit'){
          shellOpen = false;
          setShellStatus('Exited');
        }
      }catch{}
    };

    ws.onclose = () => {
      if (wsConnectTimer) clearTimeout(wsConnectTimer);
      wsConnectTimer = null;
      setStatus('Disconnected – reconnecting…');
      setShellStatus('Disconnected');
      shellOpen = false;
      scheduleReconnect();
    };

    ws.onerror = () => {
      try { ws.close(); } catch {}
    };
  }

  function scheduleReconnect(){
    if (reconnectTimer) return;
    if (wsCandidates.length > 1){
      wsCandidateIndex = (wsCandidateIndex + 1) % wsCandidates.length;
    }
    reconnectAttempts += 1;
    const delay = Math.min(6000, 1000 + reconnectAttempts * 500);
    reconnectTimer = setTimeout(()=>{
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function ensureSocketLive(){
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING){
      ws = null;
      connect();
    }
  }

  function startHeartbeatMonitor(){
    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN && Date.now() - lastServerMessage > SERVER_HEARTBEAT_TIMEOUT){
        try { ws.close(); } catch {}
        scheduleReconnect();
      } else if (!document.hidden && (!ws || ws.readyState !== WebSocket.OPEN)) {
        ensureSocketLive();
      }
    }, HEARTBEAT_CHECK_INTERVAL);
  }

  function ensureTerminal(){
    if (!terminalEl) return null;
    if (!window.Terminal){
      setShellStatus('xterm missing');
      return null;
    }
    if (!term){
      term = new window.Terminal({
        cursorBlink: true,
        fontSize: 13,
        theme: {
          background: 'transparent',
          foreground: '#e2e8f0',
          cursor: '#94a3b8'
        }
      });
      if (window.FitAddon && window.FitAddon.FitAddon){
        fitAddon = new window.FitAddon.FitAddon();
        term.loadAddon(fitAddon);
      }
      term.open(terminalEl);
      term.onData(data => sendShellInput(data));
      if (terminalEl){
        terminalEl.addEventListener('focusin', () => { terminalHasFocus = true; });
        terminalEl.addEventListener('focusout', () => { terminalHasFocus = false; });
        terminalEl.addEventListener('mousedown', () => {
          try { term.focus(); } catch {}
        });
      }
      if (fitAddon){
        try { fitAddon.fit(); } catch {}
      }
      term.write('KTOx shell ready.\r\n');
    }
    return term;
  }

  function sendShellInput(data){
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!shellOpen) return;
    try{
      ws.send(JSON.stringify({ type: 'shell_in', data }));
    }catch{}
  }

  function sendShellOpen(){
    shellWanted = true;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ensureTerminal();
    setShellStatus('Opening...');
    try{
      ws.send(JSON.stringify({ type: 'shell_open' }));
    }catch{}
  }

  function sendShellClose(){
    shellWanted = false;
    if (ws && ws.readyState === WebSocket.OPEN){
      try{
        ws.send(JSON.stringify({ type: 'shell_close' }));
      }catch{}
    }
    shellOpen = false;
    setShellStatus('Closed');
  }

  function sendShellResize(){
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!shellOpen || !term) return;
    if (fitAddon){
      try { fitAddon.fit(); } catch {}
    }
    try{
      ws.send(JSON.stringify({ type: 'shell_resize', cols: term.cols, rows: term.rows }));
    }catch{}
  }

  function formatBytes(bytes){
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
    const value = bytes / Math.pow(k, i);
    return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${sizes[i]}`;
  }

  function formatDuration(totalSec){
    const s = Math.max(0, Number(totalSec || 0) | 0);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function pct(used, total){
    if (!total || total <= 0) return 0;
    return Math.max(0, Math.min(100, (used / total) * 100));
  }

  function bar(el, value){
    if (!el) return;
    el.style.width = `${Math.max(0, Math.min(100, value)).toFixed(1)}%`;
  }

  function pentestProxyUrl(){
    const search = window.location.search || '';
    return `${location.origin}/pentest/${search}`;
  }

  function desktopProxyUrl(data){
    const search = window.location.search || '';
    const basePath = data && data.proxy_path ? String(data.proxy_path) : '/desktop/vnc.html?autoconnect=true&resize=remote&path=desktop/websockify';
    const join = search ? `${basePath.includes('?') ? '&' : '?'}${search.slice(1)}` : '';
    return `${location.origin}${basePath}${join}`;
  }

  function desktopDirectUrl(data){
    const base = data && data.embed_url ? String(data.embed_url) : '';
    if (window.location.protocol === 'https:') return desktopProxyUrl(data);
    return base;
  }

  function lokiProxyUrl(){
    const search = window.location.search || '';
    return `${location.origin}/loki/${search}`;
  }

  function lokiDisplayUrl(directUrl){
    return directUrl ? lokiProxyUrl() : '';
  }

  function loadPentestConsole(force = false){
    if (!pentestFrame) return;
    const src = pentestProxyUrl();
    if (force || pentestFrame.getAttribute('src') !== src){
      pentestFrame.setAttribute('src', src);
    }
  }

  let lastDesktopData = {};
  let desktopAutoStartInFlight = false;

  function loadDesktopConsole(force = false){
    if (!desktopFrame) return;
    const src = desktopDirectUrl(lastDesktopData) || desktopProxyUrl(lastDesktopData);
    if (force || desktopFrame.getAttribute('src') !== src){
      desktopFrame.setAttribute('src', src);
    }
  }

  async function ensureDesktopConsole(){
    const running = lastDesktopData && lastDesktopData.running;
    if (running){
      loadDesktopConsole(false);
      return;
    }
    if (!desktopAutoStartInFlight){
      desktopAutoStartInFlight = true;
      try{
        await controlDesktop('start');
      } finally {
        desktopAutoStartInFlight = false;
      }
    }
  }

  function ensurePentestConsole(){
    const running = pentestStatus && pentestStatus.textContent === 'running';
    if (running) loadPentestConsole(false);
  }

  function setLokiFrameVisible(visible){
    if (lokiFrame) lokiFrame.classList.toggle('hidden', !visible);
    if (lokiFrameEmpty) lokiFrameEmpty.classList.toggle('hidden', visible);
  }

  function loadLokiConsole(force = false){
    if (!lokiFrame) return;
    const src = lokiProxyUrl();
    if (force || lokiFrame.getAttribute('src') !== src){
      lokiFrame.setAttribute('src', src);
    }
    setLokiFrameVisible(true);
  }

  function ensureLokiConsole(){
    const running = lokiStatus && lokiStatus.textContent === 'running';
    if (running) loadLokiConsole(false);
  }

  function applyDesktopData(desktop){
    const data = desktop || {};
    lastDesktopData = data;
    const running = !!data.running;
    const url = desktopDirectUrl(data);
    const install = data.install || {};
    const missingDeps = Array.isArray(data.missing) && data.missing.length ? data.missing : [];
    const depsMissing = data.installed === false || missingDeps.length > 0;
    const installingDeps = !!install.installing;
    if (desktopFrameStatus){
      if (running){
        desktopFrameStatus.textContent = data.mode === 'existing' ? 'Connected to the existing Kali X desktop. This is not the KTOX LCD mirror.' : 'Kali desktop session is ready below. This controls a real Kali desktop on the device, not the KTOX LCD mirror.';
      } else if (installingDeps){
        desktopFrameStatus.textContent = install.message || 'Installing Kali desktop dependencies...';
      } else if (depsMissing){
        desktopFrameStatus.textContent = `Desktop dependencies missing: ${missingDeps.join(', ') || 'required packages'}`;
      } else {
        desktopFrameStatus.textContent = 'Open Pentest to start the Kali desktop. noVNC controls Kali Linux, not the KTOX LCD mirror.';
      }
    }
    if (desktopFrameInstallDeps){
      desktopFrameInstallDeps.classList.toggle('hidden', !depsMissing || running);
      desktopFrameInstallDeps.disabled = installingDeps;
      desktopFrameInstallDeps.classList.toggle('opacity-60', installingDeps);
      desktopFrameInstallDeps.textContent = installingDeps ? 'Installing Deps...' : 'Install Desktop Deps';
    }
    if (desktopFrameStart){
      desktopFrameStart.disabled = installingDeps || depsMissing;
      desktopFrameStart.classList.toggle('opacity-60', installingDeps || depsMissing);
    }
    if (desktopFrameExternal){
      desktopFrameExternal.href = url || '#';
      desktopFrameExternal.classList.toggle('pointer-events-none', !url);
    }
    if (running && activeTab === 'pentest') loadDesktopConsole(false);
    if (!running && desktopFrame) desktopFrame.removeAttribute('src');
  }

  function applyPentestData(pentest, target = 'desktop'){
    const data = pentest || {};
    const running = !!data.running;
    const statusText = running ? 'running' : 'stopped';
    const url = data.url || '';
    const statusEl = target === 'mobile' ? mobPentestStatus : pentestStatus;
    const urlEl = target === 'mobile' ? mobPentestUrl : pentestUrl;
    if (statusEl){
      statusEl.textContent = statusText;
      statusEl.classList.toggle('text-emerald-300', running);
      statusEl.classList.toggle('text-slate-400', !running);
    }
    if (urlEl){
      urlEl.textContent = url || 'No URL';
      if (url){
        urlEl.href = url;
        urlEl.classList.remove('pointer-events-none');
      } else {
        urlEl.href = '#';
        urlEl.classList.add('pointer-events-none');
      }
    }
    if (pentestFrameStatus){
      pentestFrameStatus.textContent = running
        ? 'Tool console is ready below. Use it to create engagements, run tools, stop jobs, and view findings.'
        : 'Start the server to load the tool console.';
    }
    if (pentestFrameExternal){
      pentestFrameExternal.href = url || '#';
      pentestFrameExternal.classList.toggle('pointer-events-none', !url);
    }
    if (target === 'desktop' && running && activeTab === 'pentest') loadPentestConsole(false);
    if (!running && pentestFrame) pentestFrame.removeAttribute('src');
  }


  function applyLokiData(loki){
    const data = loki || {};
    const running = !!data.running;
    const statusText = running ? 'running' : 'stopped';
    const url = data.url || '';
    if (lokiStatus){
      lokiStatus.textContent = statusText;
      lokiStatus.classList.toggle('text-emerald-300', running);
      lokiStatus.classList.toggle('text-slate-400', !running);
    }
    if (lokiUrl){
      lokiUrl.textContent = url || 'No URL';
      if (url){
        lokiUrl.href = lokiDisplayUrl(url);
        lokiUrl.classList.remove('pointer-events-none');
      } else {
        lokiUrl.href = '#';
        lokiUrl.classList.add('pointer-events-none');
      }
    }
    if (lokiFrameStatus){
      lokiFrameStatus.textContent = running
        ? 'Loki reconnaissance console is ready below.'
        : (data.installed === false ? 'Loki is not installed. Run setup_loki.sh first.' : 'Start Loki to load the reconnaissance console.');
    }
    if (lokiFrameExternal){
      lokiFrameExternal.href = lokiDisplayUrl(url) || '#';
      lokiFrameExternal.classList.toggle('pointer-events-none', !url);
    }
    if (running && activeTab === 'loki') loadLokiConsole(false);
    if (!running && lokiFrame){
      lokiFrame.removeAttribute('src');
      setLokiFrameVisible(false);
    }
  }

  function applySdrServiceData(sdr){
    const data = sdr || {};
    const installed = data.installed !== false;
    const running = !!data.running;
    const disabled = !!data.disabled;
    const state = running ? 'running' : (disabled ? 'disabled' : String(data.active_state || 'stopped'));
    if (sdrServiceToggle){
      sdrServiceToggle.dataset.installed = installed ? '1' : '0';
      sdrServiceToggle.checked = running && !disabled;
      sdrServiceToggle.disabled = !installed;
    }
    if (sdrServiceStart) sdrServiceStart.disabled = !installed || running;
    if (sdrServiceStop) sdrServiceStop.disabled = !installed || (!running && disabled);
    if (sdrServiceOpen){
      sdrServiceOpen.href = resolveSdrUrl();
      sdrServiceOpen.classList.toggle('opacity-50', !running);
      sdrServiceOpen.classList.toggle('pointer-events-none', !running);
      sdrServiceOpen.title = running ? 'Open SDR Suite' : 'Start SDR service first';
    }
    if (sdrServiceState){
      sdrServiceState.textContent = state;
      sdrServiceState.classList.toggle('text-emerald-300', running);
      sdrServiceState.classList.toggle('text-amber-300', disabled);
      sdrServiceState.classList.toggle('text-slate-400', !running && !disabled);
    }
    if (sdrServiceStatus){
      if (!installed){
        sdrServiceStatus.textContent = 'SDR service is not installed. Run scripts/install_sdr.sh before enabling it.';
      } else if (running){
        sdrServiceStatus.textContent = 'SDR Suite is active. Stop it when you need to save memory.';
      } else if (disabled){
        sdrServiceStatus.textContent = 'SDR is disabled and stopped. Memory-saving mode is active.';
      } else {
        sdrServiceStatus.textContent = `SDR service is ${state}. Start it when needed.`;
      }
      applyStatusTone(sdrServiceStatus, running ? 'running' : (disabled ? 'disabled' : state));
    }
    if (navSdr){
      navSdr.classList.toggle('opacity-50', !running);
      navSdr.title = running ? 'Open SDR Suite' : 'SDR service is not running. Toggle SDR Service on first.';
    }
  }

  async function loadSdrServiceStatus(){
    try{
      const res = await apiFetch(getApiUrl('/api/sdr/status'), { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.error ? data.error : 'sdr_status_failed');
      applySdrServiceData(data);
    } catch(e){
      if (sdrServiceStatus) {
        sdrServiceStatus.textContent = e && e.message ? e.message : 'SDR status unavailable';
        applyStatusTone(sdrServiceStatus, 'failed');
      }
    }
  }

  async function controlSdrService(action){
    const controls = [sdrServiceToggle, sdrServiceStart, sdrServiceOpen, sdrServiceStop, sdrServiceRefresh].filter(Boolean);
    controls.forEach(control => {
      if ('disabled' in control) control.disabled = true;
      control.classList.add('opacity-60');
    });
    if (sdrServiceStatus) sdrServiceStatus.textContent = action === 'disable' ? 'Stopping SDR service...' : 'Starting SDR service...';
    try{
      const res = await apiFetch(getApiUrl('/api/sdr/control'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      const data = await res.json();
      if (!res.ok || (data && data.ok === false)){
        throw new Error(data && data.error ? data.error : 'sdr_control_failed');
      }
      applySdrServiceData(data);
      await loadSystemStatus();
    } catch(e){
      if (sdrServiceStatus) {
        sdrServiceStatus.textContent = e && e.message ? e.message : 'SDR control failed';
        applyStatusTone(sdrServiceStatus, 'failed');
      }
      await loadSdrServiceStatus();
    } finally {
      controls.forEach(control => {
        if ('disabled' in control) control.disabled = control === sdrServiceToggle && control.dataset.installed === '0';
        control.classList.remove('opacity-60');
      });
    }
  }

  function applySystemData(data, target = 'desktop'){
    const cpu = Number(data.cpu_percent || 0);
    const memUsed = Number(data.mem_used || 0);
    const memTotal = Number(data.mem_total || 0);
    const diskUsed = Number(data.disk_used || 0);
    const diskTotal = Number(data.disk_total || 0);
    const memPercent = pct(memUsed, memTotal);
    const diskPercent = pct(diskUsed, diskTotal);
    const tempText = data.temp_c === null || data.temp_c === undefined
      ? '--.- C'
      : `${Number(data.temp_c).toFixed(1)} C`;
    const loadText = Array.isArray(data.load) ? data.load.join(', ') : '-';
    const payloadText = data.payload_running ? (data.payload_path || 'running') : 'none';
    const ifaces = Array.isArray(data.interfaces) ? data.interfaces : [];
    applyPentestData(data.pentest || {}, target);
    applyLokiData(data.loki || {});
    applyDesktopData(data.desktop || {});
    applySdrServiceData(data.sdr || {});
    const interfacesHtml = ifaces.length
      ? ifaces.map(i => `<div><span class="text-red-400">${escapeHtml(String(i.name || '-'))}</span>: ${escapeHtml(String(i.ipv4 || '-'))}</div>`).join('')
      : '<div class="text-slate-500">No active interfaces</div>';

    if (target === 'mobile'){
      if (mobSysCpuValue) mobSysCpuValue.textContent = `${cpu.toFixed(1)}%`;
      if (mobSysTempValue) mobSysTempValue.textContent = tempText;
      bar(mobSysCpuBar, cpu);
      if (mobSysMemValue) mobSysMemValue.textContent = `${memPercent.toFixed(1)}%`;
      if (mobSysMemMeta) mobSysMemMeta.textContent = `${formatBytes(memUsed)} / ${formatBytes(memTotal)}`;
      bar(mobSysMemBar, memPercent);
      if (mobSysDiskValue) mobSysDiskValue.textContent = `${diskPercent.toFixed(1)}%`;
      if (mobSysDiskMeta) mobSysDiskMeta.textContent = `${formatBytes(diskUsed)} / ${formatBytes(diskTotal)}`;
      bar(mobSysDiskBar, diskPercent);
      if (mobSysUptime) mobSysUptime.textContent = formatDuration(data.uptime_s);
      if (mobSysLoad) mobSysLoad.textContent = loadText;
      if (mobSysPayload) mobSysPayload.textContent = payloadText;
      if (mobSysInterfaces) mobSysInterfaces.innerHTML = interfacesHtml;
      if (mobSysHostname) mobSysHostname.textContent = String(data.hostname || '-');
      if (mobSysKernel) mobSysKernel.textContent = String(data.kernel || data.platform || '-');
      if (mobSysTailscale) {
        const tailscale = data.tailscale || {};
        const state = tailscale.backend_state || (tailscale.ip ? 'Online' : 'Not installed');
        mobSysTailscale.textContent = tailscale.ip ? `${state} ${tailscale.ip}` : state;
      }
      return;
    }

    if (sysCpuValue) sysCpuValue.textContent = `${cpu.toFixed(1)}%`;
    if (sysTempValue) sysTempValue.textContent = tempText;
    bar(sysCpuBar, cpu);
    if (sysMemValue) sysMemValue.textContent = `${memPercent.toFixed(1)}%`;
    if (sysMemMeta) sysMemMeta.textContent = `${formatBytes(memUsed)} / ${formatBytes(memTotal)}`;
    bar(sysMemBar, memPercent);
    if (sysDiskValue) sysDiskValue.textContent = `${diskPercent.toFixed(1)}%`;
    if (sysDiskMeta) sysDiskMeta.textContent = `${formatBytes(diskUsed)} / ${formatBytes(diskTotal)}`;
    bar(sysDiskBar, diskPercent);
    if (sysUptime) sysUptime.textContent = formatDuration(data.uptime_s);
    if (sysLoad) sysLoad.textContent = loadText;
    if (sysPayload) sysPayload.textContent = payloadText;
    if (sysInterfaces) sysInterfaces.innerHTML = interfacesHtml;
  }

  async function controlPentest(action){
    const buttons = [pentestStart, pentestStop, mobPentestStart, mobPentestStop].filter(Boolean);
    buttons.forEach(btn => { btn.disabled = true; btn.classList.add('opacity-60'); });
    try{
      const res = await apiFetch(getApiUrl(`/api/pentest/${action}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : `pentest_${action}_failed`);
      }
      applyPentestData(data, 'desktop');
      applyPentestData(data, 'mobile');
      if (action === 'start') loadPentestConsole(true);
      await loadSystemStatus();
      if (typeof window.loadMobileSystemStatus === 'function') await loadMobileSystemStatus();
    } catch (e){
      setSystemStatus(action === 'start' ? 'Pentest start failed' : 'Pentest stop failed');
      if (mobileSystemStatus) mobileSystemStatus.textContent = 'Pentest control failed';
    } finally {
      buttons.forEach(btn => { btn.disabled = false; btn.classList.remove('opacity-60'); });
    }
  }


  async function installDesktopDeps(){
    const buttons = [desktopFrameInstallDeps].filter(Boolean);
    buttons.forEach(btn => { btn.disabled = true; btn.classList.add('opacity-60'); });
    try{
      if (desktopFrameStatus) desktopFrameStatus.textContent = 'Starting Kali desktop dependency installation...';
      const res = await apiFetch(getApiUrl('/api/desktop/install-deps'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (!res.ok || (data && data.ok === false && !data.installing)){
        throw new Error(data && (data.error || data.message) ? (data.error || data.message) : 'desktop_dependency_install_failed');
      }
      applyDesktopData(data);
      await loadSystemStatus();
      if (typeof window.loadMobileSystemStatus === 'function') await window.loadMobileSystemStatus();
    } catch (e){
      setSystemStatus('Desktop dependency install failed');
      if (desktopFrameStatus) desktopFrameStatus.textContent = e && e.message ? e.message : 'Desktop dependency install failed';
    } finally {
      buttons.forEach(btn => { btn.disabled = false; btn.classList.remove('opacity-60'); });
      applyDesktopData(lastDesktopData);
    }
  }


  async function controlDesktop(action){
    const buttons = [desktopFrameStart, desktopFrameStop].filter(Boolean);
    buttons.forEach(btn => { btn.disabled = true; btn.classList.add('opacity-60'); });
    try{
      if (desktopFrameStatus) desktopFrameStatus.textContent = action === 'start' ? 'Starting Kali desktop...' : 'Stopping Kali desktop...';
      const res = await apiFetch(getApiUrl(`/api/desktop/${action}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (!res.ok || (data && data.ok === false)){
        throw new Error(data && (data.error || data.message) ? (data.error || data.message) : `desktop_${action}_failed`);
      }
      applyDesktopData(data);
      if (action === 'start') loadDesktopConsole(true);
      await loadSystemStatus();
      if (typeof window.loadMobileSystemStatus === 'function') await loadMobileSystemStatus();
    } catch (e){
      setSystemStatus(action === 'start' ? 'Desktop start failed' : 'Desktop stop failed');
      if (desktopFrameStatus) desktopFrameStatus.textContent = e && e.message ? e.message : 'Desktop control failed';
      if (mobileSystemStatus) mobileSystemStatus.textContent = 'Desktop control failed';
    } finally {
      buttons.forEach(btn => { btn.disabled = false; btn.classList.remove('opacity-60'); });
    }
  }


  async function controlLoki(action){
    const buttons = [lokiStart, lokiStop, lokiFrameStart, lokiFrameStop, lokiFrameEmptyStart].filter(Boolean);
    buttons.forEach(btn => { btn.disabled = true; btn.classList.add('opacity-60'); });
    try{
      const res = await apiFetch(getApiUrl(`/api/loki/${action}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (!res.ok || (data && data.ok === false)){
        throw new Error(data && (data.error || data.message) ? (data.error || data.message) : `loki_${action}_failed`);
      }
      applyLokiData(data);
      if (action === 'start') loadLokiConsole(true);
      await loadSystemStatus();
      if (typeof window.loadMobileSystemStatus === 'function') await loadMobileSystemStatus();
    } catch (e){
      setSystemStatus(action === 'start' ? 'Loki start failed' : 'Loki stop failed');
      if (lokiFrameStatus) lokiFrameStatus.textContent = e && e.message ? e.message : 'Loki control failed';
      if (mobileSystemStatus) mobileSystemStatus.textContent = 'Loki control failed';
    } finally {
      buttons.forEach(btn => { btn.disabled = false; btn.classList.remove('opacity-60'); });
    }
  }

  async function loadSystemStatus(){
    setSystemStatus('Loading...');
    try{
      const url = getApiUrl('/api/system/status');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'system_failed');
      }

      applySystemData(data, 'desktop');
      setSystemStatus('Live');
    } catch (e){
      setSystemStatus('Unavailable');
    }
  }

  async function loadMobileSystemStatus(){
    if (mobileSystemStatus) mobileSystemStatus.textContent = 'Loading...';
    try{
      const url = getApiUrl('/api/system/status');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'system_failed');
      }
      applySystemData(data, 'mobile');
      if (mobileSystemStatus) mobileSystemStatus.textContent = 'Live';
    } catch (e){
      if (mobileSystemStatus) mobileSystemStatus.textContent = 'Unavailable';
    }
  }
  window.loadMobileSystemStatus = loadMobileSystemStatus;

  async function loadDiscordWebhook(){
    setSettingsStatus('Loading...');
    try{
      const url = getApiUrl('/api/settings/discord_webhook');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'settings_failed');
      }
      if (discordWebhookInput) discordWebhookInput.value = String(data.url || '');
      setSettingsStatus(data.configured ? 'Webhook configured' : 'No webhook configured');
    } catch(e){
      setSettingsStatus('Failed to load settings');
    }
  }

  function applyTailscaleDataToUI(data){
    if (!tailscaleSettingsStatus) return;
    const installed = !!data.installed;
    const installing = !!data.installing;
    const backendState = data.backend_state || (installed ? 'Unknown' : 'Not installed');

    if (tailscaleInstallBtn){
      const installingNow = !!installing && !installed;
      tailscaleInstallBtn.classList.toggle('hidden', installed);
      tailscaleInstallBtn.disabled = installingNow;
      tailscaleInstallBtn.classList.toggle('opacity-50', installingNow);
      tailscaleInstallBtn.classList.toggle('cursor-not-allowed', installingNow);
    }
    if (tailscaleReauthBtn){
      const showReauth = installed;
      const disabledReauth = !!installing;
      tailscaleReauthBtn.classList.toggle('hidden', !showReauth);
      tailscaleReauthBtn.disabled = disabledReauth;
      tailscaleReauthBtn.classList.toggle('opacity-50', disabledReauth);
      tailscaleReauthBtn.classList.toggle('cursor-not-allowed', disabledReauth);
    }

    if (installing){
      setTailscaleStatus('Installing Tailscale…');
    } else if (!installed){
      setTailscaleStatus('Not installed');
    } else {
      setTailscaleStatus(`Installed (state: ${backendState || 'Running'})`);
    }
  }

  async function loadTailscaleSettings(skipLoadingState){
    if (!tailscaleSettingsStatus) return;
    if (!skipLoadingState) setTailscaleStatus('Loading...');
    try{
      const url = getApiUrl('/api/settings/tailscale');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'tailscale_failed');
      }
      applyTailscaleDataToUI(data);
    } catch(e){
      setTailscaleStatus('Failed to load Tailscale');
    }
  }

  async function saveDiscordWebhook(url){
    setSettingsStatus('Saving...');
    try{
      const endpoint = getApiUrl('/api/settings/discord_webhook');
      const res = await apiFetch(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: String(url || '').trim() }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok){
        throw new Error(data && data.error ? data.error : 'save_failed');
      }
      setSettingsStatus(data.status === 'cleared' ? 'Webhook cleared' : 'Webhook saved');
    } catch(e){
      setSettingsStatus('Failed to save webhook');
    }
  }

  function openTailscaleModal(){
    if (!tailscaleModal) return;
    if (tailscaleKeyInput) tailscaleKeyInput.value = '';
    if (tailscaleModalError){
      tailscaleModalError.textContent = '';
      tailscaleModalError.classList.add('hidden');
    }
    if (tailscaleModalStatus) tailscaleModalStatus.textContent = '';
    tailscaleModal.classList.remove('hidden');
    if (tailscaleKeyInput) tailscaleKeyInput.focus();
  }

  function closeTailscaleModal(){
    if (!tailscaleModal) return;
    tailscaleModal.classList.add('hidden');
  }

  let tailscaleInstallPollTimer = null;

  function startTailscaleInstallPoll(){
    if (tailscaleInstallPollTimer) clearInterval(tailscaleInstallPollTimer);
    const poll = async () => {
      try{
        const url = getApiUrl('/api/settings/tailscale');
        const res = await apiFetch(url, { cache: 'no-store' });
        const data = await res.json();
        if (!res.ok) return;
        applyTailscaleDataToUI(data);
        const installed = !!data.installed;
        const installing = !!data.installing;
        if (installed && !installing){
          clearInterval(tailscaleInstallPollTimer);
          tailscaleInstallPollTimer = null;
        }
      }catch(e){
        // ignore poll errors; next interval will retry
      }
    };
    tailscaleInstallPollTimer = setInterval(poll, 2000);
    poll();
  }

  async function submitTailscaleInstall(){
    if (!tailscaleKeyInput) return;
    const key = String(tailscaleKeyInput.value || '').trim();
    if (!key){
      if (tailscaleModalError){
        tailscaleModalError.textContent = 'Auth key required';
        tailscaleModalError.classList.remove('hidden');
      }
      return;
    }
    if (!key.startsWith('tskey-')){
      if (tailscaleModalError){
        tailscaleModalError.textContent = "Auth key must start with 'tskey-'.";
        tailscaleModalError.classList.remove('hidden');
      }
      return;
    }
    if (tailscaleModalError){
      tailscaleModalError.textContent = '';
      tailscaleModalError.classList.add('hidden');
    }
    if (tailscaleModalStatus) tailscaleModalStatus.textContent = tailscaleReauthMode ? 'Starting re-auth…' : 'Starting install…';
    const setDisabled = (flag) => {
      if (tailscaleKeyInput) tailscaleKeyInput.disabled = flag;
      if (tailscaleModalSave) tailscaleModalSave.disabled = flag;
      if (tailscaleModalCancel) tailscaleModalCancel.disabled = flag;
    };
    setDisabled(true);
    try{
      const endpoint = getApiUrl('/api/settings/tailscale');
      const res = await apiFetch(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auth_key: key, reauth: tailscaleReauthMode }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok){
        const msg = data && data.error ? data.error : 'install_failed';
        throw new Error(msg);
      }
      if (tailscaleModalStatus) tailscaleModalStatus.textContent = tailscaleReauthMode ? 'Re-authenticating…' : 'Installing Tailscale…';
      closeTailscaleModal();
      setTailscaleStatus(tailscaleReauthMode ? 'Re-authenticating…' : 'Installing Tailscale…');
      startTailscaleInstallPoll();
    } catch(e){
      const msg = e && e.message ? e.message : 'Failed to start install';
      if (tailscaleModalError){
        tailscaleModalError.textContent = msg;
        tailscaleModalError.classList.remove('hidden');
      }
    } finally{
      setDisabled(false);
    }
  }

  function formatTime(ts){
    try{
      const d = new Date(ts * 1000);
      return d.toLocaleString();
    }catch{
      return '';
    }
  }

  function buildLootPath(parent, name){
    return parent ? `${parent}/${name}` : name;
  }

  function setLootStatus(text){
    if (lootStatus) lootStatus.textContent = text;
  }

  function setLootPath(text){
    if (lootPathEl) lootPathEl.textContent = text ? `/${text}` : '/';
  }

  function updateLootUp(){
    if (!lootUpBtn) return;
    const disabled = !lootState.path;
    lootUpBtn.disabled = disabled;
    lootUpBtn.classList.toggle('opacity-40', disabled);
    lootUpBtn.classList.toggle('cursor-not-allowed', disabled);
  }

  function openPreview({ title, content, meta, downloadUrl }){
    if (!lootPreview) return;
    if (lootPreviewTitle) lootPreviewTitle.textContent = title || 'Preview';
    if (lootPreviewBody) lootPreviewBody.textContent = content || '';
    if (lootPreviewMeta) lootPreviewMeta.textContent = meta || '';
    if (lootPreviewDownload) lootPreviewDownload.href = downloadUrl || '#';
    lootPreview.classList.remove('hidden');
  }

  function closePreview(){
    if (!lootPreview) return;
    lootPreview.classList.add('hidden');
  }

  function setNmapVizStatus(text){
    if (!nmapVizStatus) return;
    nmapVizStatus.textContent = text || 'Ready';
    applyStatusTone(nmapVizStatus, text || 'Ready');
  }

  function setNmapVizError(message){
    if (!nmapVizError) return;
    const text = String(message || '').trim();
    nmapVizError.textContent = text;
    nmapVizError.classList.toggle('hidden', !text);
  }

  function revokeNmapJsonUrl(){
    if (!nmapVizState.jsonUrl) return;
    try { URL.revokeObjectURL(nmapVizState.jsonUrl); } catch {}
    nmapVizState.jsonUrl = '';
  }

  function closeNmapViz(){
    if (!nmapVizModal) return;
    nmapVizModal.classList.add('hidden');
    setNmapVizError('');
    setNmapVizStatus('Ready');
  }

  function hasStructuredData(value){
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === 'object') return Object.keys(value).length > 0;
    return value !== null && value !== undefined && value !== '';
  }

  function formatSeverityLabel(value){
    const text = String(value || 'unknown').toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function getSeverityClasses(value){
    const severity = String(value || 'unknown').toLowerCase();
    if (severity === 'critical') return 'border-rose-400/30 bg-rose-500/15 text-rose-200';
    if (severity === 'high') return 'border-orange-400/30 bg-orange-500/15 text-orange-200';
    if (severity === 'medium') return 'border-amber-400/30 bg-amber-500/15 text-amber-200';
    if (severity === 'low') return 'border-sky-400/30 bg-sky-500/15 text-sky-200';
    return 'border-slate-500/30 bg-slate-800/60 text-slate-300';
  }

  function formatScriptContext(script){
    if (!script || !script.context) return 'Host script';
    if (script.context.scope === 'port'){
      const port = script.context.port ?? '?';
      const proto = script.context.protocol || '?';
      return `Port ${port}/${proto}`;
    }
    return 'Host script';
  }

  function toPrettyJson(value){
    try{
      return JSON.stringify(value, null, 2);
    }catch{
      return String(value || '');
    }
  }

  function isNmapLootXml(parentPath, name){
    const current = String(parentPath || '');
    const fileName = String(name || '');
    return /\.xml$/i.test(fileName) && (current === 'Nmap' || current.startsWith('Nmap/'));
  }

  function renderNmapSummaryCards(data, hosts){
    const hostCount = hosts.length;
    const upCount = hosts.filter(host => String(host && host.status || '').toLowerCase() === 'up').length;
    const portCount = hosts.reduce((sum, host) => sum + ((host && Array.isArray(host.ports)) ? host.ports.length : 0), 0);
    const vulnCount = hosts.reduce((sum, host) => sum + ((host && Array.isArray(host.vulnerabilities)) ? host.vulnerabilities.length : 0), 0);
    const elapsed = data && data.stats && data.stats.elapsed ? `${Number(data.stats.elapsed).toFixed(2)}s` : 'Unknown';
    const cards = [
      { label: 'Hosts', value: String(hostCount), tone: 'text-red-400' },
      { label: 'Up', value: String(upCount), tone: 'text-cyan-200' },
      { label: 'Ports', value: String(portCount), tone: 'text-slate-100' },
      { label: 'Vulnerabilities', value: String(vulnCount), tone: vulnCount ? 'text-rose-200' : 'text-slate-100' },
      { label: 'Elapsed', value: elapsed, tone: 'text-slate-100' },
    ];
    return `
      <div class="grid grid-cols-2 xl:grid-cols-5 gap-3">
        ${cards.map(card => `
          <div class="rounded-xl border border-slate-800/70 bg-slate-900/50 px-4 py-3">
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500">${escapeHtml(card.label)}</div>
            <div class="mt-2 text-lg font-semibold ${card.tone}">${escapeHtml(card.value)}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderVulnerabilityList(vulnerabilities){
    if (!Array.isArray(vulnerabilities) || !vulnerabilities.length){
      return '<div class="text-xs text-slate-500">No vulnerabilities identified.</div>';
    }
    return vulnerabilities.map(vuln => {
      const refs = Array.isArray(vuln.references) ? vuln.references : [];
      const portLabel = vuln.port ? ` · Port ${escapeHtml(String(vuln.port))}/${escapeHtml(String(vuln.protocol || '?'))}` : '';
      return `
        <div class="rounded-xl border ${getSeverityClasses(vuln.severity)} px-3 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-xs font-semibold">${escapeHtml(vuln.id || 'Finding')}</span>
            <span class="px-2 py-0.5 rounded-full border text-[10px] ${getSeverityClasses(vuln.severity)}">${escapeHtml(formatSeverityLabel(vuln.severity))}</span>
            <span class="text-[11px] text-slate-400">${escapeHtml(vuln.source_script_id || 'script')}${portLabel}</span>
          </div>
          <div class="mt-2 text-xs text-slate-100 whitespace-pre-wrap">${escapeHtml(vuln.description || 'No description available.')}</div>
          ${refs.length ? `<div class="mt-2 text-[11px] text-slate-400">Refs: ${escapeHtml(refs.join(', '))}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  function renderPortList(ports){
    if (!Array.isArray(ports) || !ports.length){
      return '<div class="text-xs text-slate-500">No port data in this scan.</div>';
    }
    return `
      <div class="space-y-2">
        ${ports.map(port => {
          const serviceBits = [port.service, port.product, port.version].filter(Boolean);
          return `
            <div class="rounded-xl border border-slate-800/70 bg-slate-900/40 px-3 py-3">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="text-sm text-slate-100 font-medium">${escapeHtml(String(port.port ?? '?'))}/${escapeHtml(String(port.protocol || '?'))}</div>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="px-2 py-0.5 rounded-full border text-[10px] ${String(port.state || '').toLowerCase() === 'open' ? 'border-red-400/30 bg-red-800/10 text-emerald-200' : 'border-slate-600/40 bg-slate-800/70 text-slate-300'}">${escapeHtml(String(port.state || 'unknown'))}</span>
                  ${port.scripts && port.scripts.length ? `<span class="text-[11px] text-slate-400">${escapeHtml(String(port.scripts.length))} scripts</span>` : ''}
                </div>
              </div>
              <div class="mt-2 text-xs text-slate-300">${escapeHtml(serviceBits.join(' · ') || 'Service metadata unavailable')}</div>
              ${port.extrainfo ? `<div class="mt-1 text-[11px] text-slate-500">${escapeHtml(String(port.extrainfo))}</div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function renderOsSection(osInfo){
    if (!osInfo || (!osInfo.name && !(Array.isArray(osInfo.matches) && osInfo.matches.length))){
      return '<div class="text-xs text-slate-500">No OS detection data in this scan.</div>';
    }
    const matches = Array.isArray(osInfo.matches) ? osInfo.matches.slice(0, 3) : [];
    return `
      <div class="space-y-2">
        <div class="rounded-xl border border-slate-800/70 bg-slate-900/40 px-3 py-3">
          <div class="text-sm font-medium text-slate-100">${escapeHtml(String(osInfo.name || 'Best match unavailable'))}</div>
          <div class="mt-1 text-[11px] text-slate-400">Accuracy: ${escapeHtml(String(osInfo.accuracy ?? 'unknown'))}</div>
        </div>
        ${matches.map(match => `
          <div class="rounded-xl border border-slate-800/70 bg-slate-950/40 px-3 py-2">
            <div class="text-xs text-slate-200">${escapeHtml(String(match.name || 'Unknown match'))}</div>
            <div class="text-[11px] text-slate-500">Accuracy ${escapeHtml(String(match.accuracy ?? 'unknown'))}</div>
          </div>
        `).join('')}
      </div>
    `;
  }

  function renderScriptOutputs(scripts){
    if (!Array.isArray(scripts) || !scripts.length){
      return '<div class="text-xs text-slate-500">No script output in this scan.</div>';
    }
    return scripts.map(script => {
      const structured = hasStructuredData(script.structured)
        ? `<div class="mt-3"><div class="text-[11px] uppercase tracking-[0.16em] text-slate-500 mb-1">Structured</div><pre class="text-[11px] text-cyan-100 whitespace-pre-wrap rounded-lg border border-slate-800/70 bg-slate-950/70 p-3 overflow-auto">${escapeHtml(toPrettyJson(script.structured))}</pre></div>`
        : '';
      const vulnerabilities = Array.isArray(script.vulnerabilities) && script.vulnerabilities.length
        ? `<div class="mt-3 space-y-2">${renderVulnerabilityList(script.vulnerabilities)}</div>`
        : '';
      return `
        <details class="rounded-xl border border-slate-800/70 bg-slate-900/45 px-3 py-3 group">
          <summary class="flex flex-wrap items-center gap-2 cursor-pointer list-none">
            <span class="text-xs font-semibold text-slate-100">${escapeHtml(String(script.id || 'script'))}</span>
            <span class="text-[11px] text-slate-400">${escapeHtml(formatScriptContext(script))}</span>
            ${script.is_vulnerability ? `<span class="px-2 py-0.5 rounded-full border text-[10px] border-rose-400/30 bg-rose-500/15 text-rose-200">Vulnerability</span>` : ''}
          </summary>
          <div class="mt-3 text-[11px] uppercase tracking-[0.16em] text-slate-500 mb-1">Raw Output</div>
          <pre class="text-[11px] text-slate-100 whitespace-pre-wrap rounded-lg border border-slate-800/70 bg-slate-950/70 p-3 overflow-auto">${escapeHtml(String(script.output || 'No raw output available.'))}</pre>
          ${structured}
          ${vulnerabilities}
        </details>
      `;
    }).join('');
  }

  function renderHostCard(host){
    const hostnames = Array.isArray(host.hostnames) && host.hostnames.length ? host.hostnames.join(', ') : 'No hostnames';
    const ports = Array.isArray(host.ports) ? host.ports : [];
    const vulnerabilities = Array.isArray(host.vulnerabilities) ? host.vulnerabilities : [];
    const scripts = Array.isArray(host.raw_scripts) ? host.raw_scripts : [];
    const highest = host && host.severity_summary ? host.severity_summary.highest : null;
    return `
      <section class="rounded-2xl border border-slate-800/70 bg-slate-950/45 overflow-hidden">
        <div class="px-4 py-4 border-b border-slate-800/70 bg-slate-900/45">
          <div class="flex flex-wrap items-center gap-2">
            <div class="text-base font-semibold text-slate-100">${escapeHtml(String(host.ip || 'Unknown host'))}</div>
            <span class="px-2 py-0.5 rounded-full border text-[10px] ${String(host.status || '').toLowerCase() === 'up' ? 'border-red-400/30 bg-red-800/10 text-emerald-200' : 'border-slate-600/40 bg-slate-800/70 text-slate-300'}">${escapeHtml(String(host.status || 'unknown'))}</span>
            ${highest ? `<span class="px-2 py-0.5 rounded-full border text-[10px] ${getSeverityClasses(highest)}">${escapeHtml(formatSeverityLabel(highest))}</span>` : ''}
          </div>
          <div class="mt-2 text-xs text-slate-400">${escapeHtml(hostnames)}</div>
          <div class="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
            <span>MAC: ${escapeHtml(String(host.mac || 'n/a'))}</span>
            <span>Vendor: ${escapeHtml(String(host.vendor || 'n/a'))}</span>
            <span>Ports: ${escapeHtml(String(ports.length))}</span>
            <span>Findings: ${escapeHtml(String(vulnerabilities.length))}</span>
          </div>
        </div>
        <div class="grid xl:grid-cols-2 gap-4 p-4">
          <div>
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500 mb-2">Ports & Services</div>
            ${renderPortList(ports)}
          </div>
          <div>
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500 mb-2">OS Detection</div>
            ${renderOsSection(host.os)}
          </div>
        </div>
        <div class="grid xl:grid-cols-2 gap-4 px-4 pb-4">
          <div>
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500 mb-2">Vulnerabilities</div>
            ${renderVulnerabilityList(vulnerabilities)}
          </div>
          <div>
            <div class="text-[11px] uppercase tracking-[0.18em] text-slate-500 mb-2">Script Outputs</div>
            <div class="space-y-2">${renderScriptOutputs(scripts)}</div>
          </div>
        </div>
      </section>
    `;
  }

  function renderNmapVisualization(){
    if (!nmapVizBody) return;
    const data = nmapVizState.data;
    if (!data){
      nmapVizBody.innerHTML = '<div class="text-sm text-slate-400">No Nmap data loaded.</div>';
      return;
    }

    const allHosts = Array.isArray(data.hosts) ? data.hosts : [];
    const vulnerableOnly = !!(nmapVizFilterVuln && nmapVizFilterVuln.checked);
    const hosts = vulnerableOnly
      ? allHosts.filter(host => Array.isArray(host.vulnerabilities) && host.vulnerabilities.length)
      : allHosts;
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const args = data && data.scan ? data.scan.args : '';
    const rawXmlSection = data.raw_xml
      ? `<details class="rounded-xl border border-slate-800/70 bg-slate-900/45 px-4 py-3"><summary class="cursor-pointer text-xs font-semibold text-slate-200">Raw XML</summary><pre class="mt-3 text-[11px] text-slate-100 whitespace-pre-wrap rounded-lg border border-slate-800/70 bg-slate-950/70 p-3 overflow-auto">${escapeHtml(String(data.raw_xml || ''))}</pre></details>`
      : '';
    const warningsSection = warnings.length
      ? `<div class="rounded-xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-100">Warnings: ${escapeHtml(warnings.join(' | '))}</div>`
      : '';

    nmapVizBody.innerHTML = `
      ${renderNmapSummaryCards(data, hosts)}
      ${args ? `<div class="rounded-xl border border-slate-800/70 bg-slate-900/45 px-4 py-3 text-xs text-slate-300"><span class="text-slate-500 uppercase tracking-[0.16em] mr-2">Args</span>${escapeHtml(String(args))}</div>` : ''}
      ${warningsSection}
      <div class="space-y-4">
        ${hosts.length ? hosts.map(renderHostCard).join('') : '<div class="rounded-xl border border-slate-800/70 bg-slate-900/45 px-4 py-6 text-sm text-slate-400">No hosts match the current filter.</div>'}
      </div>
      ${rawXmlSection}
    `;
  }

  async function loadNmapVisualization(path, name){
    if (!nmapVizModal) return;
    const xmlUrl = getApiUrl('/api/loot/download', { path });
    if (nmapVizTitle) nmapVizTitle.textContent = name || 'Nmap Visualization';
    if (nmapVizMeta) nmapVizMeta.textContent = path ? `/${path}` : '';
    if (nmapVizDownloadXml) nmapVizDownloadXml.href = xmlUrl;
    if (nmapVizFilterVuln) nmapVizFilterVuln.checked = false;
    setNmapVizError('');
    setNmapVizStatus('Loading...');
    nmapVizState.data = null;
    revokeNmapJsonUrl();
    if (nmapVizBody) nmapVizBody.innerHTML = '<div class="text-sm text-slate-400">Parsing XML and normalizing results...</div>';
    nmapVizModal.classList.remove('hidden');

    try{
      const url = getApiUrl('/api/loot/nmap', { path, include_raw: '1' });
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'Failed to parse Nmap XML');
      }
      nmapVizState.data = data;
      if (nmapVizMeta){
        const metaBits = [
          path ? `/${path}` : '',
          data && data.scan && data.scan.version ? `Nmap ${data.scan.version}` : '',
          data && data.stats && data.stats.time_str ? data.stats.time_str : '',
        ].filter(Boolean);
        nmapVizMeta.textContent = metaBits.join(' · ');
      }
      if (nmapVizDownloadJson){
        const jsonBlob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        nmapVizState.jsonUrl = URL.createObjectURL(jsonBlob);
        nmapVizDownloadJson.href = nmapVizState.jsonUrl;
        nmapVizDownloadJson.download = String(name || 'nmap').replace(/\.xml$/i, '.json');
      }
      renderNmapVisualization();
      setNmapVizStatus('Ready');
    }catch(e){
      setNmapVizStatus('Parse failed');
      setNmapVizError(e && e.message ? e.message : 'Failed to parse Nmap XML');
      if (nmapVizBody) nmapVizBody.innerHTML = '<div class="text-sm text-slate-400">The XML file could not be visualized.</div>';
    }
  }

  function renderLoot(items){
    if (!lootList) return;
    if (!items.length){
      lootList.innerHTML = '<div class="px-3 py-4 text-sm text-slate-400">No files found.</div>';
      return;
    }
    const rows = items.map(item => {
      const itemType = item && item.type === 'dir' ? 'dir' : 'file';
      const icon = itemType === 'dir' ? '📁' : '📄';
      const meta = itemType === 'dir' ? 'Folder' : `${formatBytes(item.size)} · ${formatTime(item.mtime)}`;
      const safeName = escapeHtml(item.name || '');
      const encodedName = encodeData(item.name || '');
      const vizAction = isNmapLootXml(lootState.path, item.name)
        ? `<span role="button" tabindex="0" title="Visualize Nmap XML" aria-label="Visualize Nmap XML" data-visualize-nmap="${encodedName}" class="ml-2 inline-flex h-6 w-6 items-center justify-center rounded-md border border-red-400/20 bg-red-800/10 text-emerald-200 hover:bg-red-800/20 transition align-middle"><i class="fa-solid fa-network-wired pointer-events-none text-[11px]"></i></span>`
        : '';
      return `
        <button class="w-full text-left px-3 py-2 flex items-center gap-3 hover:bg-slate-800/60 transition loot-item" data-type="${itemType}" data-name="${encodedName}">
          <span class="text-lg">${icon}</span>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-slate-100 truncate"><span>${safeName}</span>${vizAction}</div>
            <div class="text-[11px] text-slate-400">${escapeHtml(meta)}</div>
          </div>
          <div class="text-xs text-slate-400">${itemType === 'dir' ? 'Open' : 'Download'}</div>
        </button>
      `;
    }).join('');
    lootList.innerHTML = rows;
  }

  async function loadLoot(path = ''){
    setLootStatus('Loading...');
    try{
      const url = getApiUrl('/api/loot/list', { path });
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'Failed to load');
      }
      lootState = { path: data.path || '', parent: data.parent || '' };
      setLootPath(lootState.path);
      updateLootUp();
      renderLoot(data.items || []);
      setLootStatus('Ready');
    }catch(e){
      setLootStatus('Failed to load loot');
      renderLoot([]);
    }
  }

  async function previewLootFile(path, name){
    setLootStatus('Loading preview...');
    try{
      const url = getApiUrl('/api/loot/view', { path });
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'preview_failed');
      }
      const meta = `${formatBytes(data.size || 0)} · ${formatTime(data.mtime || 0)}${data.truncated ? ' · truncated' : ''}`;
      const downloadUrl = getApiUrl('/api/loot/download', { path });
      openPreview({
        title: name,
        content: data.content || '',
        meta,
        downloadUrl
      });
      setLootStatus('Ready');
    }catch(e){
      setLootStatus('Preview unavailable');
      const downloadUrl = getApiUrl('/api/loot/download', { path });
      window.open(downloadUrl, '_blank');
    }
  }

  async function loadPayloads(){
    setPayloadStatus('Loading...');
    try{
      const url = getApiUrl('/api/payloads/list');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data && data.error ? data.error : 'payloads_failed');
      }
      payloadState.categories = data.categories || [];
      payloadState.categories.forEach((cat, idx) => {
        if (payloadState.open[cat.id] === undefined) {
          payloadState.open[cat.id] = idx === 0;
        }
      });
      renderPayloadSidebar();
      setPayloadStatus('Ready');
    }catch(e){
      setPayloadStatus('Failed to load');
      const noPayloadsHtml = '<div class="text-xs text-slate-500 px-2">No payloads available.</div>';
      if (payloadSidebar) payloadSidebar.innerHTML = noPayloadsHtml;
      if (payloadsMobileList) payloadsMobileList.innerHTML = noPayloadsHtml;
    }
  }

  function renderPayloadSidebar(){
    if (!payloadSidebar && !payloadsMobileList) return;
    const cats = payloadState.categories || [];
    if (!cats.length){
      const emptyHtml = '<div class="text-xs text-slate-500 px-2">No categories.</div>';
      if (payloadSidebar) payloadSidebar.innerHTML = emptyHtml;
      if (payloadsMobileList) payloadsMobileList.innerHTML = emptyHtml;
      return;
    }
    const rendered = cats.map(cat => {
      const catId = String(cat?.id || '');
      const catIdEncoded = encodeData(catId);
      const catLabel = escapeHtml(String(cat?.label || catId || 'Category'));
      const isOpen = !!payloadState.open[catId];
      const items = (cat.items || []).map(item => {
        const itemName = escapeHtml(String(item?.name || 'payload'));
        const itemPath = String(item?.path || '');
        const itemPathEncoded = encodeData(itemPath);
        const isActive = payloadState.activePath === itemPath;
        const disabled = !!payloadState.activePath;
        const startCls = disabled
          ? 'px-2 py-0.5 text-[10px] rounded-md bg-slate-800/80 border border-slate-700/40 text-slate-500 cursor-not-allowed'
          : 'px-2 py-0.5 text-[10px] rounded-md bg-red-900/80 border border-red-300/30 text-white hover:bg-red-800/80 transition';
        const stopBtn = isActive
          ? '<button type="button" data-stop="1" class="px-2 py-0.5 text-[10px] rounded-md bg-rose-600/80 border border-rose-300/30 text-white hover:bg-rose-500/80 transition">Stop</button>'
          : '<span class="px-2 py-0.5 text-[10px] rounded-md bg-slate-900/60 border border-slate-800/40 text-slate-600">Idle</span>';
        return `
        <div class="flex items-center justify-between gap-2 px-2 py-1 rounded-lg bg-slate-900/40 border border-slate-800/70">
          <div class="text-[11px] text-slate-200 truncate">${itemName}</div>
          <div class="flex items-center gap-1">
            <button type="button" data-start="${itemPathEncoded}" ${disabled ? 'disabled' : ''} class="${startCls}">Start</button>
            ${stopBtn}
          </div>
        </div>
      `;
      }).join('');
      return `
        <div class="rounded-xl border border-slate-800/70 bg-slate-950/40">
          <button type="button" data-cat="${catIdEncoded}" class="w-full px-3 py-2 text-left text-xs font-semibold text-slate-200 flex items-center justify-between">
            <span>${catLabel}</span>
            <span class="text-slate-400">${isOpen ? '▾' : '▸'}</span>
          </button>
          <div class="${isOpen ? '' : 'hidden'} px-2 pb-2 space-y-1">
            ${items || '<div class="text-[11px] text-slate-500 px-1">Empty</div>'}
          </div>
        </div>
      `;
    }).join('');
    if (payloadSidebar) payloadSidebar.innerHTML = rendered;
    if (payloadsMobileList) payloadsMobileList.innerHTML = rendered;
  }

  async function startPayload(path){
    setPayloadStatus('Starting...');
    try{
      const url = getApiUrl('/api/payloads/start');
      const res = await apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      const data = await res.json();
      if (!res.ok || !data.ok){
        throw new Error(data && data.error ? data.error : 'start_failed');
      }
      payloadState.activePath = path;
      renderPayloadSidebar();
      setPayloadStatus('Launched');
    }catch(e){
      setPayloadStatus('Start failed');
    }
  }

  async function pollPayloadStatus(){
    try{
      const url = getApiUrl('/api/payloads/status');
      const res = await apiFetch(url, { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok){
        return;
      }
      const running = !!data.running;
      const path = running ? (data.path || null) : null;
      if (payloadState.activePath !== path){
        payloadState.activePath = path;
        renderPayloadSidebar();
      }
      setPayloadStatus(running ? 'Running' : 'Ready');
    }catch(e){
      setPayloadStatus('Ready');
    }
  }

  function rotateButton(btn, rotation) {
    if (rotation === 0 || !btn) return btn;
    const rotations = {
      90: { UP: 'LEFT', DOWN: 'RIGHT', LEFT: 'DOWN', RIGHT: 'UP' },
      180: { UP: 'DOWN', DOWN: 'UP', LEFT: 'RIGHT', RIGHT: 'LEFT' },
      270: { UP: 'RIGHT', DOWN: 'LEFT', LEFT: 'UP', RIGHT: 'DOWN' }
    };
    return rotations[rotation]?.[btn] || btn;
  }

  function sendInput(button, state){
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try{
      const rotatedButton = rotateButton(button, currentRotation);
      ws.send(JSON.stringify({ type: 'input', button: rotatedButton, state }));
    }catch{}
  }

  function tapInput(button){
    sendInput(button, 'press');
    setTimeout(() => sendInput(button, 'release'), 120);
  }

  function exitStealth(){
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try { ws.send(JSON.stringify({ type: 'stealth_exit' })); } catch{}
  }
  window.exitStealth = exitStealth;

  // Mouse/touch buttons
  function bindButtons(){
    const buttons = document.querySelectorAll('[data-btn]');
    buttons.forEach(btn => {
      const name = btn.getAttribute('data-btn');
      const press = () => { btn.classList.add('active'); sendInput(name, 'press'); };
      const release = () => { btn.classList.remove('active'); sendInput(name, 'release'); };
      btn.addEventListener('mousedown', press);
      btn.addEventListener('mouseup', release);
      btn.addEventListener('mouseleave', release);
      btn.addEventListener('touchstart', (e)=>{ e.preventDefault(); press(); }, {passive:false});
      btn.addEventListener('touchend', (e)=>{ e.preventDefault(); release(); }, {passive:false});
      btn.addEventListener('touchcancel', (e)=>{ e.preventDefault(); release(); }, {passive:false});
    });
  }

  // Keyboard mapping
  const KEYMAP = new Map([
    ['ArrowUp','UP'],
    ['ArrowDown','DOWN'],
    ['ArrowLeft','LEFT'],
    ['ArrowRight','RIGHT'],
    ['Enter','OK'],
    ['NumpadEnter','OK'],
    ['Digit1','KEY1'],
    ['Digit2','KEY2'],
    ['Digit3','KEY3'],
    ['Escape','KEY3'],
  ]);

  function bindKeyboard(){
    const isTypingFocus = () => {
      const el = document.activeElement;
      if (!el) return false;
      const tag = String(el.tagName || '').toUpperCase();
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || !!el.isContentEditable;
    };

    window.addEventListener('keydown', (e)=>{
      if (terminalHasFocus || isTypingFocus()) return;
      const btn = KEYMAP.get(e.code) || KEYMAP.get(e.key);
      if (!btn) return;
      if (pressed.has(btn)) return; // avoid repeats
      pressed.add(btn);
      sendInput(btn, 'press');
      e.preventDefault();
    });
    window.addEventListener('keyup', (e)=>{
      if (terminalHasFocus || isTypingFocus()) return;
      const btn = KEYMAP.get(e.code) || KEYMAP.get(e.key);
      if (!btn) return;
      pressed.delete(btn);
      sendInput(btn, 'release');
      e.preventDefault();
    });
    window.addEventListener('blur', ()=>{
      // Release everything on blur to avoid stuck keys
      for (const btn of pressed){ sendInput(btn, 'release'); }
      pressed.clear();
    });
  }

  bindButtons();
  bindKeyboard();
  if (shellConnectBtn) shellConnectBtn.addEventListener('click', sendShellOpen);
  if (shellDisconnectBtn) shellDisconnectBtn.addEventListener('click', sendShellClose);
  document.querySelectorAll('.shell-key-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.getAttribute('data-shell-key');
      if (key) sendShellInput(key);
      if (term) try { term.focus(); } catch {}
    });
  });
  if (logoutBtn) logoutBtn.addEventListener('click', logoutUser);
  window.addEventListener('resize', () => {
    if (shellOpen) sendShellResize();
  });
  if (navDevice) navDevice.addEventListener('click', () => setActiveTab('device'));
  if (navSystem) navSystem.addEventListener('click', () => {
    setSystemOpen(!systemOpen);
  });
  if (navPentest) navPentest.addEventListener('click', () => {
    setActiveTab('pentest');
    loadSystemStatus().then(() => ensurePentestConsole()).catch(() => {});
  });
  if (navLoki) navLoki.addEventListener('click', () => {
    setActiveTab('loki');
    loadSystemStatus().then(() => ensureLokiConsole()).catch(() => {});
  });
  if (navLoot) navLoot.addEventListener('click', () => {
    setActiveTab('loot');
    if (lootList && !lootList.dataset.loaded){
      loadLoot('');
      lootList.dataset.loaded = '1';
    }
  });
  if (navSettings) navSettings.addEventListener('click', () => {
    setActiveTab('settings');
    loadDiscordWebhook();
    loadTailscaleSettings();
  });
  if (navSdr) {
    navSdr.href = resolveSdrUrl();
    navSdr.addEventListener('click', (event) => {
      const target = resolveSdrUrl();
      navSdr.href = target;
      if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        window.open(target, '_blank', 'noopener,noreferrer');
      }
    });
  }
  if (sdrServiceOpen) {
    sdrServiceOpen.href = resolveSdrUrl();
    sdrServiceOpen.addEventListener('click', () => {
      sdrServiceOpen.href = resolveSdrUrl();
    });
  }
  if (sdrServiceToggle) {
    sdrServiceToggle.addEventListener('change', () => {
      controlSdrService(sdrServiceToggle.checked ? 'enable-start' : 'disable');
    });
  }
  if (sdrServiceStart) {
    sdrServiceStart.addEventListener('click', () => controlSdrService('enable-start'));
  }
  if (sdrServiceStop) {
    sdrServiceStop.addEventListener('click', () => controlSdrService('disable'));
  }
  if (sdrServiceRefresh) {
    sdrServiceRefresh.addEventListener('click', loadSdrServiceStatus);
  }
  if (navPayloadStudio) navPayloadStudio.href = './ide.html' + getForwardSearch();
  themeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-theme');
      if (id) setThemeById(id);
    });
  });
  if (menuToggle) menuToggle.addEventListener('click', () => setSidebarOpen(true));
  if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', () => setSidebarOpen(false));
  if (lootUpBtn) lootUpBtn.addEventListener('click', () => {
    if (lootState.parent !== undefined){
      loadLoot(lootState.parent || '');
    }
  });
  if (lootList) lootList.addEventListener('click', (e) => {
    const vizBtn = e.target.closest('[data-visualize-nmap]');
    if (vizBtn){
      e.preventDefault();
      const encodedViz = vizBtn.getAttribute('data-visualize-nmap') || '';
      const vizName = decodeURIComponent(encodedViz);
      const vizPath = buildLootPath(lootState.path, vizName);
      loadNmapVisualization(vizPath, vizName);
      return;
    }
    const btn = e.target.closest('.loot-item');
    if (!btn) return;
    const encoded = btn.getAttribute('data-name') || '';
    const name = decodeURIComponent(encoded);
    const type = btn.getAttribute('data-type');
    const nextPath = buildLootPath(lootState.path, name);
    if (type === 'dir'){
      loadLoot(nextPath);
    } else {
      previewLootFile(nextPath, name);
    }
  });
  if (payloadSidebar) payloadSidebar.addEventListener('click', (e) => {
    const catBtn = e.target.closest('[data-cat]');
    if (catBtn){
      const encodedId = catBtn.getAttribute('data-cat') || '';
      const id = decodeURIComponent(encodedId);
      if (id){
        payloadState.open[id] = !payloadState.open[id];
        renderPayloadSidebar();
      }
      return;
    }
    const startBtn = e.target.closest('[data-start]');
    if (startBtn){
      const encodedPath = startBtn.getAttribute('data-start') || '';
      const path = decodeURIComponent(encodedPath);
      if (path) startPayload(path);
      return;
    }
    const stopBtn = e.target.closest('[data-stop]');
    if (stopBtn){
      setPayloadStatus('Stopping...');
      tapInput('KEY3');
    }
  });
  if (payloadsMobileList) payloadsMobileList.addEventListener('click', (e) => {
    const catBtn = e.target.closest('[data-cat]');
    if (catBtn){
      const id = decodeURIComponent(catBtn.getAttribute('data-cat') || '');
      if (id){ payloadState.open[id] = !payloadState.open[id]; renderPayloadSidebar(); }
      return;
    }
    const startBtn = e.target.closest('[data-start]');
    if (startBtn){
      const path = decodeURIComponent(startBtn.getAttribute('data-start') || '');
      if (path) startPayload(path);
      return;
    }
    const stopBtn = e.target.closest('[data-stop]');
    if (stopBtn){ setPayloadStatus('Stopping...'); tapInput('KEY3'); }
  });
  const payloadsMobRefresh = document.getElementById('payloadsMobRefresh');
  if (payloadsMobRefresh) payloadsMobRefresh.addEventListener('click', () => loadPayloads());
  // ── Mobile bottom nav ──────────────────────────────────────────────────────
  document.querySelectorAll('[data-mobnav]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.mobnav;
      if (tab === 'system'){
        setActiveTab('system');
        setTimeout(() => loadMobileSystemStatus(), 50);
      } else if (tab === 'loot'){
        setActiveTab('loot');
        if (lootList && !lootList.dataset.loaded){ loadLoot(''); lootList.dataset.loaded = '1'; }
      } else if (tab === 'settings'){
        setActiveTab('settings');
        loadDiscordWebhook();
        loadTailscaleSettings();
      } else {
        setActiveTab(tab);
      }
    });
  });
  if (payloadsRefresh) payloadsRefresh.addEventListener('click', () => loadPayloads());
  if (gameCenterRefresh) gameCenterRefresh.addEventListener('click', () => loadGameCenter());
  if (gameCenterInstall) gameCenterInstall.addEventListener('click', () => installGameCenterEmulators());
  if (gameCenterPlay) gameCenterPlay.addEventListener('click', () => playSelectedGame());
  if (pentestStart) pentestStart.addEventListener('click', () => controlPentest('start'));
  if (pentestOpen) pentestOpen.addEventListener('click', () => setActiveTab('pentest'));
  if (lokiOpen) lokiOpen.addEventListener('click', () => setActiveTab('loki'));
  if (pentestStop) pentestStop.addEventListener('click', () => controlPentest('stop'));
  if (pentestFrameStart) pentestFrameStart.addEventListener('click', () => controlPentest('start'));
  if (pentestFrameReload) pentestFrameReload.addEventListener('click', () => loadPentestConsole(true));
  if (pentestFrameStop) pentestFrameStop.addEventListener('click', () => controlPentest('stop'));
  if (desktopFrameInstallDeps) desktopFrameInstallDeps.addEventListener('click', () => installDesktopDeps());
  if (desktopFrameStart) desktopFrameStart.addEventListener('click', () => controlDesktop('start'));
  if (desktopFrameReload) desktopFrameReload.addEventListener('click', () => loadDesktopConsole(true));
  if (desktopFrameStop) desktopFrameStop.addEventListener('click', () => controlDesktop('stop'));
  if (mobPentestStart) mobPentestStart.addEventListener('click', () => controlPentest('start'));
  if (mobPentestStop) mobPentestStop.addEventListener('click', () => controlPentest('stop'));
  if (lokiStart) lokiStart.addEventListener('click', () => controlLoki('start'));
  if (lokiStop) lokiStop.addEventListener('click', () => controlLoki('stop'));
  if (lokiFrameStart) lokiFrameStart.addEventListener('click', () => controlLoki('start'));
  if (lokiFrameEmptyStart) lokiFrameEmptyStart.addEventListener('click', () => controlLoki('start'));
  if (lokiFrameReload) lokiFrameReload.addEventListener('click', () => loadLokiConsole(true));
  if (lokiFrameStop) lokiFrameStop.addEventListener('click', () => controlLoki('stop'));
  if (mobileSystemRefresh) mobileSystemRefresh.addEventListener('click', () => loadMobileSystemStatus());
  if (discordWebhookSave) discordWebhookSave.addEventListener('click', () => {
    saveDiscordWebhook(discordWebhookInput ? discordWebhookInput.value : '');
  });
  if (discordWebhookClear) discordWebhookClear.addEventListener('click', () => {
    if (discordWebhookInput) discordWebhookInput.value = '';
    saveDiscordWebhook('');
  });
  if (tailscaleInstallBtn) tailscaleInstallBtn.addEventListener('click', () => {
    tailscaleReauthMode = false;
    openTailscaleModal();
  });
  if (tailscaleReauthBtn) tailscaleReauthBtn.addEventListener('click', () => {
    tailscaleReauthMode = true;
    openTailscaleModal();
  });
  if (tailscaleModalSave) tailscaleModalSave.addEventListener('click', submitTailscaleInstall);
  if (tailscaleModalCancel) tailscaleModalCancel.addEventListener('click', closeTailscaleModal);
  if (tailscaleModalClose) tailscaleModalClose.addEventListener('click', closeTailscaleModal);
  if (tailscaleModal) tailscaleModal.addEventListener('click', (e) => {
    if (e.target === tailscaleModal) closeTailscaleModal();
  });
  if (lootPreviewClose) lootPreviewClose.addEventListener('click', closePreview);
  if (lootPreview) lootPreview.addEventListener('click', (e) => {
    if (e.target === lootPreview) closePreview();
  });
  if (nmapVizClose) nmapVizClose.addEventListener('click', closeNmapViz);
  if (nmapVizModal) nmapVizModal.addEventListener('click', (e) => {
    if (e.target === nmapVizModal) closeNmapViz();
  });
  if (nmapVizFilterVuln) nmapVizFilterVuln.addEventListener('change', renderNmapVisualization);
  if (authModalConfirm) authModalConfirm.addEventListener('click', () => {
    resolveAuthPrompt({
      recovery: authRecoveryMode,
      token: authModalToken ? authModalToken.value : '',
      username: authModalUsername ? authModalUsername.value : '',
      password: authModalPassword ? authModalPassword.value : '',
      confirm: authModalPasswordConfirm ? authModalPasswordConfirm.value : '',
    });
  });
  if (authModalCancel) authModalCancel.addEventListener('click', () => resolveAuthPrompt(null));
  if (authModalClose) authModalClose.addEventListener('click', () => resolveAuthPrompt(null));
  if (authModal) authModal.addEventListener('click', (e) => {
    if (e.target === authModal) resolveAuthPrompt(null);
  });
  if (authModalToggleRecovery) authModalToggleRecovery.addEventListener('click', () => {
    setRecoveryMode(!authRecoveryMode);
  });
  const authSubmitFromEnter = (e) => {
    if (e.key === 'Enter'){
      e.preventDefault();
      resolveAuthPrompt({
        recovery: authRecoveryMode,
        token: authModalToken ? authModalToken.value : '',
        username: authModalUsername ? authModalUsername.value : '',
        password: authModalPassword ? authModalPassword.value : '',
        confirm: authModalPasswordConfirm ? authModalPasswordConfirm.value : '',
      });
    } else if (e.key === 'Escape'){
      e.preventDefault();
      resolveAuthPrompt(null);
    }
  };
  if (authModalToken) authModalToken.addEventListener('keydown', authSubmitFromEnter);
  if (authModalUsername) authModalUsername.addEventListener('keydown', authSubmitFromEnter);
  if (authModalPassword) authModalPassword.addEventListener('keydown', authSubmitFromEnter);
  if (authModalPasswordConfirm) authModalPasswordConfirm.addEventListener('keydown', authSubmitFromEnter);
  loadAuthToken();
  loadThemePreference();
  applyTheme();
  loadRotationPreference();
  applyRotation();
  setActiveTab('device');

  let payloadPollTimer = null;
  let systemPollTimer = null;

  function schedulePayloadPoll(){
    if (payloadPollTimer) clearTimeout(payloadPollTimer);
    const delay = document.hidden ? 6000 : 1500;
    payloadPollTimer = setTimeout(async () => {
      await pollPayloadStatus();
      schedulePayloadPoll();
    }, delay);
  }

  function scheduleSystemPoll(){
    if (systemPollTimer) clearTimeout(systemPollTimer);
    const delay = document.hidden ? 10000 : 3000;
    systemPollTimer = setTimeout(async () => {
      if (systemOpen){
        await loadSystemStatus();
      }
      if (mobileSystemTabActive){
        await loadMobileSystemStatus();
      }
      scheduleSystemPoll();
    }, delay);
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden){
      if (systemOpen) loadSystemStatus();
      loadSdrServiceStatus();
      pollPayloadStatus();
      ensureSocketLive();
    }
    schedulePayloadPoll();
    scheduleSystemPoll();
  });

  window.addEventListener('pageshow', () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    wsCandidateIndex = 0;
    reconnectAttempts = 0;
    ensureSocketLive();
  });

  window.addEventListener('online', () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ensureSocketLive();
  });

  const startAfterAuth = () => {
    ensureAuthenticated('Log in to access KTOx WebUI.').then((ok) => {
      if (!ok){
        setTimeout(startAfterAuth, 0);
        return;
      }
      startHeartbeatMonitor();
      connect();
      loadPayloads();
      loadSdrServiceStatus();
      schedulePayloadPoll();
      scheduleSystemPoll();
    });
  };
  startAfterAuth();
})();
