# KTOX SDR Live Receiver Design

## Goal

Build KTOX SDR into a HackRF-focused browser receiver that is more useful than a basic BrowSDR-style page for KTOX workflows. The receiver must tune, visualize, demodulate, play audio, capture evidence, and report hardware failures clearly from the WebUI.

This is a product reset from the current diagnostic/control panel. The page should still include hardware checks, but the primary experience is a live SDR workspace.

## Success Criteria

- The SDR Suite opens from the main KTOX WebUI at `http://<device-ip>:8081/`.
- The page can connect to HackRF through the backend service and show exact status for USB detection, `hackrf_info`, RX sample reads, and sweep support.
- A user can tune a frequency, select demodulation mode, adjust sample rate and gain, see spectrum/waterfall activity, and hear browser audio.
- Failures are visible at the action that failed, with the command layer identified: missing tools, USB permissions, HackRF busy, RX read failure, sweep failure, or demod failure.
- The implementation remains installable by OTA and `scripts/install_sdr.sh` without large external SDR engine dependencies in the first release.

## Scope

### In Scope

- HackRF One as the primary SDR hardware.
- Backend-owned HackRF access through the `ktox-sdr` service.
- Browser UI for receiver controls, spectrum, waterfall, demod audio, scan/bookmark preparation, capture, and diagnostics.
- Demodulation modes: `NFM`, `WFM`, `AM`, `USB`, `LSB`, `CW`, and `RAW`.
- Tactical presets for common ranges: NOAA weather, FM broadcast, ISM, Wi-Fi/Bluetooth area, ADS-B, GSM ranges, and user bookmarks.
- Evidence-friendly capture and export: IQ capture metadata, detected peaks, scan hits, and receiver settings used.

### Out of Scope For First Release

- Direct browser USB access to HackRF.
- Heavy GNU Radio/OpenWebRX/SoapySDR dependency stack.
- Transmit/replay automation beyond clearly separated future design. HackRF TX is safety-sensitive and should not be mixed into the first receiver release.
- Guaranteed real-time low-latency audio comparable to native SDR desktop applications. The first release prioritizes reliability on Pi/Kali hardware.

## Recommended Approach

Use a Hybrid Receiver architecture:

1. Start with stable backend chunk polling for receiver frames and demodulated audio.
2. Keep the backend DSP/session boundaries compatible with a future persistent stream.
3. Upgrade transport to WebSocket or Server-Sent Events after the HackRF and demodulation pipeline works reliably.

This avoids the current failure mode where the UI says the device is connected but individual actions do not actually prove RX, sweep, or demodulation.

## Architecture

### Components

- `services/sdr_server.py`: HTTP service on port `8081`, owns SDR routes and receiver session state.
- `sdr/device.py`: HackRF command wrapper for tool detection, USB detection, RX samples, sweeps, captures, and hardware self-tests.
- `sdr/processing.py`: FFT, spectrum, peak detection, and waterfall normalization.
- `sdr/demod.py`: demodulation and audio PCM generation.
- `sdr/receiver.py`: new receiver session layer for tuning state, chunk reads, spectrum frames, demod frames, squelch, and lifecycle control.
- `static/sdr/*`: browser receiver UI.
- `tools/validate_sdr_suite.py`: no-hardware validation for routes, static assets, DSP helpers, and command contracts.

### Data Flow

The receiver flow is:

`Browser controls -> ktox-sdr HTTP API -> Receiver session -> HackRF RX samples -> FFT/waterfall -> demodulator -> browser audio`

The backend is the only component that touches HackRF. The browser receives JSON frames for spectrum/waterfall and float PCM chunks for audio.

## Receiver UI

The first screen should be the receiver workspace, not a marketing page and not a diagnostics-only dashboard.

Primary areas:

- Top control bar: frequency, step size, sample rate, demod mode, bandwidth, squelch, LNA gain, VGA gain, amp toggle where supported, Listen/Stop.
- Spectrum view: FFT line graph with peak markers and selected VFO/frequency marker.
- Waterfall view: scrolling waterfall tied to the same receiver stream.
- Audio panel: browser audio state, volume, mute, underrun/error messages.
- Presets/bookmarks: tactical frequency groups and user-saved bookmarks.
- Diagnostics drawer: HackRF command status, USB status, recent command errors, serial-style USB devices where present.

## Backend API

Initial stable APIs:

