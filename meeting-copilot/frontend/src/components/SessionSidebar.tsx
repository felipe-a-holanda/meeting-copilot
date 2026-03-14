import React, { useState, useEffect, useCallback } from 'react';
import { SessionListItem, SessionData } from '../types/messages';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

interface SessionSidebarProps {
  open: boolean;
  onClose: () => void;
  onLoadSession: (session: SessionData) => void;
}

export function SessionSidebar({ open, onClose, onLoadSession }: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/sessions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSessions(await res.json());
    } catch (e: any) {
      setError(e.message ?? 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) fetchSessions();
  }, [open, fetchSessions]);

  const handleSelect = async (id: string) => {
    setLoadingId(id);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/sessions/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const session: SessionData = await res.json();
      onLoadSession(session);
      onClose();
    } catch (e: any) {
      setError(e.message ?? 'Failed to load session');
    } finally {
      setLoadingId(null);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-72 h-full bg-white dark:bg-gray-800 shadow-xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Past Meetings</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-900 dark:hover:text-white text-2xl leading-none"
            aria-label="Close sidebar"
          >
            ×
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
          {loading && (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">Loading...</p>
          )}
          {error && (
            <p className="text-sm text-red-400 text-center py-6">{error}</p>
          )}
          {!loading && !error && sessions.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">
              No past sessions found
            </p>
          )}
          {sessions.map(s => (
            <button
              key={s.id}
              onClick={() => handleSelect(s.id)}
              disabled={loadingId === s.id}
              className="w-full text-left p-3 rounded-lg bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-60 transition-colors border border-gray-200 dark:border-transparent"
            >
              <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                {s.title || 'Untitled Meeting'}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {new Date(s.created_at).toLocaleDateString(undefined, {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })}{' '}
                · {s.segment_count} segment{s.segment_count !== 1 ? 's' : ''}
              </p>
              {loadingId === s.id && (
                <p className="text-xs text-indigo-500 mt-1">Loading...</p>
              )}
            </button>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={fetchSessions}
            disabled={loading}
            className="w-full px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 text-gray-700 dark:text-gray-200 rounded-lg transition-colors"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>
    </div>
  );
}
