import { useState, useCallback, useEffect, useRef } from 'react';
import type {
  DeviceListResponse,
  RecordingStartRequest,
  RecordingStartResponse,
  RecordingStopResponse,
  RecordingStatusResponse,
} from '../types/messages';

const API_BASE = '/api';
const STATUS_POLL_INTERVAL_MS = 2000;

export interface UseAudioCaptureReturn {
  isRecording: boolean;
  status: RecordingStatusResponse | null;
  devices: DeviceListResponse | null;
  error: string | null;
  start: (options?: RecordingStartRequest) => Promise<RecordingStartResponse | null>;
  stop: () => Promise<RecordingStopResponse | null>;
  fetchDevices: () => Promise<void>;
}

export function useAudioCapture(): UseAudioCaptureReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState<RecordingStatusResponse | null>(null);
  const [devices, setDevices] = useState<DeviceListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPoll = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/recording/status`);
      if (!res.ok) return;
      const data: RecordingStatusResponse = await res.json();
      setStatus(data);
      setIsRecording(data.is_recording);
      if (!data.is_recording) {
        clearPoll();
      }
    } catch {
      // Network error — don't surface during polling
    }
  }, [clearPoll]);

  const startPoll = useCallback(() => {
    clearPoll();
    pollIntervalRef.current = setInterval(fetchStatus, STATUS_POLL_INTERVAL_MS);
  }, [clearPoll, fetchStatus]);

  // Clean up interval on unmount
  useEffect(() => {
    return () => clearPoll();
  }, [clearPoll]);

  const fetchDevices = useCallback(async () => {
    try {
      setError(null);
      const res = await fetch(`${API_BASE}/audio/devices`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Device list failed: ${res.status}`);
      }
      const data: DeviceListResponse = await res.json();
      setDevices(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch devices');
    }
  }, []);

  const start = useCallback(
    async (options?: RecordingStartRequest): Promise<RecordingStartResponse | null> => {
      try {
        setError(null);
        const res = await fetch(`${API_BASE}/recording/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(options ?? {}),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? `Start failed: ${res.status}`);
        }
        const data: RecordingStartResponse = await res.json();
        setIsRecording(true);
        startPoll();
        return data;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to start recording');
        return null;
      }
    },
    [startPoll],
  );

  const stop = useCallback(async (): Promise<RecordingStopResponse | null> => {
    try {
      setError(null);
      const res = await fetch(`${API_BASE}/recording/stop`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Stop failed: ${res.status}`);
      }
      const data: RecordingStopResponse = await res.json();
      setIsRecording(false);
      clearPoll();
      // Fetch one final status snapshot
      await fetchStatus();
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop recording');
      return null;
    }
  }, [clearPoll, fetchStatus]);

  return { isRecording, status, devices, error, start, stop, fetchDevices };
}
