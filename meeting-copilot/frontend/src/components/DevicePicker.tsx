import React, { useEffect } from 'react';
import type { AudioDevice, DeviceListResponse } from '../types/messages';

interface DevicePickerProps {
  devices: DeviceListResponse | null;
  micSource: string;
  monitorSource: string;
  micVolume: number;
  onMicSourceChange: (source: string) => void;
  onMonitorSourceChange: (source: string) => void;
  onMicVolumeChange: (volume: number) => void;
  onRefresh: () => void;
  disabled?: boolean;
}

function DeviceSelect({
  label,
  devices,
  value,
  defaultValue,
  onChange,
  disabled,
}: {
  label: string;
  devices: AudioDevice[];
  value: string;
  defaultValue: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-gray-400 font-medium">{label}</label>
      <select
        value={value || defaultValue}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || devices.length === 0}
        className="bg-gray-700 text-gray-100 text-sm rounded px-2 py-1.5 border border-gray-600 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {devices.length === 0 ? (
          <option value="">No devices found</option>
        ) : (
          devices.map((d) => (
            <option key={d.name} value={d.name}>
              {d.description || d.name}
            </option>
          ))
        )}
      </select>
    </div>
  );
}

export function DevicePicker({
  devices,
  micSource,
  monitorSource,
  micVolume,
  onMicSourceChange,
  onMonitorSourceChange,
  onMicVolumeChange,
  onRefresh,
  disabled,
}: DevicePickerProps) {
  // Auto-select defaults when devices load
  useEffect(() => {
    if (!devices) return;
    if (!micSource && devices.defaults.source) {
      onMicSourceChange(devices.defaults.source);
    }
    if (!monitorSource && devices.defaults.monitor) {
      onMonitorSourceChange(devices.defaults.monitor);
    }
  }, [devices]); // eslint-disable-line react-hooks/exhaustive-deps

  const monitorSources: AudioDevice[] = devices
    ? devices.sources.filter((s) => s.name.endsWith('.monitor'))
    : [];

  return (
    <div className="flex flex-col gap-3 p-3 bg-gray-750 rounded-lg border border-gray-700">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 font-semibold uppercase tracking-wide">
          Audio Devices
        </span>
        <button
          onClick={onRefresh}
          disabled={disabled}
          className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Refresh
        </button>
      </div>

      <DeviceSelect
        label="Microphone (Me)"
        devices={devices?.sources ?? []}
        value={micSource}
        defaultValue={devices?.defaults.source ?? ''}
        onChange={onMicSourceChange}
        disabled={disabled}
      />

      <DeviceSelect
        label="System Audio (Them)"
        devices={monitorSources}
        value={monitorSource}
        defaultValue={devices?.defaults.monitor ?? ''}
        onChange={onMonitorSourceChange}
        disabled={disabled}
      />

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-400 font-medium">
          Mic Volume Boost: {micVolume.toFixed(1)}x
        </label>
        <input
          type="range"
          min={0.5}
          max={5.0}
          step={0.1}
          value={micVolume}
          onChange={(e) => onMicVolumeChange(parseFloat(e.target.value))}
          disabled={disabled}
          className="w-full accent-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        />
        <div className="flex justify-between text-xs text-gray-500">
          <span>0.5x</span>
          <span>5.0x</span>
        </div>
      </div>
    </div>
  );
}
