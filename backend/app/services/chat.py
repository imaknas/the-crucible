"""One chat turn, independent of how it is delivered.

api/chat.py drives these over REST and WebSockets; nothing here knows about
either. A turn always forks from an explicit parent checkpoint and is tagged
with a run id (see services/runs.py), so parallel models in one turn stay on
their own branches.
"""

from typing import Any, AsyncIterator, Dict, Mapping, Optional

from app.services.runs import final_state_of_run, tag_run, thread_config
from app.utils.helpers import clean_string, extract_text

MAX_PROMPT_CHARS = 100_000
TITLE_CHARS = 40


def build_turn_input(
    state_values: Mapping[str, Any],
    *,
    message: Optional[str],
    model: str,
    toggles: Optional[Mapping[str, bool]] = None,
    documents: Optional[Mapping[str, str]] = None,
    is_deliberation: bool = False,
) -> Dict[str, Any]:
    """The graph input for one model's turn, given the parent's state values.

    Documents travel in state rather than in the message, to keep history
    clean. Empty prompts get a stand-in: Anthropic rejects empty content.
    """
    text = clean_string(message or "")
    if len(text) > MAX_PROMPT_CHARS:
        text = text[:MAX_PROMPT_CHARS] + "\n\n[... truncated ...]"

    if text.strip():
        prompt = text
    elif is_deliberation:
        prompt = "Please review the conversation and provide your analysis."
    else:
        prompt = "Please continue."

    return {
        "active_peer": model,
        "toggles": {**state_values.get("toggles", {}), **(toggles or {})},
        "is_deliberation": is_deliberation,
        "documents": dict(documents or {}),
        "messages": [("user", prompt)],
    }


def auto_title(first_user_message: str) -> Optional[str]:
    """A thread title from its first message: first line, word-trimmed to 40 chars."""
    first_line = first_user_message.strip().split("\n")[0]
    if not first_line:
        return None
    if len(first_line) <= TITLE_CHARS:
        return first_line
    return first_line[:TITLE_CHARS].rsplit(" ", 1)[0] + "…"


async def path_messages(graph_app, final_state) -> list:
    """Client-ready messages on the path from the root to `final_state`.

    Walks parent checkpoints rather than reading final_state's own messages,
    which may be pruned by summarisation.
    """
    from app.services.tree import format_messages

    states: Dict[str, Any] = {}
    current = final_state
    base = current.config
    while current:
        cid = current.config.get("configurable", {}).get("checkpoint_id")
        if not cid:
            break
        states[cid] = current
        parent_id = (current.parent_config or {}).get("configurable", {}).get("checkpoint_id")
        if not parent_id or parent_id in states:
            break
        current = await graph_app.aget_state(
            {**base, "configurable": {**base["configurable"], "checkpoint_id": parent_id}}
        )
    return format_messages(final_state.config["configurable"]["checkpoint_id"], states)


async def stream_turn(
    graph_app,
    thread_id: str,
    parent_checkpoint_id: Optional[str],
    *,
    message: Optional[str],
    model: str,
    toggles: Optional[Mapping[str, bool]] = None,
    documents: Optional[Mapping[str, str]] = None,
    is_deliberation: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    """Run one model's turn. Yields ``token`` events, then one ``end`` event
    carrying the new checkpoint id and the path's messages. Raises on failure."""
    config = thread_config(thread_id, parent_checkpoint_id)
    run_id = tag_run(config)
    state = await graph_app.aget_state(config)

    current = state.values.get("messages", [])
    if current:
        from app.services.graph import count_tokens, get_token_limit

        print(f"[Context] Current Tokens: {count_tokens(current)}, Limit: {get_token_limit(model)}")

    turn_input = build_turn_input(
        state.values,
        message=message,
        model=model,
        toggles=toggles,
        documents=documents,
        is_deliberation=is_deliberation,
    )

    async for event in graph_app.astream_events(turn_input, config, version="v2"):
        if event.get("event") != "on_chat_model_stream":
            continue
        if event.get("metadata", {}).get("langgraph_node") != "draft":
            continue
        chunk = event.get("data", {}).get("chunk")
        if chunk is None or getattr(chunk, "content", None) is None:
            continue
        token = extract_text(chunk.content, strip=False)
        if token:
            yield {"type": "token", "token": token}

    final = await final_state_of_run(graph_app, thread_id, run_id)
    if final is None:
        raise RuntimeError(f"{model} finished without writing a checkpoint")
    yield {
        "type": "end",
        "checkpoint_id": final.config["configurable"]["checkpoint_id"],
        "messages": await path_messages(graph_app, final),
    }
