# System Audio Capture — Options & Tradeoffs

## Problem

The current implementation uses `getUserMedia({ audio: true })`, which captures only the **microphone**. In a meeting, other participants' voices come through the **speakers** (system audio). Without capturing system audio, the app only transcribes what the local user says — missing the other side of every conversation.

---

## Option A — `getDisplayMedia()` + Mic Mix (Browser-only)

The Web Audio API supports capturing tab/screen audio when the user shares their screen. Two streams run in parallel:

- `getUserMedia` → local microphone
- `getDisplayMedia({ audio: true, video: false })` → tab or system audio

Both are merged into one `AudioContext` and the combined stream is sent to the backend.

**Pros**
- No installs required
- Works entirely in the browser
- No OS-level configuration

**Cons**
- Chrome shows a screen-share dialog — slightly disruptive UX
- On Linux, system audio capture via `getDisplayMedia` is unreliable or unsupported
- In most browsers, only captures **tab audio**, not all system audio

---

## Option B — Virtual Audio Device / OS-level Loopback

Install a virtual audio cable that exposes a device capturing everything playing through the speakers. The user selects this virtual device as the microphone in the browser — no code changes needed.

| Platform | Tools |
|----------|-------|
| Linux    | PulseAudio monitor source (built-in), PipeWire loopback |
| macOS    | BlackHole, Loopback |
| Windows  | VB-CABLE, Voicemeeter |

**Pros**
- Works with any browser, zero frontend code changes
- On Linux, PulseAudio monitor sources are available out-of-the-box
- Full system audio — captures all apps, not just one tab

**Cons**
- Requires per-machine OS-level setup
- User must manually select the virtual device in the browser

---

## Option C — Backend PulseAudio + ffmpeg ✅ Implemented

> **This approach is fully implemented in the backend. No separate script is required.**

PulseAudio automatically creates a `.monitor` source for every audio sink — no virtual device installation required. The backend's `AudioRecorder` class launches two separate `ffmpeg` processes and streams their output directly into the transcription pipeline:

1. Queries `pactl` for the default mic source and the default sink's monitor source (`<sink>.monitor`)
2. Launches two `ffmpeg` processes: one for mic (`-f pulse -i <mic>`), one for monitor (`-f pulse -i <sink>.monitor`)
3. Mic stream chunks are labeled **"Me"**, monitor stream chunks are labeled **"Them"** — no diarization needed
4. Each process outputs **16kHz mono PCM s16le** piped directly to the pipeline (no intermediate files unless `SAVE_RECORDINGS=true`)
5. Falls back gracefully to mic-only if the monitor source is unavailable (all chunks labeled "Me")
6. Saves WAV files + JSON metadata sidecar when `SAVE_RECORDINGS=true`
7. On server startup, orphaned `ffmpeg` processes from previous runs are automatically cleaned up

**How to use:** Set `AUDIO_CAPTURE_MODE=backend` in `.env` (the default). Recording is controlled via `POST /api/recording/start` and `POST /api/recording/stop`.

**Dependencies:** `pactl` (pulseaudio-utils or pipewire-pulse) + `ffmpeg` — both commonly pre-installed on Linux.

**Pros**
- No installs beyond common system packages
- PulseAudio monitor sources exist out-of-the-box — no sink creation needed
- Two-stream architecture gives 100% accurate speaker attribution at zero ML cost
- Graceful mic-only fallback
- Fully integrated into the web UI — start/stop from the browser
- WAV recordings + metadata sidecars saved automatically

**Cons**
- Linux/PulseAudio only (macOS/Windows must use `AUDIO_CAPTURE_MODE=browser`)
- Cannot distinguish multiple remote speakers — all remote audio is labeled "Them"

---

## Option D — Electron or Browser Extension

Wrap the frontend in Electron, or build a Chrome extension. Both have access to native OS audio APIs unavailable to regular web pages.

**Pros**
- Full system audio access without OS-level configuration by the user
- Can provide a polished, integrated UX

**Cons**
- Significant engineering effort
- Introduces a new runtime (Electron) or distribution channel (Chrome Web Store)
- Ongoing maintenance burden separate from the web app

---

## Option E — Meeting Platform Native Bots

For specific platforms (Zoom, Google Meet, Teams), use their SDKs or recording APIs. A bot joins the meeting server-side and captures audio directly from the platform.

**Pros**
- Clean, no local setup required
- Works regardless of the user's OS or browser

**Cons**
- Requires API keys and platform approval (especially Zoom/Teams)
- Does not work for ad-hoc, offline, or unsupported meeting tools
- Significant per-platform integration work

---

## Recommendation

| Horizon | Approach | Status |
|---------|----------|--------|
| **Now** | Option C — Backend PulseAudio + ffmpeg, fully integrated into FastAPI and React UI | ✅ **Implemented** |
| **Short term** | Option A — Add `getDisplayMedia` as a browser-native fallback for non-Linux users (`AUDIO_CAPTURE_MODE=browser`) | Partial (browser mode supported, no `getDisplayMedia` mixing yet) |
| **Medium term** | Option D — Electron wrapper for full cross-platform system audio without browser limits | Not started |
| **Long term** | Option E — Meeting platform native bots (Zoom, Teams, Google Meet) | Not started |

**Option C is the current default** (`AUDIO_CAPTURE_MODE=backend`). It provides the best speaker attribution (two-stream "Me"/"Them" labels) with zero ML cost on Linux systems with PulseAudio or PipeWire.
