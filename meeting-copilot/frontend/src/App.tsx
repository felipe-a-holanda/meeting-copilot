import React, { useCallback, useState, useEffect, useRef } from 'react';
import { AudioControls } from './components/AudioControls';
import { TranscriptPanel } from './components/TranscriptPanel';
import { CopilotPanel } from './components/CopilotPanel';
import { PromptInput } from './components/PromptInput';
import { ReplyPanel } from './components/ReplyPanel';
import { SettingsPanel } from './components/SettingsPanel';
import { SessionSidebar } from './components/SessionSidebar';
import { ErrorToast, Toast } from './components/ErrorToast';
import { DebugPanel } from './components/DebugPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { useAudioCapture } from './hooks/useAudioCapture';
import { useMeetingState } from './hooks/useMeetingState';
import { SessionData } from './types/messages';

const CONTROL_WS_URL = process.env.REACT_APP_CONTROL_WS_URL || 'ws://localhost:8000/ws/control';

function ConnectionDot({ status }: { status: 'connecting' | 'connected' | 'disconnected' }) {
  const color =
    status === 'connected'
      ? 'bg-green-500'
      : status === 'connecting'
      ? 'bg-yellow-500 animate-pulse'
      : 'bg-gray-400';
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function App() {
  const { state, handleMessage, loadSession } = useMeetingState();

  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('theme') !== 'light');
  const [showSettings, setShowSettings] = useState(false);
  const [showSessions, setShowSessions] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // Debug stats
  const debugStatsRef = useRef({
    audioChunksSent: 0,
    audioBytesSent: 0,
    messagesReceived: 0,
    lastMessageType: null as string | null,
    lastChunkSize: null as number | null,
    recentMessages: [] as Array<{ type: string; ts: number; preview: string }>,
  });
  const [debugStats, setDebugStats] = useState(debugStatsRef.current);

  const addToast = useCallback((message: string, type: Toast['type'] = 'error') => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts(prev => [...prev, { id, message, type }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // Apply / remove `dark` class on the root element
  useEffect(() => {
    const root = document.documentElement;
    if (darkMode) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  const handleControlMessage = useCallback((event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      const s = debugStatsRef.current;
      s.messagesReceived += 1;
      s.lastMessageType = data.type ?? 'unknown';
      const preview = JSON.stringify(data).slice(0, 80);
      s.recentMessages = [{ type: data.type ?? 'unknown', ts: Date.now(), preview }, ...s.recentMessages].slice(0, 8);
      setDebugStats({ ...s });

      if (data.type === 'error') {
        addToast(data.message || 'An error occurred', 'error');
        return;
      }
    } catch {
      // ignore parse errors
    }
    handleMessage(event);
  }, [handleMessage, addToast]);

  const controlWs = useWebSocket(CONTROL_WS_URL, { onMessage: handleControlMessage });

  const {
    send: sendControl,
    start: startControl,
    disconnect: disconnectControl,
  } = controlWs;

  useEffect(() => {
    startControl();
    return () => {
      disconnectControl();
    };
  }, [startControl, disconnectControl]);

  const {
    isRecording,
    status: recordingStatus,
    devices,
    error,
    start: startCapture,
    stop: stopCapture,
    fetchDevices,
  } = useAudioCapture();

  useEffect(() => {
    if (error) addToast(error, 'error');
  }, [error, addToast]);

  const handleStart = useCallback(async (options?: import('./types/messages').RecordingStartRequest) => {
    startControl();
    await startCapture(options);
  }, [startControl, startCapture]);

  const handleStop = useCallback(async () => {
    await stopCapture();
    disconnectControl();
  }, [disconnectControl, stopCapture]);

  const handleRequestReplySuggestions = useCallback(
    (contextHint: string) => {
      sendControl(JSON.stringify({ type: 'request_reply', context_hint: contextHint || null }));
    },
    [sendControl]
  );

  const handleSendCustomPrompt = useCallback(
    (prompt: string) => {
      sendControl(JSON.stringify({ type: 'custom_prompt', prompt }));
    },
    [sendControl]
  );

  const handleLoadSession = useCallback(
    (session: SessionData) => {
      loadSession(session);
    },
    [loadSession]
  );

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 transition-colors duration-200">
      <ErrorToast toasts={toasts} onDismiss={dismissToast} />
      <DebugPanel
        audioWsStatus={controlWs.status}
        controlWsStatus={controlWs.status}
        stats={debugStats}
      />
      {/* Overlays */}
      <SettingsPanel open={showSettings} onClose={() => setShowSettings(false)} />
      <SessionSidebar
        open={showSessions}
        onClose={() => setShowSessions(false)}
        onLoadSession={handleLoadSession}
      />

      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 sm:px-6 py-3">
        <div className="max-w-7xl mx-auto flex items-center gap-2 sm:gap-3">
          {/* Sessions toggle */}
          <button
            onClick={() => setShowSessions(true)}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 transition-colors"
            title="Browse past meetings"
            aria-label="Browse past meetings"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          {/* Title */}
          <div className="flex-1 min-w-0">
            <h1 className="text-base sm:text-xl font-bold text-gray-900 dark:text-white leading-tight truncate">
              Meeting Copilot
            </h1>
            <p className="hidden sm:block text-xs text-gray-500 dark:text-gray-400">
              Real-time AI meeting assistant
            </p>
          </div>

          {/* Connection status — desktop only */}
          <div className="hidden sm:flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
            <span className="flex items-center gap-1.5">
              <ConnectionDot status={controlWs.status} />
              Control
            </span>
          </div>

          {/* Dark mode toggle */}
          <button
            onClick={() => setDarkMode(d => !d)}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 transition-colors"
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {darkMode ? (
              /* sun icon */
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707M17.657 17.657l-.707-.707M6.343 6.343l-.707-.707M12 8a4 4 0 100 8 4 4 0 000-8z"
                />
              </svg>
            ) : (
              /* moon icon */
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
                />
              </svg>
            )}
          </button>

          {/* Settings toggle */}
          <button
            onClick={() => setShowSettings(true)}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 transition-colors"
            title="Settings"
            aria-label="Settings"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
              />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        </div>

        {/* Mobile connection status bar */}
        <div className="sm:hidden max-w-7xl mx-auto flex items-center gap-4 pt-1 text-xs text-gray-500 dark:text-gray-400">
          <span className="flex items-center gap-1.5">
            <ConnectionDot status={controlWs.status} />
            Control {controlWs.status}
          </span>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto p-3 sm:p-6 flex flex-col gap-4 sm:gap-6">
        <AudioControls
          isRecording={isRecording}
          wsStatus={controlWs.status}
          status={recordingStatus}
          devices={devices}
          onStart={handleStart}
          onStop={handleStop}
          onFetchDevices={fetchDevices}
        />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
          {/* Transcript panel */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 sm:p-5 min-h-64 lg:h-[calc(100vh-220px)] flex flex-col">
            <TranscriptPanel segments={state.segments} />
          </div>

          {/* Copilot panel (scrollable) */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 sm:p-5 flex flex-col gap-5 overflow-y-auto lg:h-[calc(100vh-220px)]">
            <CopilotPanel
              summary={state.summary}
              actionItems={state.actionItems}
              contradictions={state.contradictions}
            />
            <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
              <ReplyPanel
                suggestion={state.replySuggestions}
                onRequestSuggestions={handleRequestReplySuggestions}
              />
            </div>
            <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
              <PromptInput
                results={state.customPromptResults}
                onSendPrompt={handleSendCustomPrompt}
              />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
