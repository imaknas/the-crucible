from typing import Annotated, Any, Dict, List, Optional, TypedDict
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph.message import add_messages

from app.utils.helpers import extract_text


class CrucibleState(TypedDict):
    # Core data: messages is managed by add_messages for history
    messages: Annotated[List[BaseMessage], add_messages]

    # Legacy: the rolling thesis synthesis_node used to rewrite every turn.
    # Old checkpoints carry it; nothing writes or reads it any more.
    current_thesis: str

    # Control flow / Multi-model alignment
    active_peer: str  # e.g., "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"

    # UI/logic toggles
    toggles: Dict[str, bool]  # e.g., {"strict_logic": True}

    # Tree navigation / Branching metadata
    parent_id: Optional[str]
    branch_name: str

    # Deliberation mode trigger
    is_deliberation: bool

    # RAG Context
    retrieved_chunks: Optional[List[Dict[str, str]]]

    # Attached documents (non-RAG) in this turn's context: filenames only;
    # the content is in the thread's document store (services/documents.py).
    attached_documents: Optional[List[str]]

    # Legacy: attached documents' full content, as checkpoints written
    # before the store carry it. New turns write {}.
    documents: Optional[Dict[str, str]]


# ─── Context summaries ─────────────────────────────────────────────
# summarize_history appends a system message holding the summary. It is
# recognised by a flag on the message, not by its text: a user message or an
# attached document that merely quotes the marker must never be taken for a
# summary (sanitize_messages drops everything before one).
SUMMARY_MARKER = "PREVIOUS CONTEXT SUMMARY:"
SUMMARY_FLAG = "crucible_summary"


def summary_message(text: str) -> SystemMessage:
    """The system message summarize_history writes."""
    return SystemMessage(
        content=f"{SUMMARY_MARKER} {text}",
        additional_kwargs={SUMMARY_FLAG: True},
    )


def _field(message: Any, name: str) -> Any:
    if isinstance(message, dict):
        return message.get(name)
    return getattr(message, name, None)


def is_summary_message(message: Any) -> bool:
    """Whether `message` (a LangChain message or its dict form) is a summary
    written by summarize_history.

    Only system messages qualify. Summaries written before the flag existed
    carry no flag but always start with the marker, so an unflagged system
    message counts when its text starts with it; the drafting system prompt,
    which embeds attached documents and RAG chunks, never does.
    """
    role = _field(message, "type") or _field(message, "role")
    if role != "system":
        return False
    if (_field(message, "additional_kwargs") or {}).get(SUMMARY_FLAG):
        return True
    return extract_text(_field(message, "content") or "").lstrip().startswith(SUMMARY_MARKER)


def summary_text(message: Any) -> str:
    """A summary message's text without the marker."""
    text = extract_text(_field(message, "content") or "").lstrip()
    return text[len(SUMMARY_MARKER):].strip() if text.startswith(SUMMARY_MARKER) else text.strip()
