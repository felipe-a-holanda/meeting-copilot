from pydantic import BaseModel
from typing import Literal, Optional


# === Audio Pipeline → Frontend ===

class TranscriptSegment(BaseModel):
    """A single transcribed segment with speaker info."""
    type: Literal["transcript_segment"] = "transcript_segment"
    speaker: str
    text: str
    timestamp_start: float
    timestamp_end: float
    language: str = "pt"
    is_partial: bool = False


# === Reasoning Engine → Frontend ===

class SummaryUpdate(BaseModel):
    type: Literal["summary_update"] = "summary_update"
    summary: str
    covered_until: float


class ActionItem(BaseModel):
    id: str
    description: str
    assignee: Optional[str] = None
    source_timestamp: float
    status: Literal["new", "updated", "completed"] = "new"


class ActionItemsUpdate(BaseModel):
    type: Literal["action_items_update"] = "action_items_update"
    items: list[ActionItem]


class ContradictionAlert(BaseModel):
    type: Literal["contradiction_alert"] = "contradiction_alert"
    description: str
    statement_a: str
    statement_a_timestamp: float
    statement_b: str
    statement_b_timestamp: float
    severity: Literal["low", "medium", "high"]


class ReplySuggestion(BaseModel):
    type: Literal["reply_suggestion"] = "reply_suggestion"
    suggestions: list[str]
    context: str
    triggered_by: Literal["auto", "manual"]


class CustomPromptResult(BaseModel):
    type: Literal["custom_prompt_result"] = "custom_prompt_result"
    prompt: str
    result: str
    timestamp: float


# === Frontend → Backend ===

class RequestReplySuggestion(BaseModel):
    type: Literal["request_reply"] = "request_reply"
    context_hint: Optional[str] = None


class CustomPromptRequest(BaseModel):
    type: Literal["custom_prompt"] = "custom_prompt"
    prompt: str
