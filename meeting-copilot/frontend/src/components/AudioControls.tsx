import React, { useState, useEffect } from 'react';
import { DevicePicker } from './DevicePicker';
import type {
  DeviceListResponse,
  RecordingStartRequest,
  RecordingStatusResponse,
} from '../types/messages';

interface AudioControlsProps {
  isRecording: boolean;
  wsStatus: 'connecting' | 'connected' | 'disconnected';
  status: RecordingStatusResponse | null;
  devices: DeviceListResponse | null;
  onStart: (options: RecordingStartRequest) => Promise<void>;
  onStop: () => Promise<void>;
  onFetchDevices: () => Promise<void>;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function AudioControls({
  isRecording,
  wsStatus,
  status,
  devices,
  onStart,
  onStop,
  onFetchDevices,
}: AudioControlsProps) {
  const [title, setTitle] = useState('');
  const [micSource, setMicSource] = useState('');
  const [monitorSource, setMonitorSource] = useState('');
  const [micVolume, setMicVolume] = useState(2.0);

  useEffect(() => {
    onFetchDevices();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const wsStatusColor = {
    connected: 'bg-green-500',
    connecting: 'bg-yellow-500',
    disconnected: 'bg-red-500',
  }[wsStatus];

  const wsStatusLabel = {
    connected: 'Connected',
    connecting: 'Connecting...',
    disconnected: 'Disconnected',
  }[wsStatus];

  const handleStart = async () => {
    const options: RecordingStartRequest = {};
    if (title.trim()) options.title = title.trim();
    if (micSource) options.mic_source = micSource;
    if (monitorSource) options.monitor_source = monitorSource;
    options.mic_volume = micVolume;
    await onStart(options);
  };

  return (
    <div className="flex flex-col gap-3 p-4 bg-gray-800 rounded-lg">
      {/* WS status */}
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full ${wsStatusColor}`} />
        <span className="text-sm text-gray-300">{wsStatusLabel}</span>
        {isRecording && status && (
          <span className="ml-auto text-sm font-mono text-gray-300">
            {formatDuration(status.duration_seconds)}
          </span>
        )}
      </div>

      {/* Meeting title */}
      <input
        type="text"
        placeholder="Meeting title (optional)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        disabled={isRecording}
        className="bg-gray-700 text-gray-100 text-sm rounded px-3 py-1.5 border border-gray-600 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed placeholder-gray-500"
      />

      {/* Device picker */}
      <DevicePicker
        devices={devices}
        micSource={micSource}
        monitorSource={monitorSource}
        micVolume={micVolume}
        onMicSourceChange={setMicSource}
        onMonitorSourceChange={setMonitorSource}
        onMicVolumeChange={setMicVolume}
        onRefresh={onFetchDevices}
        disabled={isRecording}
      />

      {/* Controls */}
      <div className="flex gap-3 items-center">
        <button
          onClick={handleStart}
          disabled={isRecording || wsStatus !== 'connected'}
          className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
        >
          Start Recording
        </button>
        <button
          onClick={onStop}
          disabled={!isRecording}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
        >
          Stop Recording
        </button>

        {isRecording && (
          <span className="flex items-center gap-1.5 text-sm text-red-400 ml-auto">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            Recording
          </span>
        )}
      </div>

      {/* Segment count while recording */}
      {isRecording && status && (
        <div className="text-xs text-gray-400 flex gap-4">
          <span>Chunks: {status.chunks_processed}</span>
          <span>Segments: {status.segments_emitted}</span>
        </div>
      )}
    </div>
  );
}
