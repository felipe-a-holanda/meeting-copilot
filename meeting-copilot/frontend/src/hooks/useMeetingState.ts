import { useReducer, useCallback } from 'react';
import {
  TranscriptSegment,
  SummaryUpdate,
  ActionItem,
  ActionItemsUpdate,
  ContradictionAlert,
  ReplySuggestion,
  CustomPromptResult,
} from '../types/messages';

export interface MeetingState {
  segments: TranscriptSegment[];
  summary: string;
  coveredUntil: number;
  actionItems: ActionItem[];
  contradictions: ContradictionAlert[];
  replySuggestions: ReplySuggestion | null;
  customPromptResults: CustomPromptResult[];
}

type MeetingAction =
  | { type: 'transcript_segment'; payload: TranscriptSegment }
  | { type: 'summary_update'; payload: SummaryUpdate }
  | { type: 'action_items_update'; payload: ActionItemsUpdate }
  | { type: 'contradiction_alert'; payload: ContradictionAlert }
  | { type: 'reply_suggestion'; payload: ReplySuggestion }
  | { type: 'custom_prompt_result'; payload: CustomPromptResult }
  | { type: 'reset' };

const initialState: MeetingState = {
  segments: [],
  summary: '',
  coveredUntil: 0,
  actionItems: [],
  contradictions: [],
  replySuggestions: null,
  customPromptResults: [],
};

function meetingReducer(state: MeetingState, action: MeetingAction): MeetingState {
  switch (action.type) {
    case 'transcript_segment':
      return { ...state, segments: [...state.segments, action.payload] };

    case 'summary_update':
      return {
        ...state,
        summary: action.payload.summary,
        coveredUntil: action.payload.covered_until,
      };

    case 'action_items_update':
      return { ...state, actionItems: action.payload.items };

    case 'contradiction_alert':
      return { ...state, contradictions: [...state.contradictions, action.payload] };

    case 'reply_suggestion':
      return { ...state, replySuggestions: action.payload };

    case 'custom_prompt_result':
      return {
        ...state,
        customPromptResults: [...state.customPromptResults, action.payload],
      };

    case 'reset':
      return initialState;

    default:
      return state;
  }
}

export function useMeetingState() {
  const [state, dispatch] = useReducer(meetingReducer, initialState);

  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case 'transcript_segment':
          dispatch({ type: 'transcript_segment', payload: msg as TranscriptSegment });
          break;
        case 'summary_update':
          dispatch({ type: 'summary_update', payload: msg as SummaryUpdate });
          break;
        case 'action_items_update':
          dispatch({ type: 'action_items_update', payload: msg as ActionItemsUpdate });
          break;
        case 'contradiction_alert':
          dispatch({ type: 'contradiction_alert', payload: msg as ContradictionAlert });
          break;
        case 'reply_suggestion':
          dispatch({ type: 'reply_suggestion', payload: msg as ReplySuggestion });
          break;
        case 'custom_prompt_result':
          dispatch({ type: 'custom_prompt_result', payload: msg as CustomPromptResult });
          break;
      }
    } catch {
      // ignore non-JSON messages
    }
  }, []);

  const reset = useCallback(() => dispatch({ type: 'reset' }), []);

  return { state, handleMessage, reset };
}
