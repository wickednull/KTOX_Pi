# SDR Live Receiver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first reliable KTOX SDR live receiver slice: receiver session state, HackRF-backed spectrum/waterfall frames, demodulated browser audio chunks, and a receiver-first UI.

**Architecture:** Add `sdr/receiver.py` as the focused session and DSP boundary between `services/sdr_server.py` and `sdr/device.py`. Keep first-release transport as stable HTTP polling while shaping APIs so WebSocket/SSE streaming can replace polling later. Preserve the static fallback page, but make all backend failures explicit in receiver status.

**Tech Stack:** Python stdlib, Flask/Flask-SocketIO already used by `services/sdr_server.py`, HackRF CLI tools, NumPy optional via `sdr/processing.py` and `sdr/demod.py`, browser Web Audio, plain HTML/CSS/JS.

---

## File Structure

- Create `sdr/receiver.py`: receiver configuration, validation, lifecycle state, frame generation, audio chunk generation, and receiver-level error summaries.
- Modify `services/sdr_server.py`: add `/api/receiver/start`, `/api/receiver/stop`, `/api/receiver/status`, `/api/receiver/frame`, and `/api/receiver/audio`; route legacy demod/waterfall endpoints through receiver helpers where practical.
- Modify `static/sdr/index.html`: make `Receiver` the first active workspace and add controls for frequency, step, sample rate, demod mode, bandwidth, squelch, gains, spectrum, waterfall, audio status, and diagnostics.
- Modify `static/sdr/js/api.js`: add receiver API methods.
- Modify `static/sdr/js/waterfall.js`: add a spectrum renderer or extend the canvas helper to support both line spectrum and scrolling waterfall.
- Modify `static/sdr/js/app.js`: replace the current one-off receiver/audio polling with receiver session start/stop/status/frame/audio loops.
- Modify `static/sdr/css/style.css`: layout receiver workspace without nested cards and keep controls dense but readable.
- Modify `tools/validate_sdr_suite.py`: no-hardware tests for receiver config validation, frame/audio routes, UI tokens, and API method wiring.
- Modify `payloads/utilities/auto_update.py`: add `sdr/receiver.py` to required SDR OTA files.
- Modify `scripts/install_sdr.sh` only if validation shows a missing dependency; the first receiver slice should avoid new external packages.

---

### Task 1: Receiver Session Core

**Files:**
- Create: `sdr/receiver.py`
- Modify: `tools/validate_sdr_suite.py`

- [ ] **Step 1: Write failing receiver validation checks**

Add this function to `tools/validate_sdr_suite.py` after `validate_device()`:

```python
def validate_receiver() -> None:
    from sdr.device import HackRFManager
    from sdr.receiver import ReceiverConfig, ReceiverSession

    manager = HackRFManager(runner=FakeRunner())
    config = ReceiverConfig.from_payload({
        "frequency": 162550000,
        "sample_rate": 2000000,
        "mode": "nfm",
        "fft_size": 256,
        "audio_rate": 48000,
        "sample_count": 4096,
        "lna_gain": 16,
        "vga_gain": 20,
        "squelch": -80,
        "bandwidth": 12500,
    })
    require(config.frequency == 162550000, "receiver config frequency mismatch")
    require(config.mode == "nfm", "receiver mode should normalize to lowercase")

    session = ReceiverSession(manager)
    status = session.start(config)
    require(status["running"] is True, "receiver should start")
    require(status["config"]["frequency"] == 162550000, "receiver status should include config")
    frame = session.frame()
    require(frame["ok"] is True, "receiver frame should succeed")
    require(len(frame["spectrum"]) == 256, "receiver spectrum size mismatch")
    require(len(frame["waterfall"]) == 256, "receiver waterfall size mismatch")
    audio = session.audio()
    require(audio["ok"] is True, "receiver audio should succeed")
    require(audio["audio"], "receiver audio should include samples")
    stopped = session.stop()
    require(stopped["running"] is False, "receiver should stop")
```

Add `validate_receiver` to the `checks` list immediately after `validate_device`.

