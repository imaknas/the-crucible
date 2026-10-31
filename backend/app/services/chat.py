"""One chat turn, independent of how it is delivered.

api/chat.py drives these over REST and WebSockets; nothing here knows about
either. A turn always forks from an explicit parent checkpoint and is tagged
with a run id (see services/runs.py), so parallel models in one turn stay on
their own branches.
"""

from typing import Any, AsyncIterator, Dict, Mapping, Optional, Sequence

from langchain_core.messages import HumanMessage

from app.services.context import DEFAULT_CONTEXT, ContextSettings
from app.services.documents import attach_documents
from app.services.recall import INTERNAL_TAG
from app.services.runs import TURN_KIND_KEY, TURN_KINDS, final_state_of_run, tag_run, tag_turn_kind, thread_config
from app.utils.helpers import clean_string, extract_text

MAX_PROMPT_CHARS = 100_000
TITLE_CHARS = 40


def build_turn_input(
    state_values: Mapping[str, Any],
    *,
    message: Optional[str],
    model: str,
    toggles: Optional[Mapping[str, bool]] = None,
    document_names: Sequence[str] = (),
    is_deliberation: bool = False,
    turn_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """The graph input for one model's turn, given the parent's state values.

    A special turn's prompt (a synthesis request) carries its kind in the
    message itself, so every reader of the path can hide it
    (tree.is_synthesis_prompt), not only readers of checkpoint metadata.

    The turn's attached documents are named, not included: their content is
    saved per thread (services/documents.py). Exactly the named ones are in
    context, so a turn sent without documents has none. `documents` (their
    content, as older checkpoints carry it) is reset so such a parent stops
    handing its copy down. Empty prompts get a stand-in: Anthropic rejects
    empty content.
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

    message = (
        HumanMessage(content=prompt, additional_kwargs={TURN_KIND_KEY: turn_kind})
        if turn_kind in TURN_KINDS
        else ("user", prompt)
    )
    return {
        "active_peer": model,
        "toggles": {**state_values.get("toggles", {}), **(toggles or {})},
        "is_deliberation": is_deliberation,
        "attached_documents": list(document_names),
        "documents": {},
        "messages": [message],
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
    context: ContextSettings = DEFAULT_CONTEXT,
    turn_kind: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Run one model's turn. Yields ``token`` events, then one ``end`` event
    carrying the new checkpoint id, the reply's text and the path's messages.
    Raises on failure.

    ``turn_kind="synthesis"`` tags the turn's checkpoints, so the tree and the
    transcript can show the reply as a synthesis rather than another answer."""
    config = context.apply(thread_config(thread_id, parent_checkpoint_id))
    run_id = tag_run(config)
    tag_turn_kind(config, turn_kind)
    document_names = await attach_documents(config, documents)
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
        document_names=document_names,
        is_deliberation=is_deliberation,
        turn_kind=turn_kind,
    )

    async for event in graph_app.astream_events(turn_input, config, version="v2", exclude_tags=[INTERNAL_TAG]):
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
        "content": reply_text(final),
        "messages": await path_messages(graph_app, final),
    }


def reply_text(state) -> str:
    """The text of the last reply in a checkpoint's messages ("" if none)."""
    messages = (state.values or {}).get("messages", []) if state else []
    last_ai = next((m for m in reversed(messages) if getattr(m, "type", "") == "ai"), None)
    return extract_text(last_ai.content) if last_ai is not None else ""
