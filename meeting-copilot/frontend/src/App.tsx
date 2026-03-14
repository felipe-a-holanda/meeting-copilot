import React, { useState, useCallback } from 'react';
import { AudioControls } from './components/AudioControls';
import { TranscriptPanel } from './components/TranscriptPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { useAudioCapture } from './hooks/useAudioCapture';
import { TranscriptSegment } from './types/messages';

const AUDIO_WS_URL = process.env.REACT_APP_AUDIO_WS_URL || 'ws://localhost:8000/ws/audio';
const CONTROL_WS_URL = process.env.REACT_APP_CONTROL_WS_URL || 'ws://localhost:8000/ws/control';

function App() {
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);

  const handleControlMessage = useCallback((event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'transcript_segment') {
        setSegments(prev => [...prev, msg as TranscriptSegment]);
      }
    } catch {
      // ignore non-JSON messages
    }
  }, []);

  const audioWs = useWebSocket(AUDIO_WS_URL);
  const controlWs = useWebSocket(CONTROL_WS_URL, { onMessage: handleControlMessage });

  const { isCapturing, error, start: startCapture, stop: stopCapture } = useAudioCapture({
    onAudioChunk: useCallback((pcm: ArrayBuffer) => {
      audioWs.send(pcm);
    }, [audioWs]),
  });

  const handleStart = useCallback(async () => {
    audioWs.start();
    controlWs.start();
    await startCapture();
  }, [audioWs, controlWs, startCapture]);

  const handleStop = useCallback(() => {
    stopCapture();
    audioWs.disconnect();
    controlWs.disconnect();
  }, [audioWs, controlWs, stopCapture]);

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      <header className="border-b border-gray-700 px-6 py-4">
        <h1 className="text-2xl font-bold text-white">Meeting Copilot</h1>
        <p className="text-sm text-gray-400">Real-time AI meeting assistant</p>
      </header>

      <main className="max-w-5xl mx-auto p-6 flex flex-col gap-6">
        <AudioControls
          isCapturing={isCapturing}
          wsStatus={audioWs.status}
          error={error}
          onStart={handleStart}
          onStop={handleStop}
        />

        <div className="bg-gray-800 rounded-lg p-5 h-[60vh]">
          <TranscriptPanel segments={segments} />
        </div>
      </main>
    </div>
  );
}

export default App;
