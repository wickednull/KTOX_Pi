(function(){
  const api = window.SdrApi;
  const waterfall = new window.SdrWaterfall(document.getElementById('waterfallCanvas'));
  const receiverSpectrum = new window.SdrSpectrum(document.getElementById('receiverSpectrum'));
  const receiverWaterfall = new window.SdrWaterfall(document.getElementById('receiverWaterfall'));
  const socketPath = `${window.SdrApiBasePath ? window.SdrApiBasePath() : ''}/socket.io`;
  const socket = window.io ? window.io({ path: socketPath }) : null;
  const socketStub = !socket || !!socket.__ktoxStub;
  const settingsKey = 'ktox:sdr:settings';
  const vfoKey = 'ktox:sdr:vfos';
  let waterfallTimer = null;
  let audioCtx = null;
  let audioTimer = null;
  let receiverFrameTimer = null;
  let audioNextTime = 0;
  let lastActivityRefresh = 0;
  let vfos = [];
  let activeVfoId = null;
  let vfoActivity = [];
  const dashboardState = {
    decoderReady: 0,
    decoderTotal: 0,
    alertRules: 0
  };

  const els = {
    deviceDot: document.getElementById('deviceDot'),
    deviceState: document.getElementById('deviceState'),
    deviceSerial: document.getElementById('deviceSerial'),
    boardValue: document.getElementById('boardValue'),
    firmwareValue: document.getElementById('firmwareValue'),
    captureCount: document.getElementById('captureCount'),
    captureBytes: document.getElementById('captureBytes'),
    operatorOverview: document.getElementById('operatorOverview'),
    workflowStrip: document.getElementById('workflowStrip'),
    dashboardMetrics: document.getElementById('dashboardMetrics'),
    overviewDevicePill: document.getElementById('overviewDevicePill'),
    overviewFrequency: document.getElementById('overviewFrequency'),
    overviewMode: document.getElementById('overviewMode'),
    overviewVfos: document.getElementById('overviewVfos'),
    overviewAlerts: document.getElementById('overviewAlerts'),
    overviewDecoders: document.getElementById('overviewDecoders'),
    presetSearch: document.getElementById('presetSearch'),
    presetModeFilter: document.getElementById('presetModeFilter'),
    presetCategoryFilter: document.getElementById('presetCategoryFilter'),
    presetSummary: document.getElementById('presetSummary'),
    quickStartList: document.getElementById('quickStartList'),
    customPresetList: document.getElementById('customPresetList'),
    presetList: document.getElementById('presetList'),
    sweepOutput: document.getElementById('sweepOutput'),
    captureStatus: document.getElementById('captureStatus'),
    captureList: document.getElementById('captureList'),
    waterfallStatus: document.getElementById('waterfallStatus'),
    settingsStatus: document.getElementById('settingsStatus'),
    diagnosticsStatus: document.getElementById('diagnosticsStatus'),
    diagnosticsOutput: document.getElementById('diagnosticsOutput'),
    connectStatus: document.getElementById('connectStatus'),
    usbStatus: document.getElementById('usbStatus'),
    readinessOutput: document.getElementById('readinessOutput'),
    serialPort: document.getElementById('serialPort'),
    serialBaud: document.getElementById('serialBaud'),
    serialStatus: document.getElementById('serialStatus'),
    audioStatus: document.getElementById('audioStatus'),
    receiverSignal: document.getElementById('receiverSignal'),
    receiverStatus: document.getElementById('receiverStatus'),
    receiverOutput: document.getElementById('receiverOutput'),
    vfoList: document.getElementById('vfoList'),
    vfoActivity: document.getElementById('vfoActivity'),
    vfoImportFile: document.getElementById('vfoImportFile'),
    activitySummary: document.getElementById('activitySummary'),
    activityList: document.getElementById('activityList'),
    activityMinPeak: document.getElementById('activityMinPeak'),
    activitySearch: document.getElementById('activitySearch'),
    scanPlanSelect: document.getElementById('scanPlanSelect'),
    scanPlanOutput: document.getElementById('scanPlanOutput'),
    alertSummary: document.getElementById('alertSummary'),
    alertRules: document.getElementById('alertRules'),
    alertEvents: document.getElementById('alertEvents'),
    scanOutput: document.getElementById('scanOutput'),
    bookmarkSearch: document.getElementById('bookmarkSearch'),
    bookmarkCategory: document.getElementById('bookmarkCategory'),
    bookmarkList: document.getElementById('bookmarkList'),
    decoderStatus: document.getElementById('decoderStatus'),
    decoderEvents: document.getElementById('decoderEvents'),
    decoderPlanOutput: document.getElementById('decoderPlanOutput'),
    trunkAgreementStatus: document.getElementById('trunkAgreementStatus'),
    trunkProfileSelect: document.getElementById('trunkProfileSelect'),
    trunkProfiles: document.getElementById('trunkProfiles'),
    trunkStatus: document.getElementById('trunkStatus'),
    trunkProcessStatus: document.getElementById('trunkProcessStatus'),
    trunkDecoderStatus: document.getElementById('trunkDecoderStatus'),
    trunkSummary: document.getElementById('trunkSummary'),
    trunkEvents: document.getElementById('trunkEvents')
  };

  function bytes(size){
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = Number(size) || 0;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
  }

  function setDevice(info){
    const ok = !!(info.connected || info.available);
    els.deviceDot.classList.toggle('ok', ok);
    els.deviceState.textContent = ok ? 'HackRF online' : 'HackRF unavailable';
    els.deviceSerial.textContent = ok ? (info.serial_number || 'serial unknown') : (info.error || 'not detected');
    els.boardValue.textContent = info.board || '-';
    els.firmwareValue.textContent = info.firmware || '-';
    setOverviewDevice(ok, ok ? 'HackRF online' : 'HackRF offline');
    if (els.connectStatus) {
      els.connectStatus.textContent = ok ? 'HackRF connected and ready.' : (info.error || 'HackRF is not connected.');
    }
    if (els.usbStatus) {
      const tools = info.tools || {};
      const usb = info.usb || {};
      const lines = [
        `hackrf_info: ${tools.hackrf_info ? 'found' : 'missing'}`,
        `hackrf_transfer: ${tools.hackrf_transfer ? 'found' : 'missing'}`,
        `hackrf_sweep: ${tools.hackrf_sweep ? 'found' : 'missing'}`,
        `lsusb: ${tools.lsusb ? 'found' : 'missing'}`,
        `USB HackRF matches: ${(usb.hackrf || []).length}`
      ];
      if ((usb.hackrf || []).length) {
        lines.push('');
        lines.push(...usb.hackrf);
      }
      els.usbStatus.textContent = lines.join('\n');
    }
  }

  async function loadInfo(){
    try {
      setDevice(await api.info());
    } catch (err) {
      setDevice({ available: false, error: err.message });
    }
  }

  async function connectHackrf(){
    els.connectStatus.textContent = 'Checking HackRF USB connection...';
    try {
      setDevice(await api.connect());
    } catch (err) {
      setDevice({ available: false, connected: false, error: err.message, tools: {}, usb: { hackrf: [] } });
    }
  }

  async function loadCaptures(){
    try {
      const data = await api.captures();
      const captures = data.captures || [];
      els.captureCount.textContent = String(captures.length);
      els.captureBytes.textContent = bytes(data.stats && data.stats.total_size);
      els.captureList.innerHTML = captures.length ? captures.map(item => (
        `<div class="capture-row"><strong>${item.filename}</strong><span>${item.frequency} Hz</span><span>${bytes(item.size)}</span><a href="${window.SdrApiUrl(`/api/hackrf/captures/${item.id}/download`)}">Download</a><button data-delete-capture="${item.id}">Delete</button></div>`
      )).join('') : '<div class="empty">No captures indexed.</div>';
    } catch (err) {
      els.captureCount.textContent = '0';
      els.captureBytes.textContent = '0 B';
      els.captureList.innerHTML = `<div class="empty">Capture backend unavailable: ${err.message}</div>`;
    }
  }

  function presetSearchText(key, group){
    const values = [key, group.label, group.mode, group.category];
    (group.frequencies || []).forEach(raw => {
      const item = typeof raw === 'number' ? { hz: raw, label: mhz(raw) } : raw;
      values.push(item.label, item.hz, item.start, item.stop, item.mode);
    });
    return values.filter(value => value != null).join(' ').toLowerCase();
  }

  function renderPresetNavigator(){
    if (!els.presetList) return;
    const presets = els.presetList._presets || {};
    const query = (els.presetSearch && els.presetSearch.value || '').trim().toLowerCase();
    const modeFilter = els.presetModeFilter && els.presetModeFilter.value;
    const categoryFilter = els.presetCategoryFilter && els.presetCategoryFilter.value;
    const keys = Object.keys(presets).filter(key => {
      const group = presets[key] || {};
      const mode = group.mode || (key === 'fm' ? 'wfm' : 'nfm');
      const category = group.category || key;
      if (modeFilter && mode !== modeFilter) return false;
      if (categoryFilter && category !== categoryFilter) return false;
      return !query || presetSearchText(key, group).includes(query);
    });
    els.presetList.innerHTML = keys.length ? keys.map(key => {
      const group = presets[key];
      const mode = group.mode || (key === 'fm' ? 'wfm' : 'nfm');
      const category = group.category || key;
      const buttons = (group.frequencies || []).map(raw => {
        const item = typeof raw === 'number' ? { hz: raw, label: mhz(raw) } : raw;
        const itemMode = item.mode || mode;
        const bandwidth = item.bandwidth || group.bandwidth || 12500;
        const sampleRate = item.sample_rate || group.sample_rate || 2000000;
        const step = item.step || group.step || 12500;
        if (item.hz) {
          return `<button data-preset-frequency="${Number(item.hz)}" data-preset-mode="${escapeHtml(itemMode)}" data-preset-bandwidth="${Number(bandwidth)}" data-preset-sample-rate="${Number(sampleRate)}" data-preset-step="${Number(step)}">${escapeHtml(item.label || mhz(item.hz))}</button>`;
        }
        return `<button data-preset-start="${Number(item.start)}" data-preset-stop="${Number(item.stop)}" data-preset-mode="${escapeHtml(itemMode)}" data-preset-bandwidth="${Number(bandwidth)}" data-preset-sample-rate="${Number(sampleRate)}" data-preset-step="${Number(step)}">${escapeHtml(item.label || `${mhz(item.start)}-${mhz(item.stop)}`)}</button>`;
      }).join('');
      return `<article class="preset-card" data-category="${escapeHtml(category)}" data-mode="${escapeHtml(mode)}"><strong>${escapeHtml(group.label)}</strong><span>${(group.frequencies || []).length} presets · ${escapeHtml(String(mode).toUpperCase())} · ${escapeHtml(category)}</span><div class="preset-buttons">${buttons}</div></article>`;
    }).join('') : '<div class="empty">No presets match the current filters.</div>';
    if (els.presetSummary) {
      const totalChannels = keys.reduce((sum, key) => sum + ((presets[key].frequencies || []).length), 0);
      els.presetSummary.textContent = `${keys.length} packs · ${totalChannels} entries`;
    }
  }

  function populatePresetFilters(presets){
    const modes = new Set();
    const categories = new Set();
    Object.keys(presets).forEach(key => {
      const group = presets[key] || {};
      modes.add(group.mode || (key === 'fm' ? 'wfm' : 'nfm'));
      categories.add(group.category || key);
    });
    if (els.presetModeFilter) {
      const selected = els.presetModeFilter.value;
      els.presetModeFilter.innerHTML = '<option value="">All modes</option>' + Array.from(modes).sort().map(mode => (
        `<option value="${escapeHtml(mode)}">${escapeHtml(String(mode).toUpperCase())}</option>`
      )).join('');
      els.presetModeFilter.value = modes.has(selected) ? selected : '';
    }
    if (els.presetCategoryFilter) {
      const selected = els.presetCategoryFilter.value;
      els.presetCategoryFilter.innerHTML = '<option value="">All categories</option>' + Array.from(categories).sort().map(category => (
        `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`
      )).join('');
      els.presetCategoryFilter.value = categories.has(selected) ? selected : '';
    }
  }

  async function loadPresets(){
    let presets;
    try {
      presets = await api.presets();
    } catch (err) {
      presets = {
        weather: { label: 'NOAA Weather', mode: 'nfm', bandwidth: 12500, sample_rate: 2000000, step: 25000, frequencies: [{ label: 'WX 1', hz: 162550000 }, { label: 'WX 2', hz: 162400000 }] },
        airband: { label: 'Airband', mode: 'am', bandwidth: 25000, sample_rate: 2000000, step: 25000, frequencies: [{ label: 'Emergency', hz: 121500000 }, { label: 'Civil Airband', start: 118000000, stop: 137000000 }] },
        fm: { label: 'FM Broadcast', mode: 'wfm', bandwidth: 180000, sample_rate: 2400000, step: 200000, frequencies: [{ label: '88-108 MHz', start: 88000000, stop: 108000000 }, { label: '98.1', hz: 98100000 }] },
        adsb: { label: 'ADS-B', mode: 'raw', bandwidth: 2000000, sample_rate: 2000000, step: 1000000, frequencies: [{ label: '1090ES', hz: 1090000000 }] }
      };
    }
    els.presetList._presets = presets;
    populatePresetFilters(presets);
    renderPresetNavigator();
  }

  async function loadQuickStarts(){
    if (!els.quickStartList) return;
    let profiles;
    try {
      profiles = await api.quickStarts();
    } catch {
      profiles = {
        weather_watch: {
          label: 'Weather Watch',
          description: 'NOAA weather receiver, VFO, scan range, and watch rule.',
          receiver: { frequency: 162550000, mode: 'nfm', bandwidth: 12500, sample_rate: 2000000, step: 25000 },
          scan_ranges: [{ label: 'NOAA Weather', start: 162400000, stop: 162550000, threshold_db: -70 }],
          vfos: [{ label: 'NOAA WX 1', frequency: 162550000, mode: 'nfm', bandwidth: 12500, squelch: -85 }],
          alert_rules: [{ label: 'NOAA WX 1 open', frequency: 162550000, tolerance_hz: 25000, min_peak_db: -75 }]
        }
      };
    }
    els.quickStartList.innerHTML = Object.keys(profiles).map(key => {
      const item = profiles[key];
      return `<article class="preset-card">
        <strong>${escapeHtml(item.label || key)}</strong>
        <span>${escapeHtml(item.description || '')}</span>
        <div class="preset-buttons"><button data-quick-start="${escapeHtml(key)}">Apply Setup</button></div>
      </article>`;
    }).join('');
    els.quickStartList._profiles = profiles;
  }

  async function applyQuickStart(key){
    const profiles = els.quickStartList && els.quickStartList._profiles;
    const profile = profiles && profiles[key];
    if (!profile) return;
    const receiver = profile.receiver || {};
    if (receiver.frequency) tuneFrequency(receiver.frequency, receiver.mode || 'nfm');
    if (receiver.bandwidth) document.getElementById('rxBandwidth').value = String(receiver.bandwidth);
    if (receiver.sample_rate) document.getElementById('rxSampleRate').value = String(receiver.sample_rate);
    if (receiver.step) document.getElementById('rxStep').value = String(receiver.step);
    const firstRange = (profile.scan_ranges || [])[0];
    if (firstRange) {
      document.getElementById('scanStart').value = String(firstRange.start);
      document.getElementById('scanStop').value = String(firstRange.stop);
      document.getElementById('scanThreshold').value = String(firstRange.threshold_db == null ? -60 : firstRange.threshold_db);
      document.getElementById('sweepStart').value = String(firstRange.start);
      document.getElementById('sweepStop').value = String(firstRange.stop);
    }
    (profile.vfos || []).forEach((row, index) => {
      vfos.unshift(Object.assign({
        id: `vfo-quick-${Date.now().toString(36)}-${index}`,
        activity: 0,
        source: 'quick-start'
      }, row));
    });
    if ((profile.vfos || []).length) {
      activeVfoId = vfos[0].id;
      saveVfos();
      renderVfos();
    }
    for (const rule of (profile.alert_rules || [])) {
      try {
        await api.receiverAlertRuleAdd(rule);
      } catch {}
    }
    if (profile.decoder && document.getElementById('decoderType')) {
      document.getElementById('decoderType').value = profile.decoder.decoder || 'rds';
      document.getElementById('decoderFrequency').value = String(profile.decoder.frequency || receiver.frequency || 98100000);
      document.getElementById('decoderMode').value = profile.decoder.mode || receiver.mode || 'wfm';
    }
    if (els.connectStatus) els.connectStatus.textContent = `Applied Quick Start: ${profile.label || key}`;
    await loadAlerts();
    renderOperatorOverview();
  }

  function renderCustomPresets(data){
    if (!els.customPresetList) return;
    const rows = data.presets || [];
    els.customPresetList.innerHTML = rows.length ? rows.map(item => (
      `<div class="capture-row">
        <strong>${escapeHtml(item.label)}</strong>
        <span>${mhz(item.frequency)}</span>
        <span>${escapeHtml(String(item.mode || 'nfm').toUpperCase())}</span>
        <span>${escapeHtml(item.category || 'custom')}</span>
        <button data-apply-custom-preset="${escapeHtml(item.id)}">Apply</button>
        <button data-delete-custom-preset="${escapeHtml(item.id)}">Delete</button>
      </div>`
    )).join('') : '<div class="empty">No custom presets saved.</div>';
    els.customPresetList._presets = rows;
  }

  async function loadCustomPresets(){
    if (!els.customPresetList) return;
    try {
      renderCustomPresets(await api.customPresets());
    } catch (err) {
      els.customPresetList.innerHTML = `<div class="empty">Custom preset load failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  function applyCustomPreset(id){
    const rows = els.customPresetList && els.customPresetList._presets || [];
    const preset = rows.find(item => item.id === id);
    if (!preset) return;
    tuneFrequency(preset.frequency, preset.mode || 'nfm');
    document.getElementById('rxBandwidth').value = String(preset.bandwidth || 12500);
    document.getElementById('rxSampleRate').value = String(preset.sample_rate || 2000000);
    document.getElementById('rxStep').value = String(preset.step || 12500);
    if (els.connectStatus) els.connectStatus.textContent = `Applied custom preset: ${preset.label}`;
  }

  async function saveCustomPreset(){
    try {
      const settings = currentReceiverSettings();
      await api.customPresetAdd(Object.assign({
        label: document.getElementById('customPresetLabel').value,
        category: document.getElementById('customPresetCategory').value || 'custom',
        step: numeric('rxStep') || 12500
      }, settings));
      await loadCustomPresets();
    } catch (err) {
      if (els.customPresetList) els.customPresetList.innerHTML = `<div class="empty">Custom preset save failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function importCustomPresets(){
    if (!els.customPresetList) return;
    els.customPresetList.innerHTML = '<div class="empty">Importing custom presets...</div>';
    try {
      const payload = await readJsonFile('customPresetImportFile');
      const result = await api.customPresetsImport(payload);
      els.customPresetList.innerHTML = `<div class="empty">Imported ${Number(result.imported || 0)} custom presets.</div>`;
      await loadCustomPresets();
    } catch (err) {
      els.customPresetList.innerHTML = `<div class="empty">Custom preset import failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  function numeric(id){
    return Number(document.getElementById(id).value);
  }

  function pretty(value){
    return JSON.stringify(value, null, 2);
  }

  function mhz(value){
    return `${(Number(value) / 1000000).toFixed(3)} MHz`;
  }

  function renderOperatorOverview(){
    if (!els.operatorOverview) return;
    const frequency = numeric('rxFrequency') || 162550000;
    const mode = document.getElementById('rxMode') ? document.getElementById('rxMode').value : 'nfm';
    if (els.overviewFrequency) els.overviewFrequency.textContent = mhz(frequency);
    if (els.overviewMode) els.overviewMode.textContent = String(mode || 'nfm').toUpperCase();
    if (els.overviewVfos) els.overviewVfos.textContent = String(vfos.length);
    if (els.overviewAlerts) els.overviewAlerts.textContent = String(dashboardState.alertRules || 0);
    if (els.overviewDecoders) {
      els.overviewDecoders.textContent = `${dashboardState.decoderReady || 0}/${dashboardState.decoderTotal || 0} ready`;
    }
  }

  function setOverviewDevice(ok, label){
    if (!els.overviewDevicePill) return;
    els.overviewDevicePill.textContent = label;
    els.overviewDevicePill.classList.toggle('ok', !!ok);
    els.overviewDevicePill.classList.toggle('warn', !ok);
  }

  function activateTab(tab){
    if (!tab) return;
    document.querySelectorAll('.tab').forEach(item => item.classList.toggle('active', item.dataset.tab === tab));
    document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === tab));
    if (tab === 'receiver') {
      renderOperatorOverview();
    }
  }

  function tuneFrequency(frequency, mode){
    const value = Number(frequency);
    if (!Number.isFinite(value) || value <= 0) return;
    document.getElementById('rxFrequency').value = String(Math.round(value));
    document.getElementById('captureFrequency').value = String(Math.round(value));
    if (document.getElementById('decoderFrequency')) {
      document.getElementById('decoderFrequency').value = String(Math.round(value));
    }
    if (document.getElementById('alertRuleFrequency')) {
      document.getElementById('alertRuleFrequency').value = String(Math.round(value));
    }
    document.getElementById('sweepStart').value = String(Math.max(1000000, Math.round(value - 5000000)));
    document.getElementById('sweepStop').value = String(Math.min(6000000000, Math.round(value + 5000000)));
    if (mode && document.getElementById('rxMode')) {
      document.getElementById('rxMode').value = mode;
    }
    if (mode && document.getElementById('decoderMode') && ['nfm', 'wfm', 'am'].includes(mode)) {
      document.getElementById('decoderMode').value = mode;
    }
    if (els.receiverStatus) els.receiverStatus.textContent = `Tuned ${mhz(value)}`;
    if (els.audioStatus) els.audioStatus.textContent = `Ready at ${mhz(value)}`;
    renderOperatorOverview();
  }

  function applyPresetDefaults(button){
    if (!button) return;
    const mode = button.getAttribute('data-preset-mode');
    const bandwidth = Number(button.getAttribute('data-preset-bandwidth'));
    const sampleRate = Number(button.getAttribute('data-preset-sample-rate'));
    const step = Number(button.getAttribute('data-preset-step'));
    if (mode && document.getElementById('rxMode')) document.getElementById('rxMode').value = mode;
    if (Number.isFinite(bandwidth) && bandwidth > 0) document.getElementById('rxBandwidth').value = String(bandwidth);
    if (Number.isFinite(sampleRate) && sampleRate > 0) document.getElementById('rxSampleRate').value = String(sampleRate);
    if (Number.isFinite(step) && step > 0) document.getElementById('rxStep').value = String(step);
  }

  function applyPresetRange(button){
    applyPresetDefaults(button);
    const start = Number(button.getAttribute('data-preset-start'));
    const stop = Number(button.getAttribute('data-preset-stop'));
    if (!Number.isFinite(start) || !Number.isFinite(stop) || stop <= start) return;
    document.getElementById('scanStart').value = String(Math.round(start));
    document.getElementById('scanStop').value = String(Math.round(stop));
    document.getElementById('sweepStart').value = String(Math.round(start));
    document.getElementById('sweepStop').value = String(Math.round(stop));
    tuneFrequency(Math.round((start + stop) / 2), button.getAttribute('data-preset-mode') || 'nfm');
    if (els.receiverStatus) els.receiverStatus.textContent = `Range loaded ${mhz(start)}-${mhz(stop)}`;
  }

  function currentReceiverSettings(){
    return {
      frequency: numeric('rxFrequency') || 162550000,
      sample_rate: numeric('rxSampleRate') || 2000000,
      mode: document.getElementById('rxMode').value || 'nfm',
      bandwidth: numeric('rxBandwidth') || 12500,
      squelch: numeric('rxSquelch') || -90,
      lna_gain: numeric('rxLna') || 16,
      vga_gain: numeric('rxVga') || 20
    };
  }

  function defaultVfos(){
    return [
      { id: 'vfo-weather', label: 'NOAA 162.550', frequency: 162550000, mode: 'nfm', bandwidth: 12500, squelch: -90, activity: 0 },
      { id: 'vfo-fm', label: 'FM 98.100', frequency: 98100000, mode: 'wfm', bandwidth: 180000, squelch: -95, activity: 0 },
      { id: 'vfo-adsb', label: 'ADS-B 1090', frequency: 1090000000, mode: 'raw', bandwidth: 2000000, squelch: -80, activity: 0 }
    ];
  }

  function saveVfos(){
    localStorage.setItem(vfoKey, JSON.stringify({
      activeVfoId,
      vfos,
      activity: vfoActivity.slice(0, 40)
    }));
  }

  function loadVfos(){
    try {
      const saved = JSON.parse(localStorage.getItem(vfoKey) || '{}');
      vfos = Array.isArray(saved.vfos) && saved.vfos.length ? saved.vfos : defaultVfos();
      activeVfoId = saved.activeVfoId || (vfos[0] && vfos[0].id) || null;
      vfoActivity = Array.isArray(saved.activity) ? saved.activity.slice(0, 40) : [];
    } catch {
      vfos = defaultVfos();
      activeVfoId = vfos[0] && vfos[0].id;
      vfoActivity = [];
    }
    renderVfos();
  }

  function vfoById(id){
    return vfos.find(item => item.id === id) || null;
  }

  function applyVfoToControls(vfo){
    if (!vfo) return;
    tuneFrequency(vfo.frequency, vfo.mode || 'nfm');
    if (document.getElementById('rxBandwidth')) document.getElementById('rxBandwidth').value = String(vfo.bandwidth || 12500);
    if (document.getElementById('rxSquelch')) document.getElementById('rxSquelch').value = String(vfo.squelch == null ? -90 : vfo.squelch);
    if (document.getElementById('rxSampleRate')) document.getElementById('rxSampleRate').value = String(vfo.sample_rate || 2000000);
  }

  function addVfo(){
    const settings = currentReceiverSettings();
    const id = `vfo-${Date.now().toString(36)}`;
    const label = `${mhz(settings.frequency)} ${String(settings.mode || 'nfm').toUpperCase()}`;
    vfos.unshift(Object.assign({ id, label, activity: 0, created_at: new Date().toISOString() }, settings));
    activeVfoId = id;
    vfoActivity.unshift(`${new Date().toLocaleTimeString()} added ${label}`);
    vfoActivity = vfoActivity.slice(0, 40);
    saveVfos();
    renderVfos();
  }

  function exportVfos(){
    downloadJson('ktox-sdr-vfo-group.json', {
      schema: 'ktox-sdr-vfo-group-v1',
      exported_at: new Date().toISOString(),
      activeVfoId,
      vfos
    });
  }

  async function importVfos(){
    if (els.vfoActivity) els.vfoActivity.textContent = 'Importing VFO group...';
    try {
      const payload = await readJsonFile('vfoImportFile');
      const rows = Array.isArray(payload.vfos) ? payload.vfos : (Array.isArray(payload) ? payload : []);
      if (!rows.length) throw new Error('vfos list is required');
      vfos = rows
        .filter(row => row && Number(row.frequency) > 0)
        .map((row, index) => Object.assign({
          id: row.id || `vfo-import-${Date.now().toString(36)}-${index}`,
          label: row.label || mhz(row.frequency),
          mode: row.mode || 'nfm',
          bandwidth: row.bandwidth || 12500,
          squelch: row.squelch == null ? -90 : row.squelch,
          activity: Number(row.activity || 0)
        }, row));
      if (!vfos.length) throw new Error('no valid VFO rows found');
      activeVfoId = payload.activeVfoId || vfos[0].id;
      vfoActivity.unshift(`${new Date().toLocaleTimeString()} imported ${vfos.length} VFOs`);
      vfoActivity = vfoActivity.slice(0, 40);
      saveVfos();
      renderVfos();
      applyVfoToControls(vfoById(activeVfoId));
    } catch (err) {
      if (els.vfoActivity) els.vfoActivity.textContent = `VFO import failed: ${err.message}`;
    }
  }

  function selectVfo(id){
    const vfo = vfoById(id);
    if (!vfo) return;
    activeVfoId = id;
    applyVfoToControls(vfo);
    vfoActivity.unshift(`${new Date().toLocaleTimeString()} selected ${vfo.label || mhz(vfo.frequency)}`);
    vfoActivity = vfoActivity.slice(0, 40);
    saveVfos();
    renderVfos();
  }

  function deleteVfo(id){
    vfos = vfos.filter(item => item.id !== id);
    if (!vfos.length) {
      vfos = defaultVfos();
    }
    if (activeVfoId === id) {
      activeVfoId = vfos[0] && vfos[0].id;
      applyVfoToControls(vfoById(activeVfoId));
    }
    saveVfos();
    renderVfos();
  }

  function recordVfoActivity(frame){
    const active = vfoById(activeVfoId);
    if (!active || !frame) return;
    const peak = Number(frame.peak_db == null ? -120 : frame.peak_db);
    active.frequency = Number(frame.frequency || numeric('rxFrequency') || active.frequency);
    active.mode = document.getElementById('rxMode').value || active.mode || 'nfm';
    active.bandwidth = numeric('rxBandwidth') || active.bandwidth || 12500;
    active.squelch = numeric('rxSquelch');
    active.last_peak = peak;
    active.last_seen = new Date().toISOString();
    active.squelch_open = !!frame.squelch_open;
    if (frame.squelch_open) {
      active.activity = Number(active.activity || 0) + 1;
      active.last_open = active.last_seen;
      vfoActivity.unshift(`${new Date().toLocaleTimeString()} ${active.label || mhz(active.frequency)} opened at ${peak.toFixed(1)} dB`);
      vfoActivity = vfoActivity.slice(0, 40);
    }
    saveVfos();
    renderVfos();
  }

  function renderVfos(){
    if (!els.vfoList) return;
    const sorted = vfos.slice().sort((a, b) => {
      if (a.id === activeVfoId) return -1;
      if (b.id === activeVfoId) return 1;
      return Number(b.activity || 0) - Number(a.activity || 0);
    });
    els.vfoList.innerHTML = sorted.map((item) => {
      const active = item.id === activeVfoId;
      const status = item.squelch_open ? 'Live' : 'Idle';
      const peak = item.last_peak == null ? 'no signal' : `${Number(item.last_peak).toFixed(1)} dB`;
      return `<article class="vfo-row ${active ? 'active' : ''}">
        <div class="vfo-main">
          <strong>${escapeHtml(item.label || mhz(item.frequency))}</strong>
          <span>${mhz(item.frequency)} · ${escapeHtml(String(item.mode || 'nfm').toUpperCase())} · ${Number(item.bandwidth || 0)} Hz</span>
        </div>
        <div class="vfo-meter">
          <span class="${item.squelch_open ? 'live' : ''}">${status}</span>
          <strong>${peak}</strong>
          <span>${Number(item.activity || 0)} opens</span>
        </div>
        <div class="vfo-actions">
          <button data-select-vfo="${escapeHtml(item.id)}">${active ? 'Active' : 'Tune'}</button>
          <button data-delete-vfo="${escapeHtml(item.id)}">Delete</button>
        </div>
      </article>`;
    }).join('');
    if (els.vfoActivity) {
      els.vfoActivity.textContent = vfoActivity.length ? vfoActivity.join('\n') : 'No VFO activity yet.';
    }
    renderOperatorOverview();
  }

  function renderActivity(data){
    if (!els.activityList) return;
    const summary = data.summary || {};
    const top = summary.top_frequencies || [];
    if (els.activitySummary) {
      els.activitySummary.innerHTML = [
        `<article class="tile"><span>Total Events</span><strong>${Number(summary.total_events || 0)}</strong></article>`,
        `<article class="tile"><span>Open Squelch</span><strong>${Number(summary.open_events || 0)}</strong></article>`,
        `<article class="tile"><span>Tracked Frequencies</span><strong>${top.length}</strong></article>`,
        `<article class="tile"><span>Best Peak</span><strong>${top.length ? `${Number(top[0].best_peak_db || -120).toFixed(1)} dB` : '-'}</strong></article>`
      ].join('');
    }
    const rows = data.events || [];
    els.activityList.innerHTML = rows.length ? rows.map(item => (
      `<div class="capture-row activity-row">
        <strong>${mhz(item.frequency)}</strong>
        <span>${escapeHtml(String(item.mode || 'nfm').toUpperCase())}</span>
        <span>${Number(item.peak_db || -120).toFixed(1)} dB</span>
        <span>${item.squelch_open ? 'open' : 'closed'}</span>
        <button data-promote-activity="vfo" data-frequency="${item.frequency}" data-mode="${escapeHtml(item.mode || 'nfm')}">Promote VFO</button>
        <button data-promote-activity="bookmark" data-frequency="${item.frequency}" data-mode="${escapeHtml(item.mode || 'nfm')}">Promote Bookmark</button>
      </div>`
    )).join('') : '<div class="empty">No receiver activity recorded yet.</div>';
  }

  async function loadActivity(){
    if (!els.activityList) return;
    try {
      const params = {};
      if (els.activityMinPeak && els.activityMinPeak.value !== '') params.min_peak = els.activityMinPeak.value;
      if (els.activitySearch && els.activitySearch.value.trim()) params.q = els.activitySearch.value.trim();
      renderActivity(await api.receiverActivity(params));
    } catch (err) {
      els.activityList.innerHTML = `<div class="empty">Activity load failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function promoteActivity(kind, frequency, mode){
    const value = Number(frequency);
    if (!Number.isFinite(value) || value <= 0) return;
    tuneFrequency(value, mode || 'nfm');
    if (kind === 'bookmark') {
      await api.receiverBookmarkAdd({
        label: `Activity ${mhz(value)}`,
        frequency: value,
        mode: mode || 'nfm',
        category: 'activity',
        source: 'activity-intelligence'
      });
      await loadBookmarks();
      return;
    }
    const settings = currentReceiverSettings();
    const id = `vfo-activity-${Date.now().toString(36)}`;
    vfos.unshift(Object.assign({ id, label: `Activity ${mhz(value)}`, activity: 0, source: 'activity-intelligence' }, settings));
    activeVfoId = id;
    saveVfos();
    renderVfos();
  }

  function renderAlerts(data){
    if (!els.alertRules || !els.alertEvents) return;
    const summary = data.summary || {};
    dashboardState.alertRules = Number(summary.enabled_rules || summary.total_rules || 0);
    renderOperatorOverview();
    if (els.alertSummary) {
      els.alertSummary.innerHTML = [
        `<article class="tile"><span>Rules</span><strong>${Number(summary.total_rules || 0)}</strong></article>`,
        `<article class="tile"><span>Enabled</span><strong>${Number(summary.enabled_rules || 0)}</strong></article>`,
        `<article class="tile"><span>Alerts</span><strong>${Number(summary.total_alerts || 0)}</strong></article>`,
        `<article class="tile"><span>Last Alert</span><strong>${summary.last_alert ? new Date(Number(summary.last_alert) * 1000).toLocaleTimeString() : '-'}</strong></article>`
      ].join('');
    }
    const rules = data.rules || [];
    els.alertRules.innerHTML = rules.length ? rules.map(rule => (
      `<div class="capture-row">
        <strong>${escapeHtml(rule.label)}</strong>
        <span>${mhz(rule.frequency)}</span>
        <span>${Number(rule.min_peak_db || -60).toFixed(1)} dB</span>
        <span>±${Number(rule.tolerance_hz || 0)} Hz</span>
        <button data-delete-alert-rule="${escapeHtml(rule.id)}">Delete</button>
      </div>`
    )).join('') : '<div class="empty">No watch rules saved.</div>';
    const events = data.events || [];
    els.alertEvents.innerHTML = events.length ? events.map(event => (
      `<div class="capture-row activity-row">
        <strong>${escapeHtml(event.label || '')}</strong>
        <span>${mhz(event.frequency)}</span>
        <span>${Number(event.peak_db || -120).toFixed(1)} dB</span>
        <span>${event.squelch_open ? 'open' : 'closed'}</span>
        <button data-promote-activity="vfo" data-frequency="${event.frequency}" data-mode="${escapeHtml(event.mode || 'nfm')}">Promote VFO</button>
        <button data-promote-activity="bookmark" data-frequency="${event.frequency}" data-mode="${escapeHtml(event.mode || 'nfm')}">Promote Bookmark</button>
      </div>`
    )).join('') : '<div class="empty">No alert events yet.</div>';
  }

  async function loadAlerts(){
    if (!els.alertRules) return;
    try {
      renderAlerts(await api.receiverAlerts());
    } catch (err) {
      els.alertRules.innerHTML = `<div class="empty">Alert load failed: ${escapeHtml(err.message)}</div>`;
      if (els.alertEvents) els.alertEvents.innerHTML = '<div class="empty">Alert events unavailable.</div>';
    }
  }

  async function saveAlertRule(){
    try {
      await api.receiverAlertRuleAdd({
        label: document.getElementById('alertRuleLabel').value,
        frequency: numeric('alertRuleFrequency') || numeric('rxFrequency') || 162550000,
        mode: document.getElementById('rxMode').value || 'nfm',
        tolerance_hz: numeric('alertRuleTolerance') || 12500,
        min_peak_db: numeric('alertRuleMinPeak') || -60,
        require_open: true,
        enabled: true
      });
      await loadAlerts();
    } catch (err) {
      if (els.alertRules) els.alertRules.innerHTML = `<div class="empty">Watch save failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  function csvNumbers(id){
    const raw = document.getElementById(id).value || '';
    return raw.split(',').map(item => item.trim()).filter(Boolean).map(item => Number(item)).filter(item => Number.isFinite(item));
  }

  function readJsonFile(inputId){
    const input = document.getElementById(inputId);
    const file = input && input.files && input.files[0];
    if (!file) {
      return Promise.reject(new Error('Choose a JSON file first.'));
    }
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        try {
          resolve(JSON.parse(String(reader.result || '{}')));
        } catch (err) {
          reject(new Error(`Invalid JSON: ${err.message}`));
        }
      };
      reader.onerror = () => reject(new Error('File read failed.'));
      reader.readAsText(file);
    });
  }

  function downloadJson(filename, payload){
    const blob = new Blob([JSON.stringify(payload, null, 2) + '\n'], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function escapeHtml(value){
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function testHackrf(){
    els.connectStatus.textContent = 'Running HackRF RX and sweep test...';
    try {
      const data = await api.test({
        frequency: numeric('captureFrequency') || 2437000000,
        sample_rate: numeric('captureSampleRate') || 20000000
      });
      setDevice(data.connect || {});
      els.usbStatus.textContent = pretty(data);
      els.connectStatus.textContent = data.ok ? 'HackRF RX and sweep test passed.' : 'HackRF test failed; see details below.';
    } catch (err) {
      els.connectStatus.textContent = `HackRF test failed: ${err.message}`;
    }
  }

  async function runReadiness(){
    if (els.readinessOutput) {
      els.readinessOutput.textContent = 'Checking HackRF RX readiness...';
    }
    if (els.connectStatus) {
      els.connectStatus.textContent = 'Reading test IQ samples from HackRF...';
    }
    try {
      const data = await api.readiness({
        frequency: numeric('rxFrequency') || numeric('captureFrequency') || 2437000000,
        sample_rate: numeric('rxSampleRate') || 2000000,
        sample_count: 4096
      });
      setDevice(data.info || {});
      if (els.readinessOutput) {
        els.readinessOutput.textContent = pretty(data);
      }
      if (els.connectStatus) {
        els.connectStatus.textContent = data.ok
          ? 'HackRF RX is working. IQ samples were read successfully.'
          : `HackRF is not ready: ${(data.next_steps || [data.error || 'unknown issue']).join(' ')}`;
      }
    } catch (err) {
      if (els.readinessOutput) {
        els.readinessOutput.textContent = `Readiness failed: ${err.message}`;
      }
      if (els.connectStatus) {
        els.connectStatus.textContent = `HackRF readiness failed: ${err.message}`;
      }
    }
  }

  async function loadSerialPorts(){
    if (!els.serialPort || !els.serialStatus) return;
    els.serialStatus.textContent = 'Scanning serial ports...';
    try {
      const data = await api.serialPorts();
      const ports = data.ports || [];
      els.serialPort.innerHTML = ports.length
        ? ports.map(port => `<option value="${escapeHtml(port.device)}">${escapeHtml(port.device)} - ${escapeHtml(port.description || port.product || 'serial device')}</option>`).join('')
        : '<option value="">No serial ports found</option>';
      els.serialStatus.textContent = pretty(data);
    } catch (err) {
      els.serialPort.innerHTML = '<option value="">Serial backend unavailable</option>';
      els.serialStatus.textContent = `Serial scan failed: ${err.message}`;
    }
  }

  async function probeSerial(){
    if (!els.serialPort || !els.serialStatus) return;
    const port = els.serialPort.value;
    if (!port) {
      els.serialStatus.textContent = 'No serial port selected.';
      return;
    }
    els.serialStatus.textContent = `Opening ${port}...`;
    try {
      els.serialStatus.textContent = pretty(await api.serialProbe({
        port,
        baudrate: Number(els.serialBaud.value) || 115200
      }));
    } catch (err) {
      els.serialStatus.textContent = `Serial probe failed: ${err.message}`;
    }
  }

  async function loadDiagnostics(){
    if (!els.diagnosticsOutput) return;
    els.diagnosticsStatus.textContent = 'Running SDR diagnostics...';
    try {
      const data = await api.diagnostics();
      els.diagnosticsStatus.textContent = data.ok ? 'SDR Suite readiness checks passed.' : 'SDR Suite needs attention; see next_steps.';
      els.diagnosticsOutput.textContent = pretty(data);
    } catch (err) {
      els.diagnosticsStatus.textContent = `Diagnostics failed: ${err.message}`;
      els.diagnosticsOutput.textContent = err.message;
    }
  }

  function receiverPayload(extra){
    return Object.assign({
      frequency: numeric('rxFrequency') || 162550000,
      sample_rate: numeric('rxSampleRate') || 2000000,
      mode: document.getElementById('rxMode').value || 'nfm',
      lna_gain: numeric('rxLna') || 16,
      vga_gain: numeric('rxVga') || 20,
      bandwidth: numeric('rxBandwidth') || 12500,
      squelch: numeric('rxSquelch') || -90,
      fft_size: 512,
      sample_count: 131072,
      audio_rate: 48000
    }, extra || {});
  }

  function receiverAudioPayload(){
    return receiverPayload({
      sample_count: 1048576,
      audio_rate: 48000
    });
  }

  async function receiverFrameLoop(){
    try {
      const data = await api.receiverFrame(receiverPayload({ sample_count: 4096 }));
      if (!data.ok) throw new Error(data.error || 'receiver frame failed');
      receiverSpectrum.draw(data.spectrum || [], data.peaks || []);
      receiverWaterfall.push(data.waterfall || []);
      els.receiverStatus.textContent = data.squelch_open ? 'Signal' : 'Below squelch';
      els.receiverSignal.textContent = `${Number(data.peak_db || -120).toFixed(1)} dB peak`;
      els.receiverOutput.textContent = pretty({
        frequency: data.frequency,
        sample_rate: data.sample_rate,
        peak_db: data.peak_db,
        squelch_open: data.squelch_open,
        peaks: data.peaks || []
      });
      recordVfoActivity(data);
      if (Date.now() - lastActivityRefresh > 2500) {
        lastActivityRefresh = Date.now();
        loadActivity();
        loadAlerts();
      }
    } catch (err) {
      els.receiverStatus.textContent = `Frame failed: ${err.message}`;
    }
  }

  async function receiverAudioLoop(){
    try {
      const data = await api.receiverAudio(receiverAudioPayload());
      if (!data.ok) throw new Error(data.error || 'demodulation failed');
      const samples = data.audio || [];
      if (!samples.length) throw new Error('demodulator returned no audio');
      const rate = data.audio_rate || 48000;
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: rate });
      const buffer = audioCtx.createBuffer(1, samples.length, rate);
      const channel = buffer.getChannelData(0);
      const volume = (Number(document.getElementById('rxVolume').value) || 70) / 100;
      samples.forEach((sample, index) => {
        channel[index] = Math.max(-1, Math.min(1, Number(sample) || 0)) * volume;
      });
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(audioCtx.destination);
      audioNextTime = Math.max(audioNextTime, audioCtx.currentTime + 0.02);
      source.start(audioNextTime);
      audioNextTime += buffer.duration;
      const queued = Math.max(0, audioNextTime - audioCtx.currentTime);
      els.audioStatus.textContent = `Playing ${String(data.mode || '').toUpperCase()} at ${data.frequency} Hz - ${Number(data.duration_sec || buffer.duration).toFixed(2)}s chunk, ${queued.toFixed(2)}s queued`;
      els.receiverOutput.textContent = pretty({
        mode: data.mode,
        frequency: data.frequency,
        sample_rate: data.sample_rate,
        audio_rate: data.audio_rate,
        audio_samples: samples.length,
        duration_sec: data.duration_sec,
        queued_sec: queued
      });
    } catch (err) {
      stopAudio();
      els.audioStatus.textContent = `Audio failed: ${err.message}`;
      els.receiverOutput.textContent = err.message;
    }
  }

  async function loadBookmarks(){
    if (!els.bookmarkList) return;
    try {
      const params = {};
      if (els.bookmarkSearch && els.bookmarkSearch.value.trim()) params.q = els.bookmarkSearch.value.trim();
      if (els.bookmarkCategory && els.bookmarkCategory.value) params.category = els.bookmarkCategory.value;
      const data = await api.receiverBookmarks(params);
      const rows = data.bookmarks || [];
      if (els.bookmarkCategory) {
        const selected = els.bookmarkCategory.value;
        const categories = data.categories || [];
        els.bookmarkCategory.innerHTML = '<option value="">All categories</option>' + categories.map(category => (
          `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`
        )).join('');
        els.bookmarkCategory.value = categories.includes(selected) ? selected : '';
      }
      els.bookmarkList.innerHTML = rows.length ? rows.map((item) => (
        `<div class="capture-row"><strong>${escapeHtml(item.label)}</strong><span>${item.frequency} Hz</span><span>${escapeHtml(item.category || 'general')}</span><span>${escapeHtml(item.mode || 'nfm')}</span><button data-tune-bookmark="${item.frequency}" data-mode="${escapeHtml(item.mode || 'nfm')}">Tune</button><button data-delete-bookmark="${escapeHtml(item.id)}">Delete</button></div>`
      )).join('') : '<div class="empty">No bookmarks saved.</div>';
    } catch (err) {
      els.bookmarkList.innerHTML = `<div class="empty">Bookmark load failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function importBookmarks(){
    if (!els.bookmarkList) return;
    els.bookmarkList.innerHTML = '<div class="empty">Importing bookmarks...</div>';
    try {
      const payload = await readJsonFile('bookmarkImportFile');
      const result = await api.receiverBookmarksImport(payload);
      els.bookmarkList.innerHTML = `<div class="empty">Imported ${Number(result.imported || 0)} bookmarks.</div>`;
      await loadBookmarks();
    } catch (err) {
      els.bookmarkList.innerHTML = `<div class="empty">Bookmark import failed: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function loadScanPlans(){
    if (!els.scanPlanSelect) return;
    try {
      const plans = await api.scanPlans();
      els.scanPlanSelect.innerHTML = Object.keys(plans).map(key => (
        `<option value="${escapeHtml(key)}">${escapeHtml(plans[key].label || key)}</option>`
      )).join('');
      els.scanPlanSelect._plans = plans;
    } catch (err) {
      els.scanPlanSelect.innerHTML = '<option value="">Scan plans unavailable</option>';
      if (els.scanPlanOutput) els.scanPlanOutput.textContent = `Scan plan load failed: ${err.message}`;
    }
  }

  async function runScanPlan(){
    if (!els.scanPlanSelect || !els.scanPlanOutput) return;
    const plans = els.scanPlanSelect._plans || {};
    const key = els.scanPlanSelect.value;
    const plan = plans[key];
    if (!plan) {
      els.scanPlanOutput.textContent = 'Choose a scan plan first.';
      return;
    }
    const results = [];
    els.scanPlanOutput.textContent = `Running ${plan.label || key}...`;
    for (const range of (plan.ranges || [])) {
      document.getElementById('scanStart').value = String(range.start);
      document.getElementById('scanStop').value = String(range.stop);
      document.getElementById('scanThreshold').value = String(range.threshold_db == null ? -60 : range.threshold_db);
      if (range.mode || plan.mode) document.getElementById('rxMode').value = range.mode || plan.mode;
      if (plan.sample_rate) document.getElementById('rxSampleRate').value = String(plan.sample_rate);
      try {
        const data = await api.receiverScan({
          start: Number(range.start),
          stop: Number(range.stop),
          threshold_db: Number(range.threshold_db == null ? -60 : range.threshold_db),
          save_hits: range.save_hits !== false,
          mode: range.mode || plan.mode || document.getElementById('rxMode').value || 'nfm',
          sample_rate: Number(plan.sample_rate || numeric('rxSampleRate') || 2000000)
        });
        results.push({ range: range.label || `${range.start}-${range.stop}`, hits: data.hits || [], saved: data.saved || [] });
        els.scanPlanOutput.textContent = pretty(results);
      } catch (err) {
        results.push({ range: range.label || `${range.start}-${range.stop}`, error: err.message });
        els.scanPlanOutput.textContent = pretty(results);
      }
    }
    await loadBookmarks();
    await loadActivity();
  }

  function renderDecoderStatus(data){
    if (!els.decoderStatus) return;
    const decoders = data.decoders || {};
    dashboardState.decoderTotal = Object.keys(decoders).length;
    dashboardState.decoderReady = Object.keys(decoders).filter(key => decoders[key] && decoders[key].available).length;
    renderOperatorOverview();
    const rows = Object.keys(decoders).map(key => {
      const item = decoders[key];
      return `<div class="capture-row decoder-row ${item.available ? 'clear' : 'encrypted'}">
        <strong>${escapeHtml(item.label || key)}</strong>
        <span>${item.available ? 'available' : 'missing'}</span>
        <span>${escapeHtml(item.tool || '')}</span>
        <span>${escapeHtml((item.modes || []).join(', '))}</span>
        <span>${escapeHtml(item.path || item.notes || '')}</span>
      </div>`;
    });
    els.decoderStatus.innerHTML = rows.length ? rows.join('') : '<div class="empty">No decoder status available.</div>';
  }

  function renderDecoderEvents(data){
    if (!els.decoderEvents) return;
    const rows = data.events || [];
    els.decoderEvents.innerHTML = rows.length ? rows.map(item => (
      `<div class="capture-row decoder-row ${item.encrypted ? 'encrypted' : 'clear'}">
        <strong>${escapeHtml(item.decoder || '')}</strong>
        <span>${item.frequency || ''} Hz</span>
        <span>${escapeHtml(item.status || '')}</span>
        <span>${escapeHtml(item.capcode || item.station || item.program_id || '')}</span>
        <span>${escapeHtml(item.message || item.radiotext || item.text || '')}</span>
      </div>`
    )).join('') : '<div class="empty">No decoder events yet.</div>';
  }

  async function loadDecoders(){
    if (!els.decoderStatus) return;
    try {
      const [status, events] = await Promise.all([
        api.decoderStatus(),
        api.decoderEvents({
          decoder: document.getElementById('decoderType') && document.getElementById('decoderType').value,
          q: document.getElementById('decoderEventSearch') && document.getElementById('decoderEventSearch').value.trim()
        })
      ]);
      renderDecoderStatus(status);
      renderDecoderEvents(events);
    } catch (err) {
      els.decoderStatus.innerHTML = `<div class="empty">Decoder status failed: ${escapeHtml(err.message)}</div>`;
      if (els.decoderEvents) els.decoderEvents.innerHTML = '<div class="empty">Decoder events unavailable.</div>';
    }
  }

  async function planDecoder(){
    if (!els.decoderPlanOutput) return;
    const frequency = numeric('decoderFrequency') || numeric('rxFrequency') || 152480000;
    const mode = document.getElementById('decoderMode').value || document.getElementById('rxMode').value || 'nfm';
    els.decoderPlanOutput.textContent = 'Building decoder plan...';
    try {
      const plan = await api.decoderPlan({
        decoder: document.getElementById('decoderType').value,
        frequency,
        mode,
        sample_rate: numeric('rxSampleRate') || 2000000,
        audio_rate: 48000
      });
      els.decoderPlanOutput.textContent = pretty(plan);
      await loadDecoders();
    } catch (err) {
      els.decoderPlanOutput.textContent = `Decoder plan failed: ${err.message}`;
    }
  }

  async function runReceiverScan(){
    if (!els.scanOutput) return;
    els.scanOutput.textContent = 'Scanning...';
    try {
      const data = await api.receiverScan({
        start: numeric('scanStart') || 88000000,
        stop: numeric('scanStop') || 108000000,
        threshold_db: numeric('scanThreshold') || -50,
        save_hits: document.getElementById('scanSave').value === '1',
        mode: document.getElementById('rxMode').value || 'nfm',
        sample_rate: numeric('rxSampleRate') || 2000000
      });
      els.scanOutput.textContent = pretty({
        ok: data.ok,
        hits: data.hits || [],
        saved: data.saved || [],
        error: data.error || ''
      });
      await loadBookmarks();
    } catch (err) {
      els.scanOutput.textContent = `Scan failed: ${err.message}`;
    }
  }

  function renderTrunkProfiles(rows){
    if (!els.trunkProfileSelect || !els.trunkProfiles) return;
    els.trunkProfileSelect.innerHTML = rows.length
      ? rows.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} - ${escapeHtml(item.protocol || '')} ${item.control_channel || ''}</option>`).join('')
      : '<option value="">No trunking profiles saved</option>';
    els.trunkProfiles.innerHTML = rows.length ? rows.map(item => (
      `<div class="capture-row"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.protocol || '')}</span><span>${item.control_channel} Hz</span><span>${escapeHtml(item.decoder || '')}</span><button data-delete-trunk-profile="${escapeHtml(item.id)}">Delete</button></div>`
    )).join('') : '<div class="empty">No trunking profiles saved.</div>';
  }

  function renderTrunkEvents(rows){
    if (!els.trunkEvents) return;
    els.trunkEvents.innerHTML = rows.length ? rows.map(item => {
      const status = item.encrypted ? 'encrypted - playback blocked' : (item.status || 'decoded');
      const className = item.encrypted ? 'capture-row trunk-event encrypted' : 'capture-row trunk-event clear';
      const talkgroup = item.talkgroup_label ? `${item.talkgroup} ${item.talkgroup_label}` : (item.talkgroup || '-');
      const source = item.source_label ? `${item.source} ${item.source_label}` : (item.source || '-');
      return `<div class="${className}"><strong>${escapeHtml(status)}</strong><span>${escapeHtml(item.protocol || '')}</span><span>${item.frequency || ''} Hz</span><span>TG ${escapeHtml(talkgroup)}</span><span>SRC ${escapeHtml(source)}</span><span>${escapeHtml(item.message || '')}</span></div>`;
    }).join('') : '<div class="empty">No trunking events logged.</div>';
  }

  function trunkEventParams(){
    const params = {};
    const tg = document.getElementById('trunkTalkgroupFilter') && document.getElementById('trunkTalkgroupFilter').value.trim();
    const src = document.getElementById('trunkSourceFilter') && document.getElementById('trunkSourceFilter').value.trim();
    const enc = document.getElementById('trunkEncryptedFilter') && document.getElementById('trunkEncryptedFilter').value;
    const query = document.getElementById('trunkEventFilter') && document.getElementById('trunkEventFilter').value.trim();
    if (tg) params.talkgroup = tg;
    if (src) params.source = src;
    if (enc !== '') params.encrypted = enc;
    if (query) params.q = query;
    return params;
  }

  function renderTrunkSummary(summary){
    if (!els.trunkSummary) return;
    const totals = summary || {};
    const talkgroups = totals.talkgroups || [];
    const sources = totals.sources || [];
    const statRows = [
      `<article class="tile"><span>Total Events</span><strong>${Number(totals.total_events || 0)}</strong></article>`,
      `<article class="tile"><span>Clear Voice</span><strong>${Number(totals.clear_events || 0)}</strong></article>`,
      `<article class="tile"><span>Encrypted</span><strong>${Number(totals.encrypted_events || 0)}</strong></article>`
    ].join('');
    const talkgroupRows = talkgroups.slice(0, 8).map(item => (
      `<div class="capture-row trunk-summary-row"><strong>TG ${escapeHtml(item.talkgroup)}</strong><span>${item.events} events</span><span>${item.clear} clear</span><span>${item.encrypted} encrypted</span><span>${item.last_frequency || ''} Hz</span></div>`
    )).join('');
    const sourceRows = sources.slice(0, 6).map(item => (
      `<div class="capture-row trunk-summary-row"><strong>SRC ${escapeHtml(item.source)}</strong><span>${item.events} events</span><span>${item.encrypted} encrypted</span><span>TG ${escapeHtml(item.last_talkgroup || '-')}</span><span></span></div>`
    )).join('');
    els.trunkSummary.innerHTML = `<div class="grid">${statRows}</div>${talkgroupRows || '<div class="empty">No talkgroup activity yet.</div>'}${sourceRows}`;
  }

  async function loadTrunking(){
    if (!els.trunkStatus) return;
    try {
      const [agreement, profiles, status, events, summary] = await Promise.all([
        api.trunkingAgreement(),
        api.trunkingProfiles(),
        api.trunkingStatus(),
        api.trunkingEvents(trunkEventParams()),
        api.trunkingSummary()
      ]);
      const accepted = agreement.agreement && agreement.agreement.accepted;
      els.trunkAgreementStatus.textContent = accepted
        ? `Accepted by ${agreement.agreement.operator || 'operator'}`
        : 'Agreement has not been accepted.';
      renderTrunkProfiles(profiles.profiles || []);
      renderTrunkEvents(events.events || []);
      renderTrunkSummary(summary.summary || {});
      els.trunkStatus.textContent = status.running
        ? `Running ${status.profile && status.profile.name ? status.profile.name : 'profile'} (${status.decoder_state})`
        : 'Stopped';
      if (els.trunkProcessStatus) {
        const process = status.process || {};
        els.trunkProcessStatus.textContent = process.running
          ? `Decoder process running: ${process.engine || 'engine'} pid ${process.pid}`
          : `Decoder process stopped${process.error ? `: ${process.error}` : '.'}`;
      }
      if (els.trunkDecoderStatus) {
        els.trunkDecoderStatus.textContent = pretty({
          engines: status.decoder_tools || {},
          active_plan: status.decoder_plan || null
        });
      }
    } catch (err) {
      els.trunkStatus.textContent = `Trunking backend unavailable: ${err.message}`;
      if (els.trunkProcessStatus) {
        els.trunkProcessStatus.textContent = 'Decoder process status unavailable.';
      }
      if (els.trunkDecoderStatus) {
        els.trunkDecoderStatus.textContent = `Decoder engine status unavailable: ${err.message}`;
      }
    }
  }

  async function acceptTrunkAgreement(){
    els.trunkAgreementStatus.textContent = 'Saving agreement...';
    try {
      const data = await api.trunkingAcceptAgreement({
        operator: document.getElementById('trunkOperator').value,
        organization: document.getElementById('trunkOrganization').value,
        reference: document.getElementById('trunkReference').value
      });
      els.trunkAgreementStatus.textContent = `Accepted by ${data.agreement.operator}`;
      await loadTrunking();
    } catch (err) {
      els.trunkAgreementStatus.textContent = `Agreement failed: ${err.message}`;
    }
  }

  async function addTrunkProfile(){
    els.trunkStatus.textContent = 'Saving trunking profile...';
    try {
      await api.trunkingAddProfile({
        name: document.getElementById('trunkProfileName').value,
        protocol: document.getElementById('trunkProtocol').value,
        control_channel: numeric('trunkControlChannel'),
        voice_channels: csvNumbers('trunkVoiceChannels'),
        talkgroups_allow: csvNumbers('trunkAllowTalkgroups'),
        talkgroups_block: csvNumbers('trunkBlockTalkgroups')
      });
      await loadTrunking();
    } catch (err) {
      els.trunkStatus.textContent = `Profile failed: ${err.message}`;
    }
  }

  async function importTrunkProfiles(){
    els.trunkStatus.textContent = 'Importing trunking profiles...';
    try {
      const payload = await readJsonFile('trunkProfileImportFile');
      const result = await api.trunkingProfilesImport(payload);
      els.trunkStatus.textContent = `Imported ${result.imported || 0} profiles.`;
      await loadTrunking();
    } catch (err) {
      els.trunkStatus.textContent = `Profile import failed: ${err.message}`;
    }
  }

  async function startTrunking(){
    const profileId = els.trunkProfileSelect && els.trunkProfileSelect.value;
    if (!profileId) {
      els.trunkStatus.textContent = 'Create or select a trunking profile first.';
      return;
    }
    els.trunkStatus.textContent = 'Starting trunking session...';
    try {
      const data = await api.trunkingStart({ profile_id: profileId });
      els.trunkStatus.textContent = data.running ? `Running ${data.profile.name}` : 'Stopped';
      await loadTrunking();
    } catch (err) {
      els.trunkStatus.textContent = `Start blocked: ${err.message}`;
    }
  }

  async function stopTrunking(){
    try {
      await api.trunkingStop();
      await loadTrunking();
    } catch (err) {
      els.trunkStatus.textContent = `Stop failed: ${err.message}`;
    }
  }

  async function saveTrunkAlias(){
    try {
      await api.trunkingAliasUpsert({
        kind: document.getElementById('trunkAliasKind').value,
        key: document.getElementById('trunkAliasKey').value,
        label: document.getElementById('trunkAliasLabel').value,
        color: document.getElementById('trunkAliasColor').value
      });
      await loadTrunking();
    } catch (err) {
      els.trunkStatus.textContent = `Alias failed: ${err.message}`;
    }
  }

  async function importTrunkAliases(){
    els.trunkStatus.textContent = 'Importing trunking aliases...';
    try {
      const payload = await readJsonFile('trunkAliasImportFile');
      const result = await api.trunkingAliasesImport(payload);
      els.trunkStatus.textContent = `Imported ${result.imported || 0} aliases.`;
      await loadTrunking();
    } catch (err) {
      els.trunkStatus.textContent = `Alias import failed: ${err.message}`;
    }
  }

  function startAudio(){
    stopAudio();
    els.audioStatus.textContent = 'Starting receiver...';
    audioNextTime = 0;
    api.receiverStart(receiverPayload()).then(() => {
      receiverFrameLoop();
      receiverFrameTimer = setInterval(receiverFrameLoop, 700);
      receiverAudioLoop();
      audioTimer = setInterval(receiverAudioLoop, 450);
    }).catch((err) => {
      els.audioStatus.textContent = `Receiver failed: ${err.message}`;
    });
  }

  function stopAudio(){
    if (audioTimer) {
      clearInterval(audioTimer);
      audioTimer = null;
    }
    if (receiverFrameTimer) {
      clearInterval(receiverFrameTimer);
      receiverFrameTimer = null;
    }
    api.receiverStop().catch(() => {});
    els.audioStatus.textContent = 'Idle';
    if (els.receiverStatus) els.receiverStatus.textContent = 'Idle';
  }

  async function runSweep(){
    els.sweepOutput.textContent = 'Running sweep...';
    try {
      const data = await api.sweep({
        start: numeric('sweepStart'),
        stop: numeric('sweepStop'),
        bin_width: numeric('sweepBin'),
        dwell_ms: numeric('sweepDwell')
      });
      els.sweepOutput.textContent = JSON.stringify(data.rows || [], null, 2);
    } catch (err) {
      els.sweepOutput.textContent = `Sweep failed: ${err.message}`;
    }
  }

  async function runCapture(){
    els.captureStatus.textContent = 'Capturing IQ...';
    try {
      const data = await api.capture({
        frequency: numeric('captureFrequency'),
        sample_rate: numeric('captureSampleRate'),
        duration_sec: numeric('captureDuration'),
        lna_gain: numeric('captureLna'),
        vga_gain: 20
      });
      els.captureStatus.textContent = data.ok ? `Capture saved: ${data.filename}` : `Capture failed: ${data.error || 'unknown error'}`;
      await loadCaptures();
    } catch (err) {
      els.captureStatus.textContent = `Capture failed: ${err.message}`;
    }
  }

  function stopWaterfall(){
    if (waterfallTimer) {
      clearInterval(waterfallTimer);
      waterfallTimer = null;
    }
    if (socket && !socketStub) socket.emit('stop_waterfall');
    els.waterfallStatus.textContent = 'Idle';
  }

  async function pollWaterfall(){
    try {
      const data = await api.waterfallRow({
        fft_size: numeric('settingFft') || 256,
        frequency: numeric('captureFrequency') || 2437000000,
        sample_rate: numeric('captureSampleRate') || 20000000
      });
      waterfall.push(data.row || []);
      els.waterfallStatus.textContent = 'Streaming';
    } catch (err) {
      stopWaterfall();
      els.waterfallStatus.textContent = `Waterfall failed: ${err.message}`;
    }
  }

  function startWaterfall(){
    stopWaterfall();
    waterfall.clear();
    els.waterfallStatus.textContent = 'Starting stream...';
    pollWaterfall();
    waterfallTimer = setInterval(pollWaterfall, 700);
  }

  function loadSettings(){
    try {
      const saved = JSON.parse(localStorage.getItem(settingsKey) || '{}');
      if (saved.fft) document.getElementById('settingFft').value = saved.fft;
      if (saved.floor) document.getElementById('settingFloor').value = saved.floor;
      if (saved.theme) document.getElementById('settingTheme').value = saved.theme;
    } catch {}
  }

  function saveSettings(){
    localStorage.setItem(settingsKey, JSON.stringify({
      fft: numeric('settingFft'),
      floor: numeric('settingFloor'),
      theme: document.getElementById('settingTheme').value
    }));
    els.settingsStatus.textContent = 'Saved';
  }

  document.querySelectorAll('.tab').forEach(button => {
    button.addEventListener('click', () => {
      activateTab(button.dataset.tab);
    });
  });

  document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-open-tab]');
    if (!target) return;
    activateTab(target.getAttribute('data-open-tab'));
  });

  document.getElementById('refreshInfo').addEventListener('click', loadInfo);
  document.getElementById('connectHackrf').addEventListener('click', connectHackrf);
  document.getElementById('readinessHackrf').addEventListener('click', runReadiness);
  document.getElementById('testHackrf').addEventListener('click', testHackrf);
  document.getElementById('saveCustomPreset').addEventListener('click', saveCustomPreset);
  document.getElementById('importCustomPresets').addEventListener('click', importCustomPresets);
  document.getElementById('runSweep').addEventListener('click', runSweep);
  document.getElementById('runCapture').addEventListener('click', runCapture);
  document.getElementById('refreshSerial').addEventListener('click', loadSerialPorts);
  document.getElementById('probeSerial').addEventListener('click', probeSerial);
  document.getElementById('refreshDiagnostics').addEventListener('click', loadDiagnostics);
  document.getElementById('startAudio').addEventListener('click', startAudio);
  document.getElementById('stopAudio').addEventListener('click', stopAudio);
  document.getElementById('addVfo').addEventListener('click', addVfo);
  document.getElementById('exportVfos').addEventListener('click', exportVfos);
  document.getElementById('importVfos').addEventListener('click', importVfos);
  document.getElementById('refreshActivity').addEventListener('click', loadActivity);
  document.getElementById('refreshAlerts').addEventListener('click', loadAlerts);
  document.getElementById('saveAlertRule').addEventListener('click', saveAlertRule);
  document.getElementById('runScanPlan').addEventListener('click', runScanPlan);
  document.getElementById('runReceiverScan').addEventListener('click', runReceiverScan);
  document.getElementById('refreshBookmarks').addEventListener('click', loadBookmarks);
  document.getElementById('importBookmarks').addEventListener('click', importBookmarks);
  document.getElementById('refreshDecoders').addEventListener('click', loadDecoders);
  document.getElementById('planDecoder').addEventListener('click', planDecoder);
  document.getElementById('refreshTrunking').addEventListener('click', loadTrunking);
  document.getElementById('acceptTrunkAgreement').addEventListener('click', acceptTrunkAgreement);
  document.getElementById('addTrunkProfile').addEventListener('click', addTrunkProfile);
  document.getElementById('trunkImportProfiles').addEventListener('click', importTrunkProfiles);
  document.getElementById('trunkStart').addEventListener('click', startTrunking);
  document.getElementById('trunkStop').addEventListener('click', stopTrunking);
  document.getElementById('applyTrunkFilter').addEventListener('click', loadTrunking);
  document.getElementById('saveTrunkAlias').addEventListener('click', saveTrunkAlias);
  document.getElementById('trunkImportAliases').addEventListener('click', importTrunkAliases);
  if (els.trunkProfiles) {
    els.trunkProfiles.addEventListener('click', async (event) => {
      const del = event.target.closest('[data-delete-trunk-profile]');
      if (!del) return;
      await api.trunkingDeleteProfile(del.getAttribute('data-delete-trunk-profile'));
      await loadTrunking();
    });
  }
  if (els.bookmarkList) {
    els.bookmarkList.addEventListener('click', async (event) => {
      const tune = event.target.closest('[data-tune-bookmark]');
      if (tune) {
        document.getElementById('rxFrequency').value = tune.getAttribute('data-tune-bookmark') || '';
        document.getElementById('rxMode').value = tune.getAttribute('data-mode') || 'nfm';
        return;
      }
      const del = event.target.closest('[data-delete-bookmark]');
      if (del) {
        await api.receiverBookmarkDelete(del.getAttribute('data-delete-bookmark'));
        await loadBookmarks();
      }
    });
  }
  if (els.bookmarkSearch) {
    els.bookmarkSearch.addEventListener('input', () => loadBookmarks());
  }
  if (els.bookmarkCategory) {
    els.bookmarkCategory.addEventListener('change', () => loadBookmarks());
  }
  if (document.getElementById('decoderType')) {
    document.getElementById('decoderType').addEventListener('change', () => loadDecoders());
  }
  if (document.getElementById('decoderEventSearch')) {
    document.getElementById('decoderEventSearch').addEventListener('input', () => loadDecoders());
  }
  if (els.vfoList) {
    els.vfoList.addEventListener('click', (event) => {
      const select = event.target.closest('[data-select-vfo]');
      if (select) {
        selectVfo(select.getAttribute('data-select-vfo'));
        return;
      }
      const del = event.target.closest('[data-delete-vfo]');
      if (del) {
        deleteVfo(del.getAttribute('data-delete-vfo'));
      }
    });
  }
  if (els.activityList) {
    els.activityList.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-promote-activity]');
      if (!button) return;
      await promoteActivity(
        button.getAttribute('data-promote-activity'),
        button.getAttribute('data-frequency'),
        button.getAttribute('data-mode') || 'nfm'
      );
    });
  }
  if (els.alertRules) {
    els.alertRules.addEventListener('click', async (event) => {
      const del = event.target.closest('[data-delete-alert-rule]');
      if (!del) return;
      await api.receiverAlertRuleDelete(del.getAttribute('data-delete-alert-rule'));
      await loadAlerts();
    });
  }
  if (els.alertEvents) {
    els.alertEvents.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-promote-activity]');
      if (!button) return;
      await promoteActivity(
        button.getAttribute('data-promote-activity'),
        button.getAttribute('data-frequency'),
        button.getAttribute('data-mode') || 'nfm'
      );
    });
  }
  if (els.activityMinPeak) {
    els.activityMinPeak.addEventListener('change', () => loadActivity());
  }
  if (els.activitySearch) {
    els.activitySearch.addEventListener('input', () => loadActivity());
  }
  els.captureList.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-delete-capture]');
    if (!button) return;
    event.preventDefault();
    await api.deleteCapture(button.getAttribute('data-delete-capture'));
    await loadCaptures();
  });
  document.getElementById('saveSettings').addEventListener('click', saveSettings);
  document.getElementById('startWaterfall').addEventListener('click', startWaterfall);
  document.getElementById('stopWaterfall').addEventListener('click', stopWaterfall);
  if (els.presetList) {
    els.presetList.addEventListener('click', (event) => {
      const rangeButton = event.target.closest('[data-preset-start]');
      if (rangeButton) {
        applyPresetRange(rangeButton);
        return;
      }
      const button = event.target.closest('[data-preset-frequency]');
      if (!button) return;
      applyPresetDefaults(button);
      tuneFrequency(button.getAttribute('data-preset-frequency'), button.getAttribute('data-preset-mode') || 'nfm');
    });
  }
  if (els.presetSearch) {
    els.presetSearch.addEventListener('input', renderPresetNavigator);
  }
  if (els.presetModeFilter) {
    els.presetModeFilter.addEventListener('change', renderPresetNavigator);
  }
  if (els.presetCategoryFilter) {
    els.presetCategoryFilter.addEventListener('change', renderPresetNavigator);
  }
  if (els.quickStartList) {
    els.quickStartList.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-quick-start]');
      if (!button) return;
      await applyQuickStart(button.getAttribute('data-quick-start'));
    });
  }
  if (els.customPresetList) {
    els.customPresetList.addEventListener('click', async (event) => {
      const apply = event.target.closest('[data-apply-custom-preset]');
      if (apply) {
        applyCustomPreset(apply.getAttribute('data-apply-custom-preset'));
        return;
      }
      const del = event.target.closest('[data-delete-custom-preset]');
      if (del) {
        await api.customPresetDelete(del.getAttribute('data-delete-custom-preset'));
        await loadCustomPresets();
      }
    });
  }

  if (socket && !socketStub) {
    socket.on('waterfall_row', data => {
      waterfall.push(data.row || []);
      els.waterfallStatus.textContent = 'Streaming';
    });
    socket.on('waterfall_status', data => {
      els.waterfallStatus.textContent = data.running ? 'Streaming' : 'Idle';
    });
    socket.on('connect_error', () => {
      els.waterfallStatus.textContent = 'Socket unavailable';
    });
  } else {
    els.waterfallStatus.textContent = 'Ready';
  }

  ['rxFrequency', 'rxMode', 'rxBandwidth', 'rxStep'].forEach(id => {
    const control = document.getElementById(id);
    if (control) control.addEventListener('change', renderOperatorOverview);
  });

  loadSettings();
  loadVfos();
  loadInfo();
  loadCaptures();
  loadPresets();
  loadQuickStarts();
  loadCustomPresets();
  loadSerialPorts();
  loadBookmarks();
  loadScanPlans();
  loadActivity();
  loadAlerts();
  loadDecoders();
  loadTrunking();
  loadDiagnostics();
  renderOperatorOverview();
})();
