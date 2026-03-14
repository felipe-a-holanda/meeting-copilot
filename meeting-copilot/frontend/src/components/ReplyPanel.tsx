import React, { useState } from 'react';
import { ReplySuggestion } from '../types/messages';

interface ReplyPanelProps {
  suggestion: ReplySuggestion | null;
  onRequestSuggestions: (contextHint: string) => void;
}

export function ReplyPanel({ suggestion, onRequestSuggestions }: ReplyPanelProps) {
  const [contextHint, setContextHint] = useState('');
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const handleRequest = () => {
    onRequestSuggestions(contextHint);
  };

  const handleCopy = (text: string, index: number) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold text-gray-200">Reply Suggestions</h2>

      {/* Request input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={contextHint}
          onChange={(e) => setContextHint(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleRequest()}
          placeholder="Optional context hint..."
          className="flex-1 bg-gray-700 text-gray-200 text-sm rounded px-3 py-1.5 border border-gray-600 focus:outline-none focus:border-blue-500 placeholder-gray-500"
        />
        <button
          onClick={handleRequest}
          className="shrink-0 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded transition-colors"
        >
          Suggest Reply
        </button>
      </div>

      {/* Suggestions */}
      {suggestion && suggestion.suggestions.length > 0 ? (
        <div className="flex flex-col gap-2">
          {suggestion.context && (
            <p className="text-xs text-gray-400 italic">{suggestion.context}</p>
          )}
          {suggestion.suggestions.map((text, i) => (
            <div
              key={i}
              className="flex items-start justify-between gap-2 bg-gray-700/50 rounded-md p-3 text-sm"
            >
              <p className="text-gray-200 flex-1 leading-relaxed">{text}</p>
              <button
                onClick={() => handleCopy(text, i)}
                className="shrink-0 px-2 py-1 text-xs rounded bg-gray-600 hover:bg-gray-500 text-gray-300 transition-colors"
                title="Copy to clipboard"
              >
                {copiedIndex === i ? '✓ Copied' : 'Copy'}
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-gray-500 text-sm italic">
          Click "Suggest Reply" to get AI-generated response suggestions.
        </p>
      )}
    </div>
  );
}
