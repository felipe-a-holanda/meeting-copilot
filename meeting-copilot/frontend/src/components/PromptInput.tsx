import React, { useState } from 'react';
import { CustomPromptResult } from '../types/messages';

interface PromptInputProps {
  results: CustomPromptResult[];
  onSendPrompt: (prompt: string) => void;
}

export function PromptInput({ results, onSendPrompt }: PromptInputProps) {
  const [prompt, setPrompt] = useState('');

  const handleSend = () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    onSendPrompt(trimmed);
    setPrompt('');
  };

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold text-gray-200">Ask the Copilot</h2>

      {/* Input row */}
      <div className="flex gap-2">
        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask anything about the meeting..."
          className="flex-1 bg-gray-700 text-gray-200 text-sm rounded px-3 py-1.5 border border-gray-600 focus:outline-none focus:border-purple-500 placeholder-gray-500"
        />
        <button
          onClick={handleSend}
          disabled={!prompt.trim()}
          className="shrink-0 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded transition-colors"
        >
          Ask
        </button>
      </div>

      {/* Prompt history — newest first */}
      {results.length > 0 ? (
        <div className="flex flex-col gap-3 overflow-y-auto max-h-60">
          {[...results].reverse().map((r, i) => (
            <div key={i} className="bg-gray-700/50 rounded-md p-3 text-sm">
              <p className="text-purple-300 font-medium mb-1">Q: {r.prompt}</p>
              <p className="text-gray-200 whitespace-pre-wrap leading-relaxed">{r.result}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-gray-500 text-sm italic">
          No questions yet. Ask anything about the meeting.
        </p>
      )}
    </div>
  );
}
