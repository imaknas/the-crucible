import re
from typing import Any, List


def extract_text(content: Any, wrap_thinking: bool = False) -> str:
    """Safely extract string text from potentially structured content.

    Handles Gemini/Anthropic's list-of-dicts format, raw dicts,
    and standard string content. Explicitly extracts "text" blocks.
    If wrap_thinking is True, converts "thinking" blocks to <think> tags.
    """
    raw_text = ""
    if isinstance(content, str):
        raw_text = clean_string(content)
    elif isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                # Standard text block
                if block.get("type") == "text":
                    parts.append(clean_string(str(block.get("text") or "")))
                # Anthropic/Native thinking block
                elif block.get("type") == "thinking" or "thinking" in block:
                    think_text = block.get("thinking") or block.get("text") or ""
                    if wrap_thinking:
                        parts.append(
                            f"<think>\n{clean_string(str(think_text))}\n</think>"
                        )
                    else:
                        parts.append(clean_string(str(think_text)))
                # Handle cases where type is missing but text is present
                elif "text" in block:
                    parts.append(clean_string(str(block.get("text") or "")))
            else:
                parts.append(clean_string(str(block)))
        raw_text = "".join(parts)
    elif isinstance(content, dict):
        if content.get("type") == "text":
            raw_text = clean_string(str(content.get("text") or ""))
        elif content.get("type") == "thinking":
            think_text = content.get("thinking") or content.get("text") or ""
            if wrap_thinking:
                raw_text = f"<think>\n{clean_string(str(think_text))}\n</think>"
            else:
                raw_text = clean_string(str(think_text))
        else:
            raw_text = clean_string(str(content.get("text") or ""))
    else:
        raw_text = clean_string(str(content or ""))

    # Strip <metadata>, <confidence>, <...>, and other tag-like blocks entirely before returning to UI
    text = re.sub(
        r"<(?:metadata|confidence|\.\.\.)>[\s\S]*?</(?:metadata|confidence|\.\.\.)>",
        "",
        raw_text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<(?:metadata|confidence|\.\.\.)>[\s\S]*$", "", text, flags=re.IGNORECASE
    )  # Unclosed

    # Strip legacy plain-text confidence blocks and specific metadata markers at the end
    # We avoid common words like "理由" (Reason) alone to prevent accidental content loss.
    # We search the tail for "Confidence: X%" or specific "Confidence Explanation:" patterns.
    suffix_len = 500
    if len(text) > suffix_len:
        prefix = text[:-suffix_len]
        suffix = text[-suffix_len:]
        suffix = re.sub(
            r"(?:Confidence|信心評估|信心說明|信心程度)\s*[:：].*$",
            "",
            suffix,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = prefix + suffix
    else:
        text = re.sub(
            r"(?:Confidence|信心評估|信心說明|信心程度)\s*[:：].*$",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    return text.strip()


def get_preview_text(content: str, max_length: int = 50) -> str:
    """Creates a clean, short preview by stripping tags and MD."""
    if not content:
        return ""

    # 1. Strip <think> blocks entirely for previews
    clean = re.sub(r"<think>[\s\S]*?</think>", "", content, flags=re.IGNORECASE)
    clean = re.sub(r"<think>[\s\S]*$", "", clean, flags=re.IGNORECASE)  # Unclosed tags

    # 2. Strip standard Markdown artifacts
    clean = re.sub(r"[#*`_~\[\]()]", "", clean)

    # 3. Collapse whitespace
    clean = " ".join(clean.split())

    if len(clean) <= max_length:
        return clean
    return (
        clean[:max_length].rsplit(" ", 1)[0] + "..."
        if " " in clean[:max_length]
        else clean[:max_length] + "..."
    )


def clean_string(s: Any) -> str:
    """Normalize string, stripping null bytes and non-printable noise."""
    if s is None:
        return ""
    s_val = str(s)
    # Remove null bytes which can crash some JSON serializers/LLM gateways
    s_val = s_val.replace("\x00", "")
    return s_val
