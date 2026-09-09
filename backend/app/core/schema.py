from typing import Annotated, Dict, List, Optional, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class CrucibleState(TypedDict):
    # Core data: messages is managed by add_messages for history
    messages: Annotated[List[BaseMessage], add_messages]

    # Thesis/Briefing Note for context management
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

    # Immediate Session Documents (non-RAG)
    documents: Optional[Dict[str, str]]
