"""Arena and synthesis runs, and the entry points the CLI and the MCP server share.

Every turn here is chat.stream_turn, the same turn the web UI runs over its
socket, so a feature of a turn (attached documents, Deliberation, a branch
point, a tagged synthesis) exists for every client at once.
"""

import asyncio
import sys
from contextlib import asynccontextmanager, redirect_stdout
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional, Sequence, Tuple

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.registry import DEFAULT_ARENA_MODELS, FAMILY_META, MODEL_REGISTRY, display_name
from app.core import database as db
from app.core.storage import current_storage
from app.llm import has_credentials
from app.services.chat import node_checkpoint, stream_turn, thread_state_map
from app.services.graph import workflow
from app.services.metrics import message_metrics, snapshot_day
from app.services.context import DEFAULT_CONTEXT, ContextSettings
from app.services.synthesis import (
    INDEPENDENT,
    Component,
    build_synthesis_prompt,
    component_request,
    parse_components,
    synthesis_framing,
)
from app.services.runs import (
    SYNTHESIS_MODE_KEY,
    SYNTHESIS_QUESTION_KEY,
    SYNTHESIS_TURN,
    TURN_ID_KEY,
    fork_point,
    new_turn_id,
    thread_config,
)
from app.utils.helpers import extract_text

# Overall budget for one arena turn; models still running after it are
# cancelled and reported as timed out.
ARENA_TIMEOUT_SECONDS = 300


def stdout_to_stderr():
    """Send the graph's diagnostic print() output to stderr.

    The nodes log with print(); on stdout that corrupts CLI JSON output and,
    worse, the MCP stdio protocol stream.
    """
    return redirect_stdout(sys.stderr)


@asynccontextmanager
async def open_graph():
    """A compiled graph on the shared SQLite checkpointer, closed on exit."""
    db.init_db()
    async with AsyncSqliteSaver.from_conn_string(current_storage().db_path) as saver:
        await saver.setup()
        yield workflow.compile(checkpointer=saver)


# ─── Models ──────────────────────────────────────────────────────


def key_available(model_id: str) -> bool:
    return has_credentials(model_id)


def resolve_models(models: Optional[List[str]] = None) -> List[str]:
    """Validate explicitly requested models, or pick defaults that have keys.

    Raises ValueError with a message meant for the caller (CLI user or agent).
    """
    if models:
        unknown = [m for m in models if m not in MODEL_REGISTRY]
        if unknown:
            current = [m for m, cfg in MODEL_REGISTRY.items() if cfg.get("desc") != "Legacy"]
            raise ValueError(
                f"Invalid model(s): {', '.join(unknown)}. "
                f"Available: {', '.join(current)} (list them with `crucible models` / list_models)."
            )
        keyless = [m for m in models if not key_available(m)]
        if keyless:
            raise ValueError(f"No API key configured for: {', '.join(keyless)}")
        return list(dict.fromkeys(models))

    chosen = [m for m in DEFAULT_ARENA_MODELS if m in MODEL_REGISTRY and key_available(m)]
    if not chosen:
        chosen = [m for m in MODEL_REGISTRY if key_available(m)][:1]
    if not chosen:
        raise ValueError(
            "No API keys found. Set at least one of: "
            + ", ".join(meta["env_key"] for meta in FAMILY_META.values())
        )
    return chosen


