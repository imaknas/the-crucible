from typing import Annotated, Dict, List, Optional, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class CrucibleState(TypedDict):
    # Core data: messages is managed by add_messages for history
    messages: Annotated[List[BaseMessage], add_messages]

    # Thesis/Briefing Note for context management
    current_thesis: str

    # Control flow / Multi-model alignment
    active_peer: str  # e.g., "gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro"

    # UI/logic toggles
    toggles: Dict[str, bool]  # e.g., {"strict_logic": True}

    # Tree navigation / Branching metadata
    parent_id: Optional[str]
    branch_name: str

    # Deliberation mode trigger
    is_deliberation: bool
