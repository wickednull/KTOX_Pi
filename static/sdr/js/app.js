(function(){
  const api = window.SdrApi;
  const waterfall = new window.SdrWaterfall(document.getElementById('waterfallCanvas'));
  const socketPath = `${window.SdrApiBasePath ? window.SdrApiBasePath() : ''}/socket.io`;
  const socket = window.io ? window.io({ path: socketPath }) : null;
  const settingsKey = 'ktox:sdr:settings';

  const els = {
    deviceDot: document.getElementById('deviceDot'),
    deviceState: document.getElementById('deviceState'),
    deviceSerial: document.getElementById('deviceSerial'),
    boardValue: document.getElementById('boardValue'),
    firmwareValue: document.getElementById('firmwareValue'),
    captureCount: document.getElementById('captureCount'),
    captureBytes: document.getElementById('captureBytes'),
    presetList: document.getElementById('presetList'),
    sweepOutput: document.getElementById('sweepOutput'),
    captureStatus: document.getElementById('captureStatus'),
    captureList: document.getElementById('captureList'),
    waterfallStatus: document.getElementById('waterfallStatus'),
    settingsStatus: document.getElementById('settingsStatus')
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
    const ok = !!info.available;
    els.deviceDot.classList.toggle('ok', ok);
    els.deviceState.textContent = ok ? 'HackRF online' : 'HackRF unavailable';
    els.deviceSerial.textContent = ok ? (info.serial_number || 'serial unknown') : (info.error || 'not detected');
    els.boardValue.textContent = info.board || '-';
    els.firmwareValue.textContent = info.firmware || '-';
  }

  async function loadInfo(){
    try {
      setDevice(await api.info());
    } catch (err) {
      setDevice({ available: false, error: err.message });
    }
  }

  async function loadCaptures(){
    const data = await api.captures();
    const captures = data.captures || [];
    els.captureCount.textContent = String(captures.length);
    els.captureBytes.textContent = bytes(data.stats && data.stats.total_size);
    els.captureList.innerHTML = captures.length ? captures.map(item => (
      `<div class="capture-row"><strong>${item.filename}</strong><span>${item.frequency} Hz</span><span>${bytes(item.size)}</span><a href="${window.SdrApiUrl(`/api/hackrf/captures/${item.id}/download`)}">Download</a><button data-delete-capture="${item.id}">Delete</button></div>`
    )).join('') : '<div class="empty">No captures indexed.</div>';
  }

  async function loadPresets(){
    const presets = await api.presets();
    els.presetList.innerHTML = Object.keys(presets).map(key => {
      const group = presets[key];
      return `<article><strong>${group.label}</strong><span>${(group.frequencies || []).length} presets</span></article>`;
    }).join('');
  }

  function numeric(id){
    return Number(document.getElementById(id).value);
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
    els.captureStatus.textContent = 'Capture queued...';
    try {
      const data = await api.capture({
        frequency: numeric('captureFrequency'),
        sample_rate: numeric('captureSampleRate'),
        duration_sec: numeric('captureDuration'),
        lna_gain: numeric('captureLna'),
        vga_gain: 20
      });
      els.captureStatus.textContent = data.queued ? `Queued ${data.filename}` : 'Capture complete';
      setTimeout(loadCaptures, 1200);
    } catch (err) {
      els.captureStatus.textContent = `Capture failed: ${err.message}`;
    }
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
      const tab = button.dataset.tab;
      document.querySelectorAll('.tab').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === tab));
    });
  });

  document.getElementById('refreshInfo').addEventListener('click', loadInfo);
  document.getElementById('runSweep').addEventListener('click', runSweep);
  document.getElementById('runCapture').addEventListener('click', runCapture);
  els.captureList.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-delete-capture]');
    if (!button) return;
    event.preventDefault();
    await api.deleteCapture(button.getAttribute('data-delete-capture'));
    await loadCaptures();
  });
  document.getElementById('saveSettings').addEventListener('click', saveSettings);
  document.getElementById('startWaterfall').addEventListener('click', () => {
    waterfall.clear();
    if (socket) socket.emit('start_waterfall', { fft_size: numeric('settingFft') || 256 });
  });
  document.getElementById('stopWaterfall').addEventListener('click', () => {
    if (socket) socket.emit('stop_waterfall');
  });

  if (socket) {
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
  }

  loadSettings();
  loadInfo();
  loadCaptures().catch(() => {});
  loadPresets().catch(() => {});
})();
