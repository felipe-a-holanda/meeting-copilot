import React, { useState } from 'react';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export interface AppSettings {
  audioCaptureMode: 'backend' | 'browser' | 'both';
  whisperModelSize: 'turbo' | 'tiny' | 'small' | 'medium' | 'large';
  useClaudeApiFallback: boolean;
  micVolume: number;
  saveRecordings: boolean;
}

const DEFAULTS: AppSettings = {
  audioCaptureMode: 'backend',
  whisperModelSize: 'small',
  useClaudeApiFallback: false,
  micVolume: 2.0,
  saveRecordings: true,
};

export function loadAppSettings(): AppSettings {
  try {
    const stored = localStorage.getItem('meeting-copilot-settings');
    if (stored) return { ...DEFAULTS, ...JSON.parse(stored) };
  } catch {}
  return DEFAULTS;
}

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const [settings, setSettings] = useState<AppSettings>(loadAppSettings);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    localStorage.setItem('meeting-copilot-settings', JSON.stringify(settings));
    try {
      await fetch(`${API_BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          whisper_model_size: settings.whisperModelSize,
          use_claude_api_fallback: settings.useClaudeApiFallback,
          audio_capture_mode: settings.audioCaptureMode,
          mic_volume: settings.micVolume,
          save_recordings: settings.saveRecordings,
        }),
      });
    } catch {
      // backend may not be running; settings are still saved locally
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-80 h-full bg-white dark:bg-gray-800 shadow-xl p-6 flex flex-col gap-5 overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Settings</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-900 dark:hover:text-white text-2xl leading-none"
            aria-label="Close settings"
          >
            ×
          </button>
        </div>

        <div className="flex flex-col gap-4">
          {/* Audio capture mode */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-200">
              Audio Capture Mode
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Backend: PulseAudio via ffmpeg (recommended)
            </p>
            <select
              value={settings.audioCaptureMode}
              onChange={e =>
                setSettings(s => ({
                  ...s,
                  audioCaptureMode: e.target.value as AppSettings['audioCaptureMode'],
                }))
              }
              className="bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-200 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="backend">Backend (PulseAudio + ffmpeg)</option>
              <option value="browser">Browser (getUserMedia)</option>
              <option value="both">Both</option>
            </select>
          </div>

          {/* Mic volume */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-200">
              Mic Volume Boost: {settings.micVolume.toFixed(1)}×
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400">Amplify microphone input</p>
            <input
              type="range"
              min={0.5}
              max={5.0}
              step={0.1}
              value={settings.micVolume}
              onChange={e => setSettings(s => ({ ...s, micVolume: parseFloat(e.target.value) }))}
              className="w-full accent-indigo-600"
            />
            <div className="flex justify-between text-xs text-gray-400">
              <span>0.5×</span>
              <span>5.0×</span>
            </div>
          </div>

          {/* Save recordings toggle */}
          <label className="flex items-center justify-between gap-3 cursor-pointer">
            <div>
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200">Save Recordings</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">Write WAV files to disk</p>
            </div>
            <button
              role="switch"
              aria-checked={settings.saveRecordings}
              onClick={() => setSettings(s => ({ ...s, saveRecordings: !s.saveRecordings }))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                settings.saveRecordings ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.saveRecordings ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </label>

          {/* Whisper model size */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-200">
              Whisper Model Size
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400">Larger = better quality, slower</p>
            <select
              value={settings.whisperModelSize}
              onChange={e =>
                setSettings(s => ({
                  ...s,
                  whisperModelSize: e.target.value as AppSettings['whisperModelSize'],
                }))
              }
              className="bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-200 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="turbo">Turbo (fastest, highest throughput)</option>
              <option value="tiny">Tiny (fastest, ~39M params)</option>
              <option value="small">Small (balanced, ~244M params)</option>
              <option value="medium">Medium (~769M params)</option>
              <option value="large">Large (best quality, ~1.5B params)</option>
            </select>
          </div>

          {/* Claude API fallback */}
          <label className="flex items-center justify-between gap-3 cursor-pointer">
            <div>
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200">Claude API Fallback</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">Use Claude when Ollama fails</p>
            </div>
            <button
              role="switch"
              aria-checked={settings.useClaudeApiFallback}
              onClick={() => setSettings(s => ({ ...s, useClaudeApiFallback: !s.useClaudeApiFallback }))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                settings.useClaudeApiFallback ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.useClaudeApiFallback ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </label>
        </div>

        <button
          onClick={handleSave}
          className="mt-auto px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {saved ? '✓ Saved!' : 'Save Settings'}
        </button>
      </div>
    </div>
  );
}
