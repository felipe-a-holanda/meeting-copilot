import React from 'react';
import { ActionItem } from '../types/messages';

interface CopilotPanelProps {
  summary: string;
  actionItems: ActionItem[];
}

const STATUS_STYLES: Record<ActionItem['status'], { bg: string; text: string }> = {
  new: { bg: 'bg-blue-900/50', text: 'text-blue-300' },
  updated: { bg: 'bg-yellow-900/50', text: 'text-yellow-300' },
  completed: { bg: 'bg-green-900/50', text: 'text-green-300' },
};

export function CopilotPanel({ summary, actionItems }: CopilotPanelProps) {
  return (
    <div className="flex flex-col h-full gap-5">
      {/* Summary Section */}
      <div className="flex-1 min-h-0 flex flex-col">
        <h2 className="text-lg font-semibold text-gray-200 mb-3">Summary</h2>
        <div className="flex-1 overflow-y-auto pr-1">
          {summary ? (
            <p className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{summary}</p>
          ) : (
            <p className="text-gray-500 text-sm italic">
              Summary will appear as the meeting progresses...
            </p>
          )}
        </div>
      </div>

      {/* Action Items Section */}
      <div className="flex-1 min-h-0 flex flex-col">
        <h2 className="text-lg font-semibold text-gray-200 mb-3">
          Action Items
          {actionItems.length > 0 && (
            <span className="ml-2 text-sm font-normal text-gray-400">
              ({actionItems.length})
            </span>
          )}
        </h2>
        <div className="flex-1 overflow-y-auto pr-1 space-y-2">
          {actionItems.length === 0 ? (
            <p className="text-gray-500 text-sm italic">
              Action items will be extracted automatically...
            </p>
          ) : (
            actionItems.map((item) => {
              const style = STATUS_STYLES[item.status];
              return (
                <div
                  key={item.id}
                  className="bg-gray-700/50 rounded-md p-3 text-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-gray-200 flex-1">{item.description}</p>
                    <span
                      className={`shrink-0 px-2 py-0.5 rounded text-xs font-medium ${style.bg} ${style.text}`}
                    >
                      {item.status}
                    </span>
                  </div>
                  {item.assignee && (
                    <p className="mt-1 text-xs text-gray-400">
                      Assignee: <span className="text-gray-300">{item.assignee}</span>
                    </p>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
