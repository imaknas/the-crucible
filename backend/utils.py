"""Shared utility functions for The Crucible backend."""

from typing import Any, List


def extract_text(content: Any) -> str:
    """Safely extract string text from potentially structured content.

    Handles Gemini/Anthropic's list-of-dicts format, raw dicts,
    and standard string content. Explicitly extracts "text" blocks
    and ignores technical signatures or "thinking" blocks if desired.
    """
    if isinstance(content, str):
        return clean_string(content)

    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                # Standard LangChain/Anthropic/Google text block
                if block.get("type") == "text":
                    parts.append(clean_string(str(block.get("text") or "")))
                # If no type, check for direct "text" key
                elif "text" in block and block.get("type") != "thinking":
                    parts.append(clean_string(str(block.get("text") or "")))
                # Note: We intentionally skip "thinking" blocks here for summaries
            else:
                parts.append(clean_string(str(block)))
        return "".join(parts)

    if isinstance(content, dict):
        # Handle single block dicts
        if content.get("type") == "text":
            return clean_string(str(content.get("text") or ""))
        val = content.get("text")
        if val:
            return clean_string(str(val))
        return ""

    return clean_string(str(content or ""))


def clean_string(s: Any) -> str:
    """Normalize string, stripping null bytes and non-printable noise."""
    if s is None:
        return ""
    s_val = str(s)
    # Remove null bytes which can crash some JSON serializers/LLM gateways
    s_val = s_val.replace("\x00", "")
    return s_val
