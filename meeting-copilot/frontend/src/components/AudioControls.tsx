import React from 'react';

interface AudioControlsProps {
  isCapturing: boolean;
  wsStatus: 'connecting' | 'connected' | 'disconnected';
  error: string | null;
  onStart: () => void;
  onStop: () => void;
}

export function AudioControls({ isCapturing, wsStatus, error, onStart, onStop }: AudioControlsProps) {
  const statusColor = {
    connected: 'bg-green-500',
    connecting: 'bg-yellow-500',
    disconnected: 'bg-red-500',
  }[wsStatus];

  const statusLabel = {
    connected: 'Connected',
    connecting: 'Connecting...',
    disconnected: 'Disconnected',
  }[wsStatus];

  return (
    <div className="flex flex-col gap-3 p-4 bg-gray-800 rounded-lg">
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full ${statusColor}`} />
        <span className="text-sm text-gray-300">{statusLabel}</span>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onStart}
          disabled={isCapturing || wsStatus !== 'connected'}
          className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
        >
          Start Recording
        </button>
        <button
          onClick={onStop}
          disabled={!isCapturing}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
        >
          Stop Recording
        </button>
      </div>

      {isCapturing && (
        <div className="flex items-center gap-2 text-sm text-green-400">
          <span className="animate-pulse">●</span>
          <span>Recording in progress...</span>
        </div>
      )}

      {error && (
        <div className="text-sm text-red-400 bg-red-900/30 p-2 rounded">
          {error}
        </div>
      )}
    </div>
  );
}
