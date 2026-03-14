import React, { useEffect, useRef } from 'react';
import { TranscriptSegment } from '../types/messages';

interface TranscriptPanelProps {
  segments: TranscriptSegment[];
}

export function TranscriptPanel({ segments }: TranscriptPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [segments]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  return (
    <div className="flex flex-col h-full">
      <h2 className="text-lg font-semibold text-gray-200 mb-3">Live Transcript</h2>
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {segments.length === 0 ? (
          <p className="text-gray-500 text-sm italic">Transcript will appear here when recording starts...</p>
        ) : (
          segments.map((seg, idx) => (
            <div key={`${seg.segment_id ?? idx}`} className="flex gap-3 text-sm">
              <span className="text-gray-500 font-mono shrink-0 pt-0.5">
                {formatTime(seg.timestamp_start)}
              </span>
              <div>
                <span className="font-medium text-blue-400">{seg.speaker}</span>
                {seg.is_partial && (
                  <span className="ml-2 text-xs text-gray-500 italic">(partial)</span>
                )}
                <p className="text-gray-200 mt-0.5">{seg.text}</p>
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