- [ ] **Step 2: Run the failing check**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_receiver()"
```

Expected: fail with `ModuleNotFoundError: No module named 'sdr.receiver'`.

- [ ] **Step 3: Implement `sdr/receiver.py`**

Create `sdr/receiver.py` with:

```python
"""Receiver session model for the KTOX SDR Suite."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from sdr.demod import demodulate_audio
from sdr.device import HackRFManager
from sdr.processing import detect_peaks, normalize_power, power_spectrum, waterfall_row


SUPPORTED_MODES = {"nfm", "wfm", "fm", "am", "usb", "lsb", "cw", "raw"}


def _int_range(data: dict[str, Any], key: str, default: int, min_value: int, max_value: int) -> int:
    value = int(data.get(key, default))
    if value < min_value or value > max_value:
        raise ValueError(f"{key} out of range")
    return value


@dataclass
class ReceiverConfig:
    frequency: int = 162550000
    sample_rate: int = 2000000
    mode: str = "nfm"
    fft_size: int = 512
    audio_rate: int = 48000
    sample_count: int = 131072
    lna_gain: int = 16
    vga_gain: int = 20
    squelch: int = -90
    bandwidth: int = 12500

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ReceiverConfig":
        data = payload or {}
        mode = str(data.get("mode") or "nfm").lower()
        if mode not in SUPPORTED_MODES:
            raise ValueError("unsupported demodulation mode")
        return cls(
            frequency=_int_range(data, "frequency", 162550000, 1000000, 6000000000),
            sample_rate=_int_range(data, "sample_rate", 2000000, 1000000, 20000000),
            mode=mode,
            fft_size=_int_range(data, "fft_size", 512, 64, 4096),
            audio_rate=_int_range(data, "audio_rate", 48000, 8000, 96000),
            sample_count=_int_range(data, "sample_count", 131072, 4096, 1048576),
            lna_gain=_int_range(data, "lna_gain", 16, 0, 40),
            vga_gain=_int_range(data, "vga_gain", 20, 0, 62),
            squelch=_int_range(data, "squelch", -90, -140, 0),
            bandwidth=_int_range(data, "bandwidth", 12500, 100, 2000000),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReceiverSession:
    def __init__(self, manager: HackRFManager):
        self.manager = manager
        self.config = ReceiverConfig()
        self.running = False
        self.last_error = ""
        self.started_at = 0.0
        self.last_frame_at = 0.0
        self.last_audio_at = 0.0

    def start(self, config: ReceiverConfig) -> dict[str, Any]:
        self.config = config
        self.running = True
        self.last_error = ""
        self.started_at = time.time()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.manager.stop_active_process()
        self.running = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "config": self.config.as_dict(),
            "last_error": self.last_error,
            "started_at": self.started_at,
            "last_frame_at": self.last_frame_at,
            "last_audio_at": self.last_audio_at,
        }

    def _samples(self, sample_count: int | None = None) -> dict[str, Any]:
        cfg = self.config
        result = self.manager.read_iq_samples(
            cfg.frequency,
            sample_rate=cfg.sample_rate,
            sample_count=sample_count or max(cfg.fft_size, 4096),
            lna_gain=cfg.lna_gain,
            vga_gain=cfg.vga_gain,
        )
        if not result.get("ok"):
            self.last_error = str(result.get("error") or "RX sample read failed")
        return result

    def frame(self) -> dict[str, Any]:
        cfg = self.config
        result = self._samples(cfg.fft_size)
        if not result.get("ok"):
            return {"ok": False, "error": self.last_error, "status": self.status()}
        samples = result.get("samples", [])
        powers = power_spectrum(samples, fft_size=cfg.fft_size)
        peak_level = max(powers) if powers else -120.0
        self.last_frame_at = time.time()
        return {
            "ok": True,
            "status": self.status(),
            "frequency": cfg.frequency,
            "sample_rate": cfg.sample_rate,
            "spectrum": normalize_power(powers),
            "powers_db": powers,
            "waterfall": waterfall_row(samples, fft_size=cfg.fft_size),
            "peaks": detect_peaks(powers, threshold=max(cfg.squelch, peak_level - 20), max_peaks=8),
            "peak_db": peak_level,
            "squelch_open": peak_level >= cfg.squelch,
            "ts": self.last_frame_at,
        }

    def audio(self) -> dict[str, Any]:
        cfg = self.config
        result = self._samples(cfg.sample_count)
        if not result.get("ok"):
            return {"ok": False, "error": self.last_error, "status": self.status()}
        audio = demodulate_audio(result.get("samples", []), sample_rate=cfg.sample_rate, mode=cfg.mode, audio_rate=cfg.audio_rate)
        self.last_audio_at = time.time()
        return {
            "ok": True,
            "status": self.status(),
            "frequency": cfg.frequency,
            "sample_rate": cfg.sample_rate,
            **audio,
        }
```

- [ ] **Step 4: Run receiver validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_receiver(); print('validate_receiver passed')"
```

Expected: `validate_receiver passed`.

- [ ] **Step 5: Commit**

```bash
git add sdr/receiver.py tools/validate_sdr_suite.py
git commit -m "feat: add SDR receiver session core"
```

---

### Task 2: Receiver HTTP APIs

**Files:**
- Modify: `services/sdr_server.py`
- Modify: `tools/validate_sdr_suite.py`

- [ ] **Step 1: Write failing route checks**

In `validate_server()` in `tools/validate_sdr_suite.py`, after the serial ports assertion, add:

```python
        receiver_payload = {
            "frequency": 162550000,
            "sample_rate": 2000000,
            "mode": "nfm",
            "fft_size": 256,
            "sample_count": 4096,
            "lna_gain": 16,
            "vga_gain": 20,
            "squelch": -90,
            "bandwidth": 12500,
        }
        started = client.post("/api/receiver/start", data=json.dumps(receiver_payload), content_type="application/json")
        require(started.status_code == 200, "receiver start endpoint failed")
        require(started.get_json()["running"] is True, "receiver start should report running")
        require(client.get("/api/receiver/status").status_code == 200, "receiver status endpoint failed")
        frame = client.post("/api/receiver/frame", data=json.dumps({"fft_size": 256}), content_type="application/json")
        require(frame.status_code == 200, "receiver frame endpoint failed")
        require(frame.get_json()["spectrum"], "receiver frame should include spectrum")
        audio = client.post("/api/receiver/audio", data=json.dumps({"sample_count": 4096}), content_type="application/json")
        require(audio.status_code == 200, "receiver audio endpoint failed")
        require(audio.get_json()["audio"], "receiver audio should include samples")
        stopped = client.post("/api/receiver/stop")
        require(stopped.status_code == 200, "receiver stop endpoint failed")
        require(stopped.get_json()["running"] is False, "receiver stop should report stopped")
```

In `validate_integration()`, add:

```python
    require("/api/receiver/start" in server and "ReceiverSession" in server, "sdr_server.py must expose receiver session APIs")
```

- [ ] **Step 2: Run failing route validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_integration(); print('integration token check passed')"
```

Expected: fail with `sdr_server.py must expose receiver session APIs`.

- [ ] **Step 3: Import receiver helpers**

In `services/sdr_server.py`, inside the guarded imports, add:

```python
    from sdr.receiver import ReceiverConfig, ReceiverSession
```

- [ ] **Step 4: Create receiver session in `create_app()`**

After:

```python
    hackrf = manager or HackRFManager()
    db = database or CaptureDatabase(DB_PATH)
```

add:

```python
    receiver = ReceiverSession(hackrf)
```

- [ ] **Step 5: Add receiver routes**

After `serial_probe()` in `services/sdr_server.py`, add:

```python
    @app.post("/api/receiver/start")
    @app.post("/sdr/api/receiver/start")
    def receiver_start():
        try:
            config = ReceiverConfig.from_payload(request.get_json(silent=True) or {})
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(receiver.start(config) | {"ok": True})

    @app.post("/api/receiver/stop")
    @app.post("/sdr/api/receiver/stop")
    def receiver_stop():
        return jsonify(receiver.stop() | {"ok": True})

    @app.get("/api/receiver/status")
    @app.get("/sdr/api/receiver/status")
    def receiver_status():
        return jsonify(receiver.status() | {"ok": True})

    @app.post("/api/receiver/frame")
    @app.post("/sdr/api/receiver/frame")
    def receiver_frame():
        try:
            payload = request.get_json(silent=True) or {}
            if payload:
                receiver.start(ReceiverConfig.from_payload(receiver.config.as_dict() | payload))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = receiver.frame()
        return jsonify(result), 200 if result.get("ok") else 503

    @app.post("/api/receiver/audio")
    @app.post("/sdr/api/receiver/audio")
    def receiver_audio():
        try:
            payload = request.get_json(silent=True) or {}
            if payload:
                receiver.start(ReceiverConfig.from_payload(receiver.config.as_dict() | payload))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result = receiver.audio()
        return jsonify(result), 200 if result.get("ok") else 503
```

- [ ] **Step 6: Add static fallback receiver API responses**

In `StaticSdrHandler.do_GET()`, add `/api/receiver/status` and `/sdr/api/receiver/status` to the JSON fallback block and include:

```python
"running": False,
"config": {},
```

In `StaticSdrHandler.do_POST()`, add these paths to the 503 fallback set:

```python
"/api/receiver/start",
"/api/receiver/stop",
"/api/receiver/frame",
"/api/receiver/audio",
"/sdr/api/receiver/start",
"/sdr/api/receiver/stop",
"/sdr/api/receiver/frame",
"/sdr/api/receiver/audio",
```

- [ ] **Step 7: Run route validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_integration(); print('validate_integration passed')"
```

Expected: `validate_integration passed`.

If Flask is available on the machine running this plan, also run:

```bash
python3 tools/validate_sdr_suite.py
```

Expected: all `PASS ...` lines.

- [ ] **Step 8: Commit**

```bash
git add services/sdr_server.py tools/validate_sdr_suite.py
git commit -m "feat: expose SDR receiver session APIs"
```

---

### Task 3: Receiver Frontend API And Rendering Helpers

**Files:**
- Modify: `static/sdr/js/api.js`
- Modify: `static/sdr/js/waterfall.js`
- Modify: `tools/validate_sdr_suite.py`

- [ ] **Step 1: Add failing frontend API validation**

In `validate_integration()` after the existing `waterfallRow` assertion, add:

```python
    for token in ("receiverStart", "receiverStop", "receiverStatus", "receiverFrame", "receiverAudio"):
        require(token in sdr_api, f"SDR API client missing {token}")
    require("SdrSpectrum" in (ROOT / "static/sdr/js/waterfall.js").read_text(encoding="utf-8"), "SDR rendering helper must expose SdrSpectrum")
```

- [ ] **Step 2: Run failing validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_integration()"
```

Expected: fail with `SDR API client missing receiverStart`.

- [ ] **Step 3: Add receiver API methods**

In `static/sdr/js/api.js`, add methods to `window.SdrApi`:

```js
    receiverStart: (payload) => requestJson('/api/receiver/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverStop: () => requestJson('/api/receiver/stop', { method: 'POST' }),
    receiverStatus: () => requestJson('/api/receiver/status'),
    receiverFrame: (payload) => requestJson('/api/receiver/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
    receiverAudio: (payload) => requestJson('/api/receiver/audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }),
```

- [ ] **Step 4: Add spectrum renderer**

In `static/sdr/js/waterfall.js`, add this class before `window.SdrWaterfall = Waterfall;`:

```js
  class Spectrum {
    constructor(canvas){
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.width = canvas.width;
      this.height = canvas.height;
      this.clear();
    }

    clear(){
      this.ctx.fillStyle = '#020617';
      this.ctx.fillRect(0, 0, this.width, this.height);
      this.ctx.strokeStyle = 'rgba(148,163,184,0.18)';
      this.ctx.lineWidth = 1;
      for (let i = 1; i < 4; i += 1) {
        const y = (this.height / 4) * i;
        this.ctx.beginPath();
        this.ctx.moveTo(0, y);
        this.ctx.lineTo(this.width, y);
        this.ctx.stroke();
      }
    }

    draw(row, peaks){
      this.clear();
      const values = Array.isArray(row) ? row : [];
      if (!values.length) return;
      this.ctx.strokeStyle = '#22d3ee';
      this.ctx.lineWidth = 2;
      this.ctx.beginPath();
      values.forEach((value, index) => {
        const x = (index / Math.max(1, values.length - 1)) * this.width;
        const y = this.height - ((Math.max(0, Math.min(255, Number(value) || 0)) / 255) * this.height);
        if (index === 0) this.ctx.moveTo(x, y);
        else this.ctx.lineTo(x, y);
      });
      this.ctx.stroke();
      this.ctx.fillStyle = '#fecaca';
      (peaks || []).forEach((peak) => {
        const x = ((Number(peak.bin) || 0) / Math.max(1, values.length - 1)) * this.width;
        this.ctx.fillRect(x - 1, 0, 2, this.height);
      });
    }
  }

  window.SdrSpectrum = Spectrum;
```

- [ ] **Step 5: Run JS syntax and validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static/sdr/js/api.js
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static/sdr/js/waterfall.js
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_integration(); print('validate_integration passed')"
```

Expected: JS checks print no output and validation prints `validate_integration passed`.

- [ ] **Step 6: Commit**

```bash
git add static/sdr/js/api.js static/sdr/js/waterfall.js tools/validate_sdr_suite.py
git commit -m "feat: add SDR receiver frontend API helpers"
```

---

### Task 4: Receiver Workspace UI

**Files:**
- Modify: `static/sdr/index.html`
- Modify: `static/sdr/css/style.css`
- Modify: `static/sdr/js/app.js`
- Modify: `tools/validate_sdr_suite.py`

- [ ] **Step 1: Add failing UI token validation**

In `validate_static_assets()`, extend the token list with:

```python
"receiverSpectrum", "receiverWaterfall", "rxStep", "rxBandwidth", "rxSquelch", "receiverStatus"
```

In `validate_integration()`, add:

```python
    require("receiverStart" in sdr_app and "receiverFrameLoop" in sdr_app and "receiverAudioLoop" in sdr_app, "SDR app must run receiver session loops")
```

- [ ] **Step 2: Run failing validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_static_assets()"
```

Expected: fail with a missing receiver UI token.

- [ ] **Step 3: Replace receiver section markup**

In `static/sdr/index.html`, replace the current `<section id="receiver" ...>` with:

```html
      <section id="receiver" class="panel active">
        <div class="receiver-toolbar">
          <label>Frequency Hz<input id="rxFrequency" type="number" value="162550000"></label>
          <label>Step Hz<input id="rxStep" type="number" value="12500"></label>
          <label>Sample Rate<select id="rxSampleRate">
            <option value="2000000">2 MSPS</option>
            <option value="4000000">4 MSPS</option>
            <option value="8000000">8 MSPS</option>
            <option value="10000000">10 MSPS</option>
            <option value="20000000">20 MSPS</option>
          </select></label>
          <label>Mode<select id="rxMode">
            <option value="nfm">NFM</option>
            <option value="wfm">WFM</option>
            <option value="am">AM</option>
            <option value="usb">USB</option>
            <option value="lsb">LSB</option>
            <option value="cw">CW</option>
            <option value="raw">RAW</option>
          </select></label>
          <label>Bandwidth Hz<input id="rxBandwidth" type="number" value="12500"></label>
          <label>Squelch dB<input id="rxSquelch" type="number" value="-90"></label>
          <label>LNA<input id="rxLna" type="number" value="16"></label>
          <label>VGA<input id="rxVga" type="number" value="20"></label>
          <label>Volume<input id="rxVolume" type="range" min="0" max="100" value="70"></label>
          <div class="actions">
            <button id="startAudio" class="primary">Listen</button>
            <button id="stopAudio">Stop</button>
          </div>
        </div>
        <div class="receiver-grid">
          <section class="receiver-plot">
            <div class="plot-head"><strong>Spectrum</strong><span id="receiverSignal">No signal</span></div>
            <canvas id="receiverSpectrum" width="1100" height="240"></canvas>
          </section>
          <section class="receiver-plot">
            <div class="plot-head"><strong>Waterfall</strong><span id="receiverStatus">Idle</span></div>
            <canvas id="receiverWaterfall" width="1100" height="420"></canvas>
          </section>
        </div>
        <pre id="receiverOutput" class="output compact">Receiver status will appear here.</pre>
      </section>
```

Remove `active` from the dashboard section so the receiver is the first visible panel.

- [ ] **Step 4: Add receiver layout CSS**

Append to `static/sdr/css/style.css`:

```css
.receiver-toolbar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.7rem;
  align-items: end;
  margin-bottom: 1rem;
}

.receiver-grid {
  display: grid;
  gap: 0.8rem;
}

.receiver-plot {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  overflow: hidden;
}

.plot-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.7rem 0.9rem;
  border-bottom: 1px solid var(--border);
}

#receiverSpectrum {
  height: 240px;
}

#receiverWaterfall {
  height: min(46vh, 420px);
}
```

- [ ] **Step 5: Replace receiver JS loops**

In `static/sdr/js/app.js`:

1. Add new top-level instances after `waterfall`:

```js
  const receiverSpectrum = new window.SdrSpectrum(document.getElementById('receiverSpectrum'));
  const receiverWaterfall = new window.SdrWaterfall(document.getElementById('receiverWaterfall'));
```

2. Add state:

```js
  let receiverFrameTimer = null;
```

3. Add `receiverSignal` to `els`:

```js
    receiverSignal: document.getElementById('receiverSignal'),
```

4. Replace `receiverPayload()` with:

```js
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
```

5. Add frame loop:

```js
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
```

6. Rename `playDemodChunk()` to `receiverAudioLoop()` and replace `api.demodulate(receiverPayload())` with:

```js
      const data = await api.receiverAudio(receiverPayload());
```

7. Replace `startAudio()` with:

```js
  async function startAudio(){
    stopAudio();
    els.audioStatus.textContent = 'Starting receiver...';
    audioNextTime = 0;
    await api.receiverStart(receiverPayload());
    receiverFrameLoop();
    receiverFrameTimer = setInterval(receiverFrameLoop, 700);
    receiverAudioLoop();
    audioTimer = setInterval(receiverAudioLoop, 900);
  }
```

8. Update `stopAudio()`:

```js
  async function stopAudio(){
    if (audioTimer) {
      clearInterval(audioTimer);
      audioTimer = null;
    }
    if (receiverFrameTimer) {
      clearInterval(receiverFrameTimer);
      receiverFrameTimer = null;
    }
    try { await api.receiverStop(); } catch {}
    els.audioStatus.textContent = 'Idle';
    if (els.receiverStatus) els.receiverStatus.textContent = 'Idle';
  }
```

- [ ] **Step 6: Run JS and focused validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static/sdr/js/app.js
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_static_assets(); v.validate_integration(); print('ui validation passed')"
```

Expected: JS check prints no output and validation prints `ui validation passed`.

- [ ] **Step 7: Commit**

```bash
git add static/sdr/index.html static/sdr/css/style.css static/sdr/js/app.js tools/validate_sdr_suite.py
git commit -m "feat: build SDR receiver workspace UI"
```

---

### Task 5: OTA And Installer Awareness

**Files:**
- Modify: `payloads/utilities/auto_update.py`
- Modify: `tools/validate_sdr_suite.py`
- Optional Modify: `README.md`

- [ ] **Step 1: Add failing OTA validation for receiver files**

In `validate_integration()`, add `sdr/receiver.py` and `sdr/demod.py` to the OTA required loop by changing:

```python
    for required in ("services/sdr_server.py", "sdr/device.py", "static/sdr/index.html", "tools/validate_sdr_suite.py", "scripts/install_sdr.sh"):
```

to:

```python
    for required in ("services/sdr_server.py", "sdr/device.py", "sdr/demod.py", "sdr/receiver.py", "static/sdr/index.html", "tools/validate_sdr_suite.py", "scripts/install_sdr.sh"):
```

- [ ] **Step 2: Run failing integration validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_integration()"
```

Expected: fail if `payloads/utilities/auto_update.py` does not include `sdr/receiver.py`.

- [ ] **Step 3: Update OTA required files**

In `payloads/utilities/auto_update.py`, find `REQUIRED_SDR_FILES` and make sure it includes:

```python
"sdr/demod.py",
"sdr/receiver.py",
```

- [ ] **Step 4: Update docs if needed**

If `README.md` has an SDR section that still describes the SDR Suite as mainly diagnostics, update it to say:

```markdown
The SDR Suite runs as `ktox-sdr` on port `8081` and provides a HackRF-focused browser receiver with receiver controls, spectrum/waterfall frames, demodulated browser audio, captures, and diagnostics.
```

- [ ] **Step 5: Run validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_integration(); print('validate_integration passed')"
```

Expected: `validate_integration passed`.

- [ ] **Step 6: Commit**

```bash
git add payloads/utilities/auto_update.py tools/validate_sdr_suite.py README.md
git commit -m "chore: include SDR receiver files in OTA validation"
```

---

### Task 6: End-To-End Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run local no-bytecode syntax checks**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -c "import pathlib; files=['sdr/demod.py','sdr/device.py','sdr/processing.py','sdr/receiver.py','services/sdr_server.py','tools/validate_sdr_suite.py']; [compile(pathlib.Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]; print('python syntax passed')"
```

Expected: `python syntax passed`.

- [ ] **Step 2: Run JS syntax checks**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static/sdr/js/api.js
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static/sdr/js/app.js
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static/sdr/js/waterfall.js
```

Expected: no output from all three commands.

- [ ] **Step 3: Run focused validation**

Run:

```powershell
& 'C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import importlib.util; spec=importlib.util.spec_from_file_location('v','tools/validate_sdr_suite.py'); v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v); v.validate_processing(); v.validate_device(); v.validate_receiver(); v.validate_static_assets(); v.validate_integration(); print('focused validation passed')"
```

Expected: `focused validation passed`.

- [ ] **Step 4: Run fallback server smoke test**

Run:

```powershell
$py='C:\Users\wicke\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:KTOX_SDR_PORT='8097'
$proc=Start-Process -FilePath $py -ArgumentList @('-B','services/sdr_server.py') -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
try {
  $root=(Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8097/' -TimeoutSec 5)
  $status=(Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8097/api/receiver/status' -TimeoutSec 5)
  Write-Output "root=$($root.StatusCode) receiverStatus=$($status.StatusCode)"
} finally {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  Remove-Item Env:KTOX_SDR_PORT -ErrorAction SilentlyContinue
}
```

Expected: `root=200 receiverStatus=200`.

- [ ] **Step 5: Run on-device validation after OTA**

On the Pi/Kali device:

```bash
cd /root/KTOx
sudo bash scripts/install_sdr.sh
sudo systemctl restart ktox-webui
sudo systemctl restart ktox-sdr
curl -s -X POST http://127.0.0.1:8081/api/hackrf/connect
curl -s -X POST http://127.0.0.1:8081/api/hackrf/test -H 'Content-Type: application/json' -d '{"frequency":162550000,"sample_rate":2000000}'
curl -s -X POST http://127.0.0.1:8081/api/receiver/start -H 'Content-Type: application/json' -d '{"frequency":162550000,"sample_rate":2000000,"mode":"nfm"}'
curl -s -X POST http://127.0.0.1:8081/api/receiver/frame -H 'Content-Type: application/json' -d '{"fft_size":512}'
curl -s -X POST http://127.0.0.1:8081/api/receiver/audio -H 'Content-Type: application/json' -d '{"sample_count":131072}'
curl -s -X POST http://127.0.0.1:8081/api/receiver/stop
```

Expected:

- connect reports `connected: true`.
- test reports `ok: true`, or shows the exact failing layer.
- frame returns `ok: true` and non-empty `spectrum` and `waterfall`.
- audio returns `ok: true` and non-empty `audio`.

- [ ] **Step 6: Commit final verification notes if any docs changed**

If README or docs were updated during verification:

```bash
git add README.md docs/superpowers/plans/2026-06-07-sdr-live-receiver.md
git commit -m "docs: document SDR live receiver verification"
```

---

## Self-Review

- Spec coverage: Tasks cover receiver session state, receiver APIs, spectrum/waterfall frames, browser audio chunks, UI receiver workspace, OTA file awareness, and local/on-device validation. Scan/bookmark/evidence and streaming upgrade remain explicitly later slices from the spec.
- Placeholder scan: No `TBD`, `TODO`, or unspecified code steps are present. Each implementation step names exact files and concrete code.
- Type consistency: `ReceiverConfig`, `ReceiverSession`, `receiverStart`, `receiverStop`, `receiverStatus`, `receiverFrame`, `receiverAudio`, `SdrSpectrum`, `receiverFrameLoop`, and `receiverAudioLoop` are consistently named across backend, frontend, and validation tasks.
