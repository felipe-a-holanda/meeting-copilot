import React, { useState, useEffect, useCallback } from 'react';

interface DebugStats {
  audioChunksSent: number;
  audioBytesSent: number;
  messagesReceived: number;
  lastMessageType: string | null;
  lastChunkSize: number | null;
  recentMessages: Array<{ type: string; ts: number; preview: string }>;
}

interface BackendDebug {
  pipeline: {
    chunks_received: number;
    bytes_received: number;
    vad_speech: number;
    vad_no_speech: number;
    vad_unavailable: number;
    transcription_attempts: number;
    transcription_results: number;
    transcription_errors: number;
    segments_emitted: number;
    whisper_model_loaded: boolean;
    whisper_model_size: string;
  };
  settings: Record<string, unknown>;
  connections: { audio: number; control: number };
}

interface DebugPanelProps {
  audioWsStatus: string;
  controlWsStatus: string;
  stats: DebugStats;
}

export function DebugPanel({ audioWsStatus, controlWsStatus, stats }: DebugPanelProps) {
  const [open, setOpen] = useState(false);
  const [backend, setBackend] = useState<BackendDebug | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const fetchBackend = useCallback(async () => {
    setFetching(true);
    setBackendError(null);
    try {
      const res = await fetch('http://localhost:8000/debug');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBackend(await res.json());
    } catch (e) {
      setBackendError(e instanceof Error ? e.message : 'Failed to fetch');
    } finally {
      setFetching(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    fetchBackend();
    const id = setInterval(fetchBackend, 2000);
    return () => clearInterval(id);
  }, [open, fetchBackend]);

  const fmt = (n: number) =>
    n >= 1024 * 1024
      ? `${(n / 1024 / 1024).toFixed(1)} MB`
      : n >= 1024
      ? `${(n / 1024).toFixed(1)} KB`
      : `${n} B`;

  return (
    <div className="fixed bottom-4 right-4 z-50 font-mono text-xs">
      <button
        onClick={() => setOpen(o => !o)}
        className="px-3 py-1.5 bg-gray-900 border border-gray-600 text-gray-300 rounded-lg hover:bg-gray-800 transition-colors"
      >
        {open ? '✕ Close Debug' : '🐛 Debug'}
      </button>

      {open && (
        <div className="mt-2 w-96 max-h-[80vh] overflow-y-auto bg-gray-950 border border-gray-700 rounded-xl shadow-2xl p-4 space-y-4">
          <h2 className="text-gray-200 font-bold text-sm">Debug Panel</h2>

          {/* WebSocket status */}
          <section>
            <h3 className="text-gray-400 uppercase tracking-wider mb-1">WebSockets</h3>
            <table className="w-full">
              <tbody>
                <tr>
                  <td className="text-gray-500 pr-3">Audio WS</td>
                  <td className={wsColor(audioWsStatus)}>{audioWsStatus}</td>
                </tr>
                <tr>
                  <td className="text-gray-500 pr-3">Control WS</td>
                  <td className={wsColor(controlWsStatus)}>{controlWsStatus}</td>
                </tr>
              </tbody>
            </table>
          </section>

          {/* Frontend audio stats */}
          <section>
            <h3 className="text-gray-400 uppercase tracking-wider mb-1">Frontend Audio</h3>
            <table className="w-full">
              <tbody>
                <Row label="Chunks sent" value={stats.audioChunksSent} />
                <Row label="Bytes sent" value={fmt(stats.audioBytesSent)} />
                <Row label="Last chunk" value={stats.lastChunkSize != null ? `${stats.lastChunkSize} B` : '—'} />
                <Row label="Messages recv" value={stats.messagesReceived} />
                <Row label="Last msg type" value={stats.lastMessageType ?? '—'} />
              </tbody>
            </table>
          </section>

          {/* Recent messages */}
          {stats.recentMessages.length > 0 && (
            <section>
              <h3 className="text-gray-400 uppercase tracking-wider mb-1">Recent Messages</h3>
              <div className="space-y-1">
                {stats.recentMessages.map((m, i) => (
                  <div key={i} className="text-gray-400">
                    <span className="text-blue-400">[{m.type}]</span>{' '}
                    <span className="text-gray-500">{new Date(m.ts).toLocaleTimeString()}</span>{' '}
                    <span className="text-gray-300 truncate block max-w-full">{m.preview}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Backend stats */}
          <section>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-gray-400 uppercase tracking-wider">Backend Pipeline</h3>
              <button
                onClick={fetchBackend}
                disabled={fetching}
                className="text-gray-500 hover:text-gray-300 disabled:opacity-50"
              >
                {fetching ? '…' : '↻'}
              </button>
            </div>
            {backendError && (
              <div className="text-red-400 bg-red-900/20 p-2 rounded mb-2">
                {backendError} — is the backend running?
              </div>
            )}
            {backend && (
              <>
                <table className="w-full mb-2">
                  <tbody>
                    <Row
                      label="Whisper model"
                      value={`${backend.pipeline.whisper_model_size} (${backend.pipeline.whisper_model_loaded ? '✓ loaded' : '✗ not loaded'})`}
                      valueClass={backend.pipeline.whisper_model_loaded ? 'text-green-400' : 'text-red-400'}
                    />
                    <Row label="Chunks recv" value={backend.pipeline.chunks_received} />
                    <Row label="Bytes recv" value={fmt(backend.pipeline.bytes_received)} />
                    <Row label="VAD: speech" value={backend.pipeline.vad_speech} />
                    <Row label="VAD: silence" value={backend.pipeline.vad_no_speech} />
                    <Row label="VAD: unavail" value={backend.pipeline.vad_unavailable} />
                    <Row label="Transc attempts" value={backend.pipeline.transcription_attempts} />
                    <Row label="Transc results" value={backend.pipeline.transcription_results} />
                    <Row label="Transc errors" value={backend.pipeline.transcription_errors} />
                    <Row label="Segments emitted" value={backend.pipeline.segments_emitted} />
                    <Row label="Audio conns" value={backend.connections.audio} />
                    <Row label="Control conns" value={backend.connections.control} />
                  </tbody>
                </table>

                {/* Quick diagnosis */}
                <Diagnosis pipeline={backend.pipeline} audioWsStatus={audioWsStatus} stats={stats} />
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function wsColor(status: string) {
  if (status === 'connected') return 'text-green-400';
  if (status === 'connecting') return 'text-yellow-400';
  return 'text-red-400';
}

function Row({
  label,
  value,
  valueClass = 'text-gray-200',
}: {
  label: string;
  value: string | number;
  valueClass?: string;
}) {
  return (
    <tr>
      <td className="text-gray-500 pr-3 py-0.5">{label}</td>
      <td className={valueClass}>{value}</td>
    </tr>
  );
}

function Diagnosis({
  pipeline,
  audioWsStatus,
  stats,
}: {
  pipeline: BackendDebug['pipeline'];
  audioWsStatus: string;
  stats: DebugStats;
}) {
  const issues: string[] = [];

  if (audioWsStatus !== 'connected') issues.push('Audio WebSocket is not connected — audio cannot be sent');
  if (stats.audioChunksSent > 0 && pipeline.chunks_received === 0)
    issues.push('Frontend sent audio but backend received 0 chunks — check CORS/WS URL');
  if (pipeline.chunks_received > 0 && pipeline.vad_speech === 0 && pipeline.vad_unavailable === 0)
    issues.push('Backend receiving audio but VAD finds no speech — try speaking louder or check mic');
  if (pipeline.vad_speech > 0 && pipeline.transcription_attempts === 0)
    issues.push('VAD found speech but no transcription attempted — unexpected buffer state');
  if (pipeline.transcription_attempts > 0 && pipeline.transcription_results === 0 && pipeline.transcription_errors === 0)
    issues.push('Transcription running but producing no results — Whisper may see silence');
  if (pipeline.transcription_errors > 0)
    issues.push(`${pipeline.transcription_errors} transcription error(s) — check backend logs`);
  if (!pipeline.whisper_model_loaded)
    issues.push('Whisper model not yet loaded — wait a moment or check backend logs');

  if (issues.length === 0) {
    return <div className="text-green-400 text-xs">✓ No obvious issues detected</div>;
  }

  return (
    <div className="space-y-1">
      {issues.map((msg, i) => (
        <div key={i} className="text-yellow-300 bg-yellow-900/20 rounded px-2 py-1">
          ⚠ {msg}
        </div>
      ))}
    </div>
  );
}