- `POST /api/hackrf/connect`: detect HackRF and tool availability.
- `POST /api/hackrf/test`: run connect, RX sample read, and sweep smoke test.
- `POST /api/receiver/start`: create or update receiver session with frequency, sample rate, gain, mode, bandwidth, and squelch.
- `POST /api/receiver/stop`: stop active receiver session and release HackRF process state.
- `GET /api/receiver/status`: return current session state and last errors.
- `POST /api/receiver/frame`: return one spectrum/waterfall frame and optional signal metrics.
- `POST /api/receiver/audio`: return one demodulated audio chunk.
- `POST /api/hackrf/capture`: capture IQ at current or supplied settings.
- `GET /api/serial/ports` and `POST /api/serial/probe`: inspect non-HackRF serial-style USB devices.

Future streaming APIs:

- `/api/receiver/stream`: push spectrum/waterfall/audio metadata frames over WebSocket or SSE.
- `/api/receiver/audio-stream`: optional binary or chunked audio stream if browser scheduling through JSON is not good enough.

## Demodulation

The first release should implement practical demodulators in `sdr/demod.py`:

- `NFM`: phase difference FM demod for narrowband voice/weather style signals.
- `WFM/FM`: phase difference FM with wider gain/scaling.
- `AM`: magnitude demod with DC removal.
- `USB/LSB`: simple sideband approximation from complex components for first release.
- `CW`: tone-friendly magnitude/energy output.
- `RAW`: raw I/Q derived audio preview for debugging.

The demodulators should return normalized mono float PCM and metadata: mode, audio rate, sample count, peak level, and squelch state.

## Hardware Behavior

The UI must not treat `hackrf_info` alone as proof that the receiver works.

Connection state levels:

- `USB visible`: `lsusb` sees HackRF/OpenMoko ID.
- `Info readable`: `hackrf_info` returns board, serial, and firmware.
- `RX readable`: `hackrf_transfer -r -` can return sample bytes.
- `Sweep usable`: `hackrf_sweep` returns rows for a small range.
- `Receiver ready`: RX and demod frame routes both work.

The page should display the highest confirmed level and the failing layer.

## Error Handling

Errors must be action-local and explicit:

- Missing package: name the missing tool or Python dependency.
- USB permission issue: show that USB is visible but libhackrf cannot open it.
- HackRF busy: tell the user another process may own the device and expose stop/retry.
- Bad frequency/rate/gain: reject with validation before running a command.
- RX failure: show `hackrf_transfer` stderr.
- Sweep failure: show `hackrf_sweep` stderr.
- Audio failure: show demod or browser playback error.

Fallback static serving may keep the page open, but it must clearly state that backend SDR operations are unavailable.

## Install And OTA

The installer must include:

- `hackrf`
- `libhackrf0`
- `usbutils`
- `python3`
- `python3-pip`
- `python3-numpy`
- Python requirements from `requirements.txt`

OTA must verify all SDR files that are needed for the receiver, including `sdr/demod.py` and future `sdr/receiver.py`.

## Validation

No-hardware validation:

- Python syntax for SDR modules.
- JS syntax for SDR UI modules.
- Static asset checks for receiver controls.
- Fake-runner checks for HackRF command arguments.
- Demodulation helper tests.
- API route checks when Flask dependencies are available.

On-device validation:

- `hackrf_info`
- `lsusb`
- `POST /api/hackrf/connect`
- `POST /api/hackrf/test`
- `POST /api/receiver/frame`
- `POST /api/receiver/audio`
- Browser receiver listen test at a known local signal or NOAA/FM test range where applicable.

## Implementation Slices

1. Receiver session foundation: `sdr/receiver.py`, session state, start/stop/status APIs.
2. Receiver frames: spectrum/waterfall frame route using HackRF RX chunks.
3. Audio chunks: demodulated PCM route and browser audio scheduling.
4. UI receiver workspace: tune controls, signal meters, waterfall/spectrum, error drawer.
5. Presets and bookmarks: tactical groups and saved user frequencies.
6. Scan and evidence: range scan, peak detection, save hit, capture around hit.
7. Streaming upgrade: replace polling with persistent WebSocket/SSE transport once the pipeline is stable.

## Risks

- Pi/Kali CPU limits may make high-rate FFT and demodulation heavy. Defaults should use conservative sample rates first.
- JSON float audio chunks are not ideal long term. They are acceptable for initial proof, but persistent streaming or compressed/binary audio should be evaluated after the first stable receiver.
- HackRF only receives or transmits one stream at a time. Receiver session locking must prevent capture, sweep, and audio from fighting over the device.
- Browser audio may require a user gesture before playback. The Listen button satisfies this requirement.

## Non-Goals

This design does not attempt to clone BrowSDR exactly. KTOX SDR should be HackRF-first, diagnostic-rich, and evidence-oriented for KTOX workflows.
