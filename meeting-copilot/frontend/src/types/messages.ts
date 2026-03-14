// TypeScript interfaces matching backend protocol models from backend/ws/protocol.py

// === Audio Pipeline → Frontend ===

export interface TranscriptSegment {
  type: 'transcript_segment';
  speaker: string;
  text: string;
  timestamp_start: number;
  timestamp_end: number;
  language: string;
  is_partial: boolean;
  segment_id?: string;
}

// === Reasoning Engine → Frontend ===

export interface SummaryUpdate {
  type: 'summary_update';
  summary: string;
  covered_until: number;
}

export interface ActionItem {
  id: string;
  description: string;
  assignee: string | null;
  source_timestamp: number;
  status: 'new' | 'updated' | 'completed';
}

export interface ActionItemsUpdate {
  type: 'action_items_update';
  items: ActionItem[];
}

export interface ContradictionAlert {
  type: 'contradiction_alert';
  description: string;
  statement_a: string;
  statement_a_timestamp: number;
  statement_b: string;
  statement_b_timestamp: number;
  severity: 'low' | 'medium' | 'high';
}

export interface ReplySuggestion {
  type: 'reply_suggestion';
  suggestions: string[];
  context: string;
  triggered_by: 'auto' | 'manual';
}

export interface CustomPromptResult {
  type: 'custom_prompt_result';
  prompt: string;
  result: string;
  timestamp: number;
}

// === Frontend → Backend ===

export interface RequestReplySuggestion {
  type: 'request_reply';
  context_hint?: string | null;
}

export interface CustomPromptRequest {
  type: 'custom_prompt';
  prompt: string;
}

// Union type for all server → client messages
export type ServerMessage =
  | TranscriptSegment
  | SummaryUpdate
  | ActionItemsUpdate
  | ContradictionAlert
  | ReplySuggestion
  | CustomPromptResult;

// Union type for all client → server messages
export type ClientMessage = RequestReplySuggestion | CustomPromptRequest;

// === Session / Storage types ===

export interface SessionListItem {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  segment_count: number;
}

export interface SessionData {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  segments: TranscriptSegment[];
  summary: string;
  action_items: ActionItem[];
}
