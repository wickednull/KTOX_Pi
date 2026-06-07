(function(){
  const api = window.SdrApi;
  const waterfall = new window.SdrWaterfall(document.getElementById('waterfallCanvas'));
  const receiverSpectrum = new window.SdrSpectrum(document.getElementById('receiverSpectrum'));
  const receiverWaterfall = new window.SdrWaterfall(document.getElementById('receiverWaterfall'));
  const socketPath = `${window.SdrApiBasePath ? window.SdrApiBasePath() : ''}/socket.io`;
  const socket = window.io ? window.io({ path: socketPath }) : null;
  const socketStub = !socket || !!socket.__ktoxStub;
  const settingsKey = 'ktox:sdr:settings';
  let waterfallTimer = null;
  let audioCtx = null;
  let audioTimer = null;
  let receiverFrameTimer = null;
  let audioNextTime = 0;

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
    settingsStatus: document.getElementById('settingsStatus'),
    connectStatus: document.getElementById('connectStatus'),
    usbStatus: document.getElementById('usbStatus'),
    serialPort: document.getElementById('serialPort'),
    serialBaud: document.getElementById('serialBaud'),
    serialStatus: document.getElementById('serialStatus'),
    audioStatus: document.getElementById('audioStatus'),
    receiverSignal: document.getElementById('receiverSignal'),
    receiverStatus: document.getElementById('receiverStatus'),
    receiverOutput: document.getElementById('receiverOutput')
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

  async function loadPresets(){
    let presets;
    try {
      presets = await api.presets();
    } catch (err) {
      presets = {
        ism: { label: 'ISM / Wi-Fi', frequencies: [2400000000, 2437000000, 2462000000] },
        adsb: { label: 'ADS-B', frequencies: [1090000000] },
        fm: { label: 'FM Broadcast', frequencies: [88100000, 98100000, 107900000] },
        weather: { label: 'NOAA Weather', frequencies: [162400000, 162550000] }
      };
    }
    els.presetList.innerHTML = Object.keys(presets).map(key => {
      const group = presets[key];
      return `<article><strong>${group.label}</strong><span>${(group.frequencies || []).length} presets</span></article>`;
    }).join('');
  }

  function numeric(id){
    return Number(document.getElementById(id).value);
  }

  function pretty(value){
    return JSON.stringify(value, null, 2);
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
    } catch (err) {
      els.receiverStatus.textContent = `Frame failed: ${err.message}`;
    }
  }

  async function receiverAudioLoop(){
    try {
      const data = await api.receiverAudio(receiverPayload());
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
      els.audioStatus.textContent = `Playing ${String(data.mode || '').toUpperCase()} at ${data.frequency} Hz`;
      els.receiverOutput.textContent = pretty({
        mode: data.mode,
        frequency: data.frequency,
        sample_rate: data.sample_rate,
        audio_rate: data.audio_rate,
        audio_samples: samples.length
      });
    } catch (err) {
      stopAudio();
      els.audioStatus.textContent = `Audio failed: ${err.message}`;
      els.receiverOutput.textContent = err.message;
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
      audioTimer = setInterval(receiverAudioLoop, 900);
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
      const tab = button.dataset.tab;
      document.querySelectorAll('.tab').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === tab));
    });
  });

  document.getElementById('refreshInfo').addEventListener('click', loadInfo);
  document.getElementById('connectHackrf').addEventListener('click', connectHackrf);
  document.getElementById('testHackrf').addEventListener('click', testHackrf);
  document.getElementById('runSweep').addEventListener('click', runSweep);
  document.getElementById('runCapture').addEventListener('click', runCapture);
  document.getElementById('refreshSerial').addEventListener('click', loadSerialPorts);
  document.getElementById('probeSerial').addEventListener('click', probeSerial);
  document.getElementById('startAudio').addEventListener('click', startAudio);
  document.getElementById('stopAudio').addEventListener('click', stopAudio);
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

  loadSettings();
  loadInfo();
  loadCaptures();
  loadPresets();
  loadSerialPorts();
})();
