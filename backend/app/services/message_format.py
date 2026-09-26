"""Turning stored LangChain messages into what the chat client renders."""

from app.utils.helpers import extract_text


def format_chat_messages(raw_messages: list, active_model: str) -> list:
    """LangChain messages → the client's message dicts, with model attribution
    and web-search sources recovered from provider-specific metadata."""
    formatted = []

    # 1. First pass: Filter technical markers to ensure correct indexing
    meaningful_messages = []
    for m in raw_messages:
        content = (
            getattr(m, "content", "")
            if hasattr(m, "content")
            else (m.get("content", "") if isinstance(m, dict) else str(m))
        )
        # Skip technical system markers
        if "PREVIOUS CONTEXT SUMMARY:" in str(content):
            continue
        meaningful_messages.append(m)

    for i, msg in enumerate(meaningful_messages):
        role = "user"
        if hasattr(msg, "type"):
            role = "user" if msg.type == "human" else "assistant"
        elif isinstance(msg, dict):
            role = msg.get("role") or (
                "user" if msg.get("type") == "human" else "assistant"
            )

        content = (
            getattr(msg, "content", "")
            if hasattr(msg, "content")
            else (msg.get("content", "") if isinstance(msg, dict) else str(msg))
        )
        if not content and role != "assistant":
            continue

        # Heavy Duty Attribution Recovery
        msg_model = None

        # Priority 1: Direct name attribute
        msg_model = getattr(msg, "name", None)
        if msg_model and not isinstance(msg_model, str):
            msg_model = None

        # Priority 2: additional_kwargs
        if not msg_model and hasattr(msg, "additional_kwargs"):
            add_kwargs = getattr(msg, "additional_kwargs", {})
            if isinstance(add_kwargs, dict):
                msg_model = add_kwargs.get(
                    "model", add_kwargs.get("model_id")
                ) or add_kwargs.get("name")

        # Priority 3: response_metadata
        if not msg_model and hasattr(msg, "response_metadata"):
            resp_meta = getattr(msg, "response_metadata", {})
            if isinstance(resp_meta, dict):
                msg_model = resp_meta.get(
                    "model_name", resp_meta.get("model_id")
                ) or resp_meta.get("model")

        # Priority 4: Dictionary keys (for JSON serialized state)
        if not msg_model and isinstance(msg, dict):
            msg_model = (
                msg.get("name")
                or msg.get("model")
                or msg.get("additional_kwargs", {}).get("model_id")
                or msg.get("metadata", {}).get("active_peer")
            )

        # Context Fallback: Only the VERY LAST message in the meaningful list defaults to active_model
        if not msg_model:
            is_last = i == len(meaningful_messages) - 1
            if role == "assistant":
                msg_model = active_model if is_last else "assistant"
            else:
                msg_model = "user"

        # Extract sources if present
        sources = None
        if hasattr(msg, "additional_kwargs"):
            sources = getattr(msg, "additional_kwargs", {}).get("sources")
        if not sources and isinstance(msg, dict):
            sources = msg.get("additional_kwargs", {}).get("sources")

        # Native Grounding Metadata Extraction
        if not sources:
            extracted_sources = []

            # 1. Google Gemini Grounding (`groundingMetadata` in response_metadata or additional_kwargs)
            resp_meta = getattr(msg, "response_metadata", {})
            add_kwargs = getattr(msg, "additional_kwargs", {})

            gm = (
                resp_meta.get("groundingMetadata")
                or resp_meta.get("grounding_metadata")
                or add_kwargs.get("groundingMetadata")
                or add_kwargs.get("grounding_metadata")
            )
            if isinstance(gm, dict):
                # Handle both camelCase from raw API and snake_case from some wrappers
                chunks = gm.get("groundingChunks") or gm.get("grounding_chunks") or []
                for chunk in chunks:
                    web = chunk.get("web", {})
                    if not web:
                        # Fallback if structure is different
                        continue

                    uri = web.get("uri") or web.get("url")
                    title = web.get("title") or "Web Result"
                    if uri:
                        extracted_sources.append({"text": title, "filename": uri})

            # 2. OpenAI & Anthropic Native Search Extraction
            # Models might return `content_blocks` (OpenAI Python SDK) or list-based `content`
            c_blocks = []
            if hasattr(msg, "content_blocks"):
                c_blocks = msg.content_blocks
            elif hasattr(msg, "content") and isinstance(msg.content, list):
                c_blocks = msg.content
            elif isinstance(msg, dict) and isinstance(msg.get("content"), list):
                c_blocks = msg["content"]

            for block in c_blocks:
                if isinstance(block, dict) and block.get("type") in (
                    "text",
                    "server_tool_result",
                ):
                    # OpenAI uses 'annotations'
                    if "annotations" in block:
                        for ann in block["annotations"]:
                            if ann.get("url"):
                                extracted_sources.append(
                                    {
                                        "text": ann.get("title", "Web Source"),
                                        "filename": ann.get("url"),
                                    }
                                )
                    # Anthropic or general citation array fallback
                    # Check for 'citations' (plural) or 'citation' (singular)
                    citations = block.get("citations") or block.get("citation")
                    if citations:
                        if isinstance(citations, dict):
                            citations = [citations]

                        if isinstance(citations, list):
                            for cit in citations:
                                if isinstance(cit, dict):
                                    url = (
                                        cit.get("document_url")
                                        or cit.get("url")
                                        or "Web Search"
                                    )
                                    title = (
                                        cit.get("document_title")
                                        or cit.get("title")
                                        or cit.get("source_name")
                                        or "Web Source"
                                    )
                                    extracted_sources.append(
                                        {
                                            "text": title,
                                            "filename": url,
                                        }
                                    )

            if extracted_sources:
                # Deduplicate by URL
                unique_sources = []
                seen = set()
                for s in extracted_sources:
                    if s["filename"] not in seen:
                        seen.add(s["filename"])
                        unique_sources.append(s)
                sources = unique_sources

        formatted.append(
            {
                "role": role,
                "content": extract_text(content, wrap_thinking=True),
                "type": role,
                "model": msg_model,
                "sources": sources,
            }
        )
    return formatted