def list_models(day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every registered model: id, name, family, whether it is kept only for
    old threads (legacy), whether its key is set, whether it can search the
    web, its context window as the provider reports it, and its price in USD
    per million tokens on ``day`` (default: today; from the providers'
    pricing pages, catalog/prices.py; None for an unpriced model)."""
    import datetime

    from app.catalog import PriceBook, load_catalog, load_prices

    try:
        catalog = load_catalog()
    except Exception:
        catalog = None
    prices = PriceBook(load_prices(), day or datetime.date.today().isoformat())
    return [
        {
            "id": model_id,
            "name": cfg.get("name", model_id),
            "family": cfg.get("family"),
            "legacy": cfg.get("desc") == "Legacy",
            "key_available": key_available(model_id),
            "native_search": bool(cfg.get("native_search")),
            "context_window": _context_window(catalog, model_id),
            "price_per_mtok": _price(prices, model_id),
        }
        for model_id, cfg in MODEL_REGISTRY.items()
    ]


def _price(prices, model_id: str) -> Optional[Dict[str, Optional[float]]]:
    price = prices.price(model_id)
    return {"input": price.input, "output": price.output, "cached_input": price.cached_input} if price else None


def _context_window(catalog, model_id: str) -> Optional[int]:
    entry = catalog.get(model_id.lower()) if catalog is not None else None
    return entry.input_limit if entry is not None else None


# ─── One model's turn ────────────────────────────────────────────


async def model_turn(
    graph_app,
    thread_id: str,
    parent_checkpoint_id: Optional[str],
    model: str,
    prompt: Optional[str],
    toggles: Optional[Mapping[str, bool]] = None,
    context: ContextSettings = DEFAULT_CONTEXT,
    *,
    documents: Optional[Mapping[str, str]] = None,
    document_names: Optional[Sequence[str]] = None,
    is_deliberation: bool = False,
    turn_kind: Optional[str] = None,
    turn_id: Optional[str] = None,
    turn_note: Optional[Mapping[str, str]] = None,
    joins_turn: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """chat.stream_turn as model-tagged events: ``token`` {model, token}, then
    ``end`` {model, content, checkpoint_id, error, turn_id,
    attached_documents, retrieved, notices, metrics}. Raises on failure."""
    async for event in stream_turn(
        graph_app,
        thread_id,
        parent_checkpoint_id,
        message=prompt,
        model=model,
        toggles=toggles,
        documents=documents,
        document_names=document_names,
        is_deliberation=is_deliberation,
        context=context,
        turn_kind=turn_kind,
        turn_id=turn_id,
        turn_note=turn_note,
        with_path=False,
        joins_turn=joins_turn,
    ):
        if event["type"] == "token":
            yield {"type": "token", "model": model, "token": event["token"]}
        elif event["type"] == "end":
            yield {**event, "model": model, "error": None}


class TurnStart:
    """Where each model's turn forks from.

    ``parents`` names a checkpoint per model; any other model forks from
    ``default``. ``new_thread`` says the thread had no checkpoints."""

    def __init__(self, default: str, parents: Optional[Mapping[str, str]] = None, new_thread: bool = False):
        self.default = default
        self.parents = dict(parents or {})
        self.new_thread = new_thread

    def parent_for(self, model: str) -> str:
        return self.parents.get(model, self.default)


async def turn_start(
    graph_app,
    thread_id: str,
    checkpoint_id: Optional[str] = None,
    after_debate: Optional[str] = None,
) -> TurnStart:
    """Where a turn forks from:
    - ``checkpoint_id``: every model from there (it must exist);
    - ``after_debate``: the record of that finished debate on this thread
      (debate.continue_from_debate), or the newest turn after it;
    - neither: each model from its own reply in the latest turn, so models
      that answered side by side keep their own conversations; a model with
      no reply there (newly added, or it failed) from the latest answer.
    """
    if after_debate:
        if checkpoint_id:
            raise ValueError("Pass a checkpoint or a debate to continue, not both.")
        from app.services.debate import continue_from_debate

        session = db.get_debate_session(after_debate)
        if not session:
            raise ValueError(f"Debate session {after_debate} not found.")
        if session["parent_thread_id"] != thread_id:
            raise ValueError(f"Debate session {after_debate} belongs to thread {session['parent_thread_id']}, not {thread_id}.")
        record = await continue_from_debate(graph_app, after_debate)
        return TurnStart(await _latest_below(graph_app, thread_id, record))
    if checkpoint_id:
        parent, new_thread = await fork_point(graph_app, thread_id, checkpoint_id)
        return TurnStart(parent, new_thread=new_thread)
    head, new_thread = await fork_point(graph_app, thread_id, None)
    if new_thread:
        return TurnStart(head, new_thread=True)
    states = await thread_state_map(graph_app, thread_id)
    # The tree's id for the head, like every other id handed out.
    head = node_checkpoint(states[head], states) if head in states else head
    return TurnStart(head, await _latest_turn_replies(graph_app, thread_id, head))


async def _latest_turn_replies(graph_app, thread_id: str, head: str) -> Dict[str, str]:
    """{model: its reply's checkpoint} for the turn the head belongs to.
    Threads written before turns were tagged have no turn: empty."""
    states = await thread_state_map(graph_app, thread_id)
    head_state = states.get(head)
    turn = (getattr(head_state, "metadata", None) or {}).get(TURN_ID_KEY)
    if not turn:
        return {}
    return {model: node_checkpoint(snapshot, states) for model, snapshot in _turn_replies(states, turn).items()}


def _ends_on_reply(snapshot) -> bool:
    messages = (snapshot.values or {}).get("messages", []) if snapshot else []
    return bool(messages) and getattr(messages[-1], "type", "") == "ai"


def _turn_replies(states: Mapping[str, Any], turn: str) -> Dict[str, Any]:
    """{model: the final checkpoint of its newest reply} in turn ``turn``,
    syntheses left out, in the order the models answered (so "the first
    answer" is stable)."""
    from app.services.tree import is_synthesis_reply

    newest: Dict[str, Any] = {}
    for snapshot in states.values():
        if (snapshot.metadata or {}).get(TURN_ID_KEY) != turn or snapshot.next:
            continue
        if not _ends_on_reply(snapshot) or is_synthesis_reply(snapshot):
            continue
        model = snapshot.values.get("active_peer")
        if model and (model not in newest or (snapshot.created_at or "") > (newest[model].created_at or "")):
            newest[model] = snapshot
    return dict(sorted(newest.items(), key=lambda item: item[1].created_at or ""))


class TurnJoin:
    """One more model's answer to a turn already answered (join_point):
    the turn, where the model forks, and the question as the turn's models
    were asked it."""

    def __init__(self, turn_id: str, parent: str, message: str, *, is_deliberation: bool = False,
                 document_names: Sequence[str] = (), answered: Sequence[str] = ()):
        self.turn_id = turn_id
        # The checkpoint the turn's question was asked from, on the branch of
        # the reply the join was named by (or the turn's first reply).
        self.parent = parent
        self.message = message
        self.is_deliberation = is_deliberation
        # The files the turn's question went with.
        self.document_names = list(document_names)
        # The models that answered the turn, in the order they did.
        self.answered = list(answered)


async def join_point(
    graph_app,
    thread_id: str,
    turn: str,
    model: str,
    parent_checkpoint_id: Optional[str] = None,
) -> TurnJoin:
    """Where ``model`` answers a turn the thread already has, without asking
    the turn's other models again.

    ``turn`` is the turn's id, or the checkpoint of one of its replies: the
    new answer then goes on that reply's branch (beside the reply on screen),
    else on the branch of the turn's first reply. It forks from where that
    branch asked the question, with the question's own text, Deliberation
    and attached files; ``parent_checkpoint_id`` pins another fork point.
    The run is tagged with the turn's id (one more of its answers) and as a
    join (runs.JOINED_KEY: the thread's head passes over it).

    ValueError, with a message for the caller: an unknown model or one
    without a key, a turn the thread doesn't have, a reply written before
    turns were recorded, a synthesis, and a model that already answered the
    turn.
    """
    resolve_models([model])
    states = await thread_state_map(graph_app, thread_id)
    anchor = states.get(turn)
    if anchor is not None:
        from app.services.tree import is_synthesis_reply

        if not _ends_on_reply(anchor):
            raise ValueError(f"Checkpoint {turn} is not a reply; name one of the turn's replies, or its turn id.")
        if is_synthesis_reply(anchor):
            raise ValueError("That reply is a synthesis; add a model to the turn whose answers it combines.")
        turn_id = (anchor.metadata or {}).get(TURN_ID_KEY)
        if not turn_id:
            raise ValueError(
                f"Reply {turn} was written before turns were recorded; ask the model from the question's "
                "checkpoint instead (--from / parent_checkpoint_id)."
            )
    else:
        turn_id = turn
    replies = _turn_replies(states, turn_id)
    if not replies:
        raise ValueError(f"Turn {turn} not found on thread {thread_id}.")
    if model in replies:
        raise ValueError(f"{display_name(model)} already answered this turn.")
    anchor = anchor if anchor is not None else next(iter(replies.values()))

    asked = _question_of(anchor, states)
    if asked is None:
        raise ValueError(f"No question precedes the replies of turn {turn_id}.")
    if parent_checkpoint_id:
        parent, _ = await fork_point(graph_app, thread_id, parent_checkpoint_id)
    else:
        parent = node_checkpoint(states[asked.parent_config["configurable"]["checkpoint_id"]], states)
    # As the question was asked: the draft resets is_deliberation on the reply.
    values = asked.values or {}
    return TurnJoin(
        turn_id,
        parent,
        extract_text(asked.values["messages"][-1].content),
        is_deliberation=bool(values.get("is_deliberation")),
        document_names=values.get("attached_documents") or (),
        answered=list(replies),
    )


def _question_of(reply, states: Mapping[str, Any]):
    """The first checkpoint ending on the question ``reply`` answers (the
    tree's node for it), when it has a parent; None otherwise."""
    current = reply
    while current is not None and not _ends_on_question(current):
        parent = current.parent_config
        current = states.get(parent["configurable"]["checkpoint_id"]) if parent else None
    while current is not None and current.parent_config:
        parent = states.get(current.parent_config["configurable"]["checkpoint_id"])
        if parent is None or not _ends_on_question(parent):
            return current if parent is not None else None
        current = parent
    return None


async def _latest_below(graph_app, thread_id: str, checkpoint_id: str) -> str:
    """The thread head if it descends from ``checkpoint_id``, else the
    checkpoint itself: a second turn "after the debate" follows the first
    instead of branching beside it."""
    head, _ = await fork_point(graph_app, thread_id, None)
    states = await thread_state_map(graph_app, thread_id)
    current = states.get(head)
    while current is not None:
        if current.config["configurable"]["checkpoint_id"] == checkpoint_id:
            return node_checkpoint(states[head], states)
        parent = current.parent_config
        current = states.get(parent["configurable"]["checkpoint_id"]) if parent else None
    return checkpoint_id


# ─── Arena ───────────────────────────────────────────────────────


def _independent_synthesis_prompt(question: str, answers: List[Dict[str, Any]]) -> str:
    return build_synthesis_prompt(
        question, ((display_name(a["model"]), a["content"]) for a in answers), INDEPENDENT
    )


async def run_arena(
    graph_app,
    prompt: str,
    thread_id: str,
    models: Optional[List[str]] = None,
    toggles: Optional[Dict[str, Any]] = None,
    synthesizer: Optional[str] = None,
    timeout: float = ARENA_TIMEOUT_SECONDS,
    context: ContextSettings = DEFAULT_CONTEXT,
    *,
    parent_checkpoint_id: Optional[str] = None,
    after_debate: Optional[str] = None,
    documents: Optional[Mapping[str, str]] = None,
    document_names: Optional[Sequence[str]] = None,
    is_deliberation: bool = False,
    join_turn: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Ask every model the same question in parallel, then optionally synthesize.

    Events:
      start            {models, thread_id, parent_checkpoint_id, parents, new_thread, turn_id, prompt}
      token            {model, token}
      end              {model, content, checkpoint_id, error, attached_documents, retrieved, notices, metrics}
      synthesis_start  {model}
      synthesis_token  {model, token}
      synthesis        {model, content, checkpoint_id, error, metrics}

    ``metrics`` is the reply's time, tokens and cost (services/metrics.py);
    None for a model that failed.

    Where each model forks is turn_start(): ``parent_checkpoint_id``, the
    debate ``after_debate``, or each model's own latest reply.
    ``is_deliberation`` makes it a Deliberation turn: each model critically
    reviews the conversation, so it needs one. The synthesis is a separate,
    explicit model call over the answers, hung from the question they
    answered; it runs only when ``synthesizer`` is set and at least two
    models answered.

    ``join_turn`` (a turn id, or one of its replies' checkpoints) adds
    ``models`` to a turn the thread already has instead (join_point): they
    answer its question, from where it was asked, as more answers of that
    turn; the turn's other models are not asked again. It takes no prompt,
    debate, Deliberation (the turn's own applies) or synthesis.
    """
    if join_turn:
        if prompt and prompt.strip():
            raise ValueError("Adding a model to a turn asks the turn's own question; pass no prompt.")
        if after_debate or is_deliberation or synthesizer:
            raise ValueError("Adding a model to a turn takes no debate, Deliberation or synthesis.")
        if not models:
            raise ValueError("Name the model(s) to add to the turn.")
    models = resolve_models(models)
    if synthesizer:
        resolve_models([synthesizer])

    joins = False
    if join_turn:
        points = [await join_point(graph_app, thread_id, join_turn, m, parent_checkpoint_id) for m in models]
        first = points[0]
        prompt, is_deliberation, joins = first.message, first.is_deliberation, True
        if not documents and document_names is None:
            document_names = first.document_names
        turn_id = first.turn_id
        parents = {m: p.parent for m, p in zip(models, points)}
        start = TurnStart(first.parent, parents)
    else:
        start = await turn_start(graph_app, thread_id, parent_checkpoint_id, after_debate)
        if is_deliberation and start.new_thread:
            raise ValueError("Deliberation reviews a conversation; this thread has none yet.")
        turn_id = new_turn_id()
        parents = {m: start.parent_for(m) for m in models}
    yield {
        "type": "start", "models": models, "thread_id": thread_id, "parent_checkpoint_id": start.default,
        "parents": parents, "new_thread": start.new_thread, "turn_id": turn_id, "prompt": prompt,
    }

    queue: asyncio.Queue = asyncio.Queue()

    async def _produce(model: str):
        try:
            async for event in model_turn(graph_app, thread_id, parents[model], model, prompt, toggles, context,
                                          documents=documents, document_names=document_names,
                                          is_deliberation=is_deliberation, turn_id=turn_id, joins_turn=joins):
                await queue.put(event)
        except Exception as e:
            await queue.put({"type": "end", "model": model, "content": "", "checkpoint_id": None, "error": str(e)})

    tasks = [asyncio.create_task(_produce(m)) for m in models]
    answers: Dict[str, Dict[str, Any]] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while len(answers) < len(models):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if event["type"] == "end":
                answers[event["model"]] = event
            yield event
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    for model in models:
        if model not in answers:
            event = {"type": "end", "model": model, "content": "", "checkpoint_id": None, "error": f"timed out after {timeout:.0f}s"}
            answers[model] = event
            yield event

    usable = [answers[m] for m in models if not answers[m]["error"] and answers[m]["content"]]
    if not synthesizer or len(usable) < 2:
        return

    asked = await question_point(graph_app, thread_id, usable[0]["checkpoint_id"])
    async for event in _synthesize(graph_app, thread_id, asked, synthesizer, _independent_synthesis_prompt(prompt, usable), toggles, context):
        yield event


async def _synthesize(graph_app, thread_id, parent, synthesizer, synthesis_prompt, toggles, context=DEFAULT_CONTEXT,
                      note: Optional[Mapping[str, str]] = None):
    yield {"type": "synthesis_start", "model": synthesizer}
    try:
        async for event in model_turn(graph_app, thread_id, parent, synthesizer, synthesis_prompt, toggles, context,
                                      turn_kind=SYNTHESIS_TURN, turn_note=note):
            if event["type"] == "token":
                yield {"type": "synthesis_token", "model": synthesizer, "token": event["token"]}
            else:
                yield {**event, "type": "synthesis"}
    except Exception as e:
        yield {"type": "synthesis", "model": synthesizer, "content": "", "checkpoint_id": None, "error": str(e)}


async def collect(events: AsyncGenerator[Dict[str, Any], None]) -> Dict[str, Any]:
    """Drain a run_arena / synthesize_thread stream into one JSON-able result."""
    result: Dict[str, Any] = {"thread_id": None, "answers": {}, "synthesis": None}
    async for event in events:
        if event["type"] == "start":
            result["thread_id"] = event["thread_id"]
            result["parent_checkpoint_id"] = event["parent_checkpoint_id"]
        elif event["type"] == "end":
            result["answers"][event["model"]] = {k: event.get(k) for k in ("content", "checkpoint_id", "error", "metrics")}
        elif event["type"] == "synthesis":
            result["synthesis"] = {k: event.get(k) for k in ("model", "content", "checkpoint_id", "error", "metrics")}
    return result


# ─── Synthesize existing answers ─────────────────────────────────


async def latest_branch_answers(graph_app, thread_id: str) -> List[Dict[str, Any]]:
    """The final AI reply on every branch tip of a thread, oldest first.

    For an arena turn that is each model's answer; for a branched chat it is
    where each line of the conversation ended up.
    """
    from app.services.tree import load_thread_states

    states = await load_thread_states(graph_app, thread_id)
    parents = {
        s.parent_config["configurable"]["checkpoint_id"]
        for s in states
        if s.parent_config
    }
    answers: List[Dict[str, Any]] = []
    seen: set = set()
    for s in sorted(states, key=lambda s: s.created_at or ""):
        cid = s.config["configurable"]["checkpoint_id"]
        if cid in parents or s.next:
            continue
        last_ai = next(
            (m for m in reversed(s.values.get("messages", [])) if getattr(m, "type", "") == "ai"),
            None,
        )
        if last_ai is None:
            continue
        content = extract_text(last_ai.content)
        if not content or content in seen:
            continue
        seen.add(content)
        answers.append({
            "model": getattr(last_ai, "name", None) or s.values.get("active_peer") or "model",
            "content": content,
            "checkpoint_id": cid,
            "metrics": message_metrics(last_ai, day=snapshot_day(s)),
        })
    return answers


async def answer_at(graph_app, thread_id: str, checkpoint_id: str) -> Dict[str, Any]:
    """The reply a checkpoint ends on and the question it answered:
    {model, content, checkpoint_id, question, metrics}. Raises ValueError if there is none."""
    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    messages = (state.values or {}).get("messages", []) if state else []
    if not messages or getattr(messages[-1], "type", "") != "ai":
        raise ValueError(f"Checkpoint {checkpoint_id} on thread {thread_id} is not a reply.")
    last = messages[-1]
    question = next((extract_text(m.content) for m in reversed(messages) if getattr(m, "type", "") == "human"), "")
    return {
        "model": getattr(last, "name", None) or state.values.get("active_peer") or "model",
        "content": extract_text(last.content),
        "checkpoint_id": checkpoint_id,
        "question": question,
        "metrics": message_metrics(last, day=snapshot_day(state)),
    }


def _ends_on_question(state) -> bool:
    messages = (state.values or {}).get("messages", []) if state else []
    return bool(messages) and getattr(messages[-1], "type", "") == "human"


async def question_point(graph_app, thread_id: str, answer_checkpoint_id: str) -> str:
    """The checkpoint where the question a reply answers was asked: the
    tree's node for that question, which a synthesis of its answers hangs
    from, as in the web UI. The reply's own checkpoint if no question
    precedes it."""
    state = await graph_app.aget_state(thread_config(thread_id, answer_checkpoint_id))
    while state is not None and not _ends_on_question(state) and state.parent_config:
        state = await graph_app.aget_state(state.parent_config)
    if not _ends_on_question(state):
        return answer_checkpoint_id
    # The run writes several checkpoints ending on the question; the first is
    # the tree's node.
    while state.parent_config:
        parent = await graph_app.aget_state(state.parent_config)
        if not _ends_on_question(parent):
            break
        state = parent
    return state.config["configurable"]["checkpoint_id"]


def _labelled_answers(answers: Sequence[Mapping[str, Any]]) -> Tuple[str, List[Tuple[str, str]]]:
    """The question line and (label, content) pairs a synthesizer reads.
    Answers to one question are labelled by model; a selection across
    branches can answer several questions, so each label then says which. A
    model that appears twice is numbered."""
    questions = list(dict.fromkeys((a.get("question") or "").strip() for a in answers))
    names = [display_name(a["model"]) for a in answers]
    labels = [f"{n} #{names[:i + 1].count(n)}" if names.count(n) > 1 else n for i, n in enumerate(names)]
    if len(questions) == 1:
        return questions[0] or "(see the answers below)", list(zip(labels, (a["content"] for a in answers)))
    return (
        "(several questions: each answer is shown with the one it answered)",
        [(f"{label}, answering: {a.get('question') or '(no question)'}", a["content"]) for label, a in zip(labels, answers)],
    )


def synthesis_note(mode: str = "merge", question: Optional[str] = None) -> Dict[str, str]:
    """What a synthesis turn records about how it was asked for (runs.SYNTHESIS_MODE_KEY)."""
    note = {SYNTHESIS_MODE_KEY: mode}
    if mode == "ask" and question:
        note[SYNTHESIS_QUESTION_KEY] = question.strip()
    return note


async def synthesis_request(
    graph_app,
    thread_id: str,
    checkpoint_ids: Sequence[str],
    mode: str = "merge",
    *,
    keep: Sequence[str] = (),
    question: Optional[str] = None,
) -> str:
    """The prompt asking a model to synthesize the replies at
    ``checkpoint_ids``: merge them (answers written independently, as an
    arena turn's are), compare them, merge the components the reader kept
    (``keep``), or answer the reader's ``question`` about them (``mode``,
    synthesis.SYNTHESIS_MODES). ValueError for fewer than two answers, an
    unknown mode, or a mode missing what it needs."""
    framing = synthesis_framing(mode, keep=keep, question=question)
    answers = [await answer_at(graph_app, thread_id, cid) for cid in dict.fromkeys(checkpoint_ids)]
    if len(answers) < 2:
        raise ValueError(f"Synthesis needs at least two answers; got {len(answers)}.")
    question_line, labelled = _labelled_answers(answers)
    return build_synthesis_prompt(question_line, labelled, framing)


async def answer_components(
    graph_app,
    thread_id: str,
    checkpoint_ids: Optional[Sequence[str]] = None,
    model: Optional[str] = None,
    *,
    factory=None,
) -> List[Component]:
    """The checklist to choose from before a "checklist" synthesis: the
    answers at ``checkpoint_ids`` (default: the answers to the latest
    question) split into components, each naming the answers that contain
    it. A helper call, not a turn: nothing is written to the thread.
    ``model`` writes the list (default: the first answer's model);
    ValueError if it lists none."""
    from langchain_core.messages import HumanMessage

    from app.llm import model_factory_from
    from app.services.recall import INTERNAL_TAG

    if checkpoint_ids:
        answers = [await answer_at(graph_app, thread_id, cid) for cid in dict.fromkeys(checkpoint_ids)]
    else:
        answers = await latest_turn_answers(graph_app, thread_id)
    if len(answers) < 2:
        raise ValueError(f"A checklist needs at least two answers; got {len(answers)}.")
    model = model or answers[0]["model"]
    resolve_models([model])
    question_line, labelled = _labelled_answers(answers)
    config = {"configurable": {"model_factory": factory}} if factory else {}
    llm = model_factory_from(config).chat(model, {})
    response = await llm.ainvoke([HumanMessage(content=component_request(question_line, labelled))],
                                 config={"tags": [INTERNAL_TAG]})
    return parse_components(extract_text(response.content))


async def latest_turn_answers(graph_app, thread_id: str) -> List[Dict[str, Any]]:
    """The answers to the thread's latest question: every model's reply in
    the turn the latest answer belongs to, syntheses left out. Threads
    written before turns were tagged: the latest answer on every branch that
    isn't a synthesis."""
    from app.services.tree import is_synthesis_reply

    head, new_thread = await fork_point(graph_app, thread_id, None)
    if new_thread:
        return []
    states = await thread_state_map(graph_app, thread_id)
    replies = await _latest_turn_replies(graph_app, thread_id, head)
    if replies:
        return [await answer_at(graph_app, thread_id, cid) for cid in replies.values()]
    return [
        a for a in await latest_branch_answers(graph_app, thread_id)
        if a["checkpoint_id"] not in states or not is_synthesis_reply(states[a["checkpoint_id"]])
    ]


async def synthesize_thread(
    graph_app,
    thread_id: str,
    synthesizer: Optional[str] = None,
    toggles: Optional[Dict[str, Any]] = None,
    context: ContextSettings = DEFAULT_CONTEXT,
    *,
    checkpoint_ids: Optional[Sequence[str]] = None,
    parent_checkpoint_id: Optional[str] = None,
    mode: str = "merge",
    keep: Sequence[str] = (),
    question: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Synthesize answers already on a thread: exactly the replies at
    ``checkpoint_ids`` (the web UI's "Synthesize answers"), by default the
    answers to the latest question (latest_turn_answers). Written beside
    them, from the question they answer (question_point), unless
    ``parent_checkpoint_id`` says where. ``synthesizer`` defaults to the
    first answer's model. ``mode``, ``keep`` and ``question`` (the reader's,
    for mode "ask") as in synthesis_request. Raises ValueError when there is
    nothing to synthesize or the mode lacks what it needs.
    """
    framing = synthesis_framing(mode, keep=keep, question=question)
    if checkpoint_ids:
        answers = [await answer_at(graph_app, thread_id, cid) for cid in dict.fromkeys(checkpoint_ids)]
    else:
        answers = await latest_turn_answers(graph_app, thread_id)
    if len(answers) < 2:
        raise ValueError(
            f"Synthesis needs at least two answers; {'got' if checkpoint_ids else f'thread {thread_id} has'} "
            f"{len(answers)}. Name them with their checkpoints."
        )
    synthesizer = synthesizer or answers[0]["model"]
    resolve_models([synthesizer])
    asked = answers[0].get("question") or await _latest_question(graph_app, thread_id)
    parent, _ = await fork_point(
        graph_app, thread_id,
        parent_checkpoint_id or await question_point(graph_app, thread_id, answers[0]["checkpoint_id"]),
    )
    yield {"type": "start", "models": [a["model"] for a in answers], "thread_id": thread_id,
           "parent_checkpoint_id": parent, "parents": {}, "new_thread": False, "turn_id": None}
    for a in answers:
        yield {"type": "end", "model": a["model"], "content": a["content"], "checkpoint_id": a["checkpoint_id"],
               "error": None, "metrics": a.get("metrics")}
    question_line, labelled = _labelled_answers([{**a, "question": a.get("question") or asked} for a in answers])
    prompt = build_synthesis_prompt(question_line, labelled, framing)
    async for event in _synthesize(graph_app, thread_id, parent, synthesizer, prompt, toggles, context,
                                   note=synthesis_note(mode, question)):
        yield event


async def _latest_question(graph_app, thread_id: str) -> str:
    state = await graph_app.aget_state(thread_config(thread_id))
    for m in reversed(state.values.get("messages", []) if state.values else []):
        if getattr(m, "type", "") == "human":
            return extract_text(m.content)
    return "(see the answers below)"


# ─── Reading threads ─────────────────────────────────────────────


async def thread_messages(graph_app, thread_id: str, checkpoint_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The conversation on one path (head by default), oldest first."""
    state = await graph_app.aget_state(thread_config(thread_id, checkpoint_id))
    if not state.values:
        raise ValueError(f"Thread {thread_id} not found.")
    from app.services.tree import is_synthesis_prompt

    out = []
    for m in state.values.get("messages", []):
        kind = getattr(m, "type", "")
        if kind not in ("human", "ai") or is_synthesis_prompt(m):
            continue
        out.append({
            "role": "user" if kind == "human" else "assistant",
            "model": getattr(m, "name", None) if kind == "ai" else None,
            "content": extract_text(m.content),
        })
    return out
