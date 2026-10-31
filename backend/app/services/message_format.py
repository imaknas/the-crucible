"""What a stored LangChain message says about itself: who wrote it, and the
web sources it cites.

Every reader of messages (the transcript, the summarizer, the CLI and MCP)
asks these two functions; each used to carry its own copy, and they drifted
(only one of three extracted native search citations).
"""

from typing import Any, Dict, List, Optional


def message_model(msg: Any) -> Optional[str]:
    """The model id a message records as its author, or None.

    Providers put it in different places: the message's `name` (set by the
    graph), `additional_kwargs`, `response_metadata`, or the keys of a
    serialized dict."""
    name = getattr(msg, "name", None)
    if isinstance(name, str) and name:
        return name
    extra = getattr(msg, "additional_kwargs", None)
    if isinstance(extra, dict):
        found = extra.get("model", extra.get("model_id")) or extra.get("name")
        if found:
            return found
    meta = getattr(msg, "response_metadata", None)
    if isinstance(meta, dict):
        found = meta.get("model_name", meta.get("model_id")) or meta.get("model")
        if found:
            return found
    if isinstance(msg, dict):
        return (
            msg.get("name")
            or msg.get("model")
            or msg.get("additional_kwargs", {}).get("model_id")
            or msg.get("metadata", {}).get("active_peer")
        )
    return None


def message_sources(msg: Any) -> Optional[List[Dict[str, str]]]:
    """The web sources a reply cites as [{text, filename}] (filename is the
    URL), or None: sources the app stored, else the provider's own grounding
    (Gemini groundingMetadata, OpenAI annotations, Anthropic citations)."""
    extra = getattr(msg, "additional_kwargs", None)
    if not isinstance(extra, dict):
        extra = msg.get("additional_kwargs", {}) if isinstance(msg, dict) else {}
    if extra.get("sources"):
        return extra["sources"]

    found: List[Dict[str, str]] = []
    meta = getattr(msg, "response_metadata", None) or {}
    grounding = (
        meta.get("groundingMetadata") or meta.get("grounding_metadata")
        or extra.get("groundingMetadata") or extra.get("grounding_metadata")
    )
    if isinstance(grounding, dict):
        for chunk in grounding.get("groundingChunks") or grounding.get("grounding_chunks") or []:
            web = chunk.get("web") or {}
            uri = web.get("uri") or web.get("url")
            if uri:
                found.append({"text": web.get("title") or "Web Result", "filename": uri})

    content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
    blocks = getattr(msg, "content_blocks", None) or (content if isinstance(content, list) else [])
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") not in ("text", "server_tool_result"):
            continue
        for ann in block.get("annotations") or []:
            if isinstance(ann, dict) and ann.get("url"):
                found.append({"text": ann.get("title", "Web Source"), "filename": ann["url"]})
        citations = block.get("citations") or block.get("citation")
        if isinstance(citations, dict):
            citations = [citations]
        for cit in citations if isinstance(citations, list) else []:
            if isinstance(cit, dict):
                found.append({
                    "text": cit.get("document_title") or cit.get("title") or cit.get("source_name") or "Web Source",
                    "filename": cit.get("document_url") or cit.get("url") or "Web Search",
                })

    unique = list({s["filename"]: s for s in found}.values())
    return unique or None
