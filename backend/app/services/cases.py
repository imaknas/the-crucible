"""Saved cases: one turn kept whole, to re-run on today's models.

A case is a snapshot of a turn: its question, the conversation before it,
the documents it went with, the settings that shaped its answers, each
answer with its metrics, and the person's vote on them as it stood when the
case was saved. Everything is copied (core/database saved_cases), so a case
outlives its thread; the source thread and turn ids are a reference only.

A replay asks models the case's question again in a new thread seeded with
the case's history (runs.seed_thread), with its documents and settings,
through the one turn runner (arena.run_arena), and never writes to the
source thread. Each new answer is compared with the case's answer from the
same model, or, for a model the case doesn't have, with the answer the
person voted best. Replays are stored (case_replays) with their answers
copied, so a case shows its history of replays after their threads are gone.

The history is the messages exactly as the graph held them before the
question, on the branch of the reply the case was saved by (else the
turn's first answer, as arena.join_point picks): each model of a turn
continued its own conversation, so turn-mates' histories can differ. A
summary on that path is kept: the original answers were written from it
(a small-context model jumps to it), so leaving it out would compare new
answers written from the whole history with old ones written from a
summary. The replay's own compaction still decides whether to summarize
again.
"""

import asyncio
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from langchain_core.messages import messages_from_dict, messages_to_dict

from app.core import database as db
from app.core.database import ThreadDocumentStore
from app.core.schema import is_summary_message, summary_text
from app.registry import display_name
from app.services import arena, votes
from app.services.chat import auto_title, node_checkpoint, thread_state_map
from app.services.context import ContextSettings
from app.services.message_format import message_model
from app.services.metrics import turn_total
from app.services.runs import seed_thread
from app.services.textdiff import diff_texts
from app.utils.helpers import extract_text

TITLE_MAX_CHARS = 120
# Why a new answer is compared with the answer it is.
SAME_MODEL = "same_model"
VOTED_BEST = "voted_best"

Indexer = Callable[[str, str, str], Any]


def _utc(stamp: Optional[str]) -> Optional[str]:
    """A stored CURRENT_TIMESTAMP (UTC, no zone) as a timezone-aware ISO time."""
    if isinstance(stamp, str) and stamp and "T" not in stamp:
        return stamp.replace(" ", "T") + "+00:00"
    return stamp


# ─── Saving ──────────────────────────────────────────────────────


async def save_case(graph_app, thread_id: str, turn: str, *, title: Optional[str] = None,
                    store: Optional[ThreadDocumentStore] = None) -> Dict[str, Any]:
    """Save a turn as a case: by its turn id or one of its replies'
    checkpoints (votes.turn_answers resolves both). Returns the case
    (case_view). ValueError for an unknown thread or turn, a reply written
    before turns were recorded, or a turn whose question can't be found."""
    if not await asyncio.to_thread(db.thread_exists, thread_id):
        raise ValueError(f"Thread {thread_id} not found.")
    turn_data = await votes.turn_answers(graph_app, thread_id, turn)
    answers = turn_data["answers"]
    states = await thread_state_map(graph_app, thread_id)

    # The branch to read the history from: the reply named, else the first answer.
    named = node_checkpoint(states[turn], states) if turn in states else None
    anchor = next((a for a in answers if a["checkpoint_id"] == named), answers[0])
    reply = states[anchor["checkpoint_id"]]
    asked = arena._question_of(reply, states)
    if asked is None:
        raise ValueError(f"No question precedes the answers of turn {turn_data['turn_id']}.")
    values = asked.values or {}
    messages = list(values.get("messages") or [])
    question = extract_text(messages[-1].content)
    history = [m for m in messages[:-1] if getattr(m, "type", "") != "remove"]

    from app.services.graph import SUMMARIZER_CONFIG_KEY, SYSTEM_PROMPT_CONFIG_KEY

    recorded = reply.metadata or {}
    toggles = values.get("toggles") or {}
    settings = {
        "use_web_search": bool(toggles.get("use_web_search")),
        "use_rag": bool(toggles.get("use_rag")),
        "system_prompt": recorded.get(SYSTEM_PROMPT_CONFIG_KEY) or None,
        "summarizer": recorded.get(SUMMARIZER_CONFIG_KEY) or None,
        "is_deliberation": bool(values.get("is_deliberation")),
    }

    store = store or ThreadDocumentStore()
    names = list(values.get("attached_documents") or [])
    attached = dict(values.get("documents") or {})  # content older checkpoints carry
    attached.update(await asyncio.to_thread(store.load, thread_id, names))
    # Document search reads every file uploaded to the thread, not only the
    # attached ones; without them a replay would search nothing.
    searched = await asyncio.to_thread(store.load, thread_id) if settings["use_rag"] else {}

    saved_answers = []
    for a in answers:
        answer = await arena.answer_at(graph_app, thread_id, a["checkpoint_id"])
        saved_answers.append({"model": a["model"], "content": answer["content"], "metrics": answer["metrics"],
                              "checkpoint_id": a["checkpoint_id"]})

    vote = await asyncio.to_thread(db.get_answer_vote, thread_id, turn_data["turn_id"])
    data = {
        "history": messages_to_dict(history),
        "history_from": anchor["model"],
        "settings": settings,
        "answers": saved_answers,
        "vote": votes.with_names(vote) if vote else None,
    }
    title = " ".join((title or "").split())[:TITLE_MAX_CHARS] or auto_title(question) or "Untitled case"
    case = await asyncio.to_thread(
        db.save_case, f"case-{uuid.uuid4().hex[:10]}", title=title, question=question, data=data,
        documents={"attached": attached, "searched": searched},
        source_thread_id=thread_id, source_turn_id=turn_data["turn_id"],
    )
    return case_view(case, [])


# ─── Reading ─────────────────────────────────────────────────────


def _readable_history(serialized: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The stored history as a person reads it: who said what, a summary
    marked as one; synthesis prompts and other system messages left out."""
    from app.services.tree import is_synthesis_prompt

    out = []
    for m in messages_from_dict(list(serialized)):
        kind = getattr(m, "type", "")
        if is_summary_message(m):
            out.append({"role": "system", "kind": "summary", "content": summary_text(m), "model": None,
                        "model_name": None})
        elif kind in ("human", "ai") and not is_synthesis_prompt(m):
            model = message_model(m) if kind == "ai" else None
            out.append({"role": "user" if kind == "human" else "assistant", "kind": None,
                        "content": extract_text(m.content), "model": model,
                        "model_name": display_name(model) if model else None})
    return out


def _best_model(data: Mapping[str, Any]) -> Optional[str]:
    """The model whose answer the person voted best, if they did."""
    vote = data.get("vote") or {}
    if vote.get("outcome") != "best":
        return None
    winner = vote.get("winner_checkpoint_id")
    return next((a["model"] for a in data["answers"] if a.get("checkpoint_id") == winner), None)


def _documents_listed(documents: Mapping[str, str]) -> List[Dict[str, Any]]:
    return [{"name": name, "characters": len(text)} for name, text in documents.items()]


def case_view(case: Mapping[str, Any], replays: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """A case as clients read it: {case_id, title, question, created_at,
    source_thread_id, source_turn_id, history: [{role, kind, content, model,
    model_name}], history_from, summarized, documents / searched_documents:
    [{name, characters}], settings: {use_web_search, use_rag, system_prompt,
    summarizer, is_deliberation}, answers: [{model, model_name, content,
    metrics, checkpoint_id}], total (metrics.turn_total), vote, best_model,
    replays: [replay_view]}."""
    data = case["data"]
    history = _readable_history(data["history"])
    documents = case.get("documents") or {}
    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "question": case["question"],
        "created_at": _utc(case["created_at"]),
        "source_thread_id": case["source_thread_id"],
        "source_turn_id": case["source_turn_id"],
        "history": history,
        "history_from": data.get("history_from"),
        "summarized": any(m["kind"] == "summary" for m in history),
        "documents": _documents_listed(documents.get("attached") or {}),
        "searched_documents": _documents_listed(documents.get("searched") or {}),
        "settings": data["settings"],
        "answers": [{**a, "model_name": display_name(a["model"])} for a in data["answers"]],
        "total": turn_total(a.get("metrics") for a in data["answers"]),
        "vote": data.get("vote"),
        "best_model": _best_model(data),
        "replays": [replay_view(data, r) for r in replays],
    }


def _baseline(data: Mapping[str, Any], model: str) -> Optional[Dict[str, Any]]:
    """The case's answer a new answer from ``model`` is compared with: the
    same model's, else the one voted best, else none."""
    by_model = {a["model"]: a for a in data["answers"]}
    if model in by_model:
        return {**by_model[model], "reason": SAME_MODEL}
    best = _best_model(data)
    if best:
        return {**by_model[best], "reason": VOTED_BEST}
    return None


def replay_view(data: Mapping[str, Any], replay: Mapping[str, Any]) -> Dict[str, Any]:
    """One replay against the case: {replay_id, case_id, thread_id,
    created_at, models, total, results: [{model, model_name, content,
    checkpoint_id, error, metrics, baseline: {model, model_name, reason:
    "same_model" | "voted_best"} | null, diff (textdiff.diff_texts) | null}]}.
    A new model in a case nobody voted on has no baseline and no diff."""
    results = []
    for r in replay["results"]:
        base = _baseline(data, r["model"])
        usable = base is not None and not r.get("error")
        results.append({
            **r,
            "model_name": display_name(r["model"]),
            "baseline": {"model": base["model"], "model_name": display_name(base["model"]), "reason": base["reason"]}
            if base else None,
            "diff": diff_texts(base["content"] or "", r.get("content") or "") if usable else None,
        })
    return {
        "replay_id": replay["replay_id"],
        "case_id": replay["case_id"],
        "thread_id": replay["thread_id"],
        "created_at": _utc(replay["created_at"]),
        "models": replay["models"],
        "total": turn_total(r.get("metrics") for r in replay["results"]),
        "results": results,
    }


def _case(case_id: str) -> Dict[str, Any]:
    case = db.get_case(case_id)
    if not case:
        raise ValueError(f"Case {case_id} not found.")
    return case


def get_case(case_id: str) -> Dict[str, Any]:
    """A case with its replays, newest first (case_view). ValueError if there is none."""
    return case_view(_case(case_id), db.list_case_replays(case_id))


def list_cases() -> List[Dict[str, Any]]:
    """Every case, newest first: {case_id, title, question, created_at,
    source_thread_id, models, model_names, voted, replay_count,
    last_replayed_at}."""
    out = []
    for c in db.list_cases():
        models = [a["model"] for a in c["data"]["answers"]]
        out.append({
            "case_id": c["case_id"],
            "title": c["title"],
            "question": c["question"],
            "created_at": _utc(c["created_at"]),
            "source_thread_id": c["source_thread_id"],
            "models": models,
            "model_names": [display_name(m) for m in models],
            "voted": bool(c["data"].get("vote")),
            "replay_count": c["replay_count"],
            "last_replayed_at": _utc(c["last_replayed_at"]),
        })
    return out


def delete_case(case_id: str) -> None:
    """Delete a case and its replay records; the threads replays ran in stay.
    ValueError if there is none."""
    if not db.delete_case(case_id):
        raise ValueError(f"Case {case_id} not found.")


# ─── Replaying ───────────────────────────────────────────────────


def replay_plan(case_id: str, models: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """What a replay would run, checked without running anything: {case_id,
    title, question, models, model_names, context}. ``models`` default to
    the case's own. ValueError for an unknown case, an unknown model or one
    without a key, or settings this run can't use (a summarizer whose key is
    gone)."""
    case = _case(case_id)
    data = case["data"]
    chosen = arena.resolve_models(list(models) if models else [a["model"] for a in data["answers"]])
    settings = data["settings"]
    context = ContextSettings(summarizer=settings.get("summarizer"), system_prompt=settings.get("system_prompt"))
    if problem := context.problem():
        raise ValueError(f"This case was answered with settings a replay can't use now: {problem}")
    if settings.get("is_deliberation") and not data["history"]:
        raise ValueError("This case is a Deliberation with no conversation to review.")
    return {"case_id": case_id, "title": case["title"], "question": case["question"], "models": chosen,
            "model_names": [display_name(m) for m in chosen], "context": context}


async def replay_case(graph_app, case_id: str, models: Optional[Sequence[str]] = None, *,
                      indexer: Optional[Indexer] = None, store: Optional[ThreadDocumentStore] = None,
                      timeout: float = arena.ARENA_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Ask ``models`` (default: the case's own) the case's question in a new
    thread seeded with its history, with its documents and settings, and
    store the result. Returns replay_view plus {title, question}. The source
    thread is never read or written. ``indexer`` (default rag.index_document)
    indexes the case's searchable files into the new thread when the case
    searched documents. ValueError as replay_plan."""
    plan = await asyncio.to_thread(replay_plan, case_id, models)
    case = await asyncio.to_thread(_case, case_id)
    data, documents = case["data"], case.get("documents") or {}
    settings = data["settings"]
    toggles = {"use_web_search": settings["use_web_search"], "use_rag": settings["use_rag"]}

    thread_id = f"replay-{uuid.uuid4().hex[:8]}"
    await asyncio.to_thread(db.rename_thread, thread_id, f"Replay: {case['title']}"[:TITLE_MAX_CHARS])
    history = messages_from_dict(data["history"])
    if history:
        await seed_thread(graph_app, thread_id, {"messages": history})
    searched = documents.get("searched") or {}
    if settings["use_rag"] and searched:
        if indexer is None:
            from app.services.rag import index_document as indexer
        await asyncio.to_thread((store or ThreadDocumentStore()).save, thread_id, searched)
        for name, text in searched.items():
            await asyncio.to_thread(indexer, text, name, thread_id)

    result = await arena.collect(arena.run_arena(
        graph_app, case["question"], thread_id, plan["models"], toggles, synthesizer=None, timeout=timeout,
        context=plan["context"], documents=documents.get("attached") or None,
        is_deliberation=settings["is_deliberation"],
    ))
    results = [{"model": m, **{k: result["answers"][m].get(k) for k in ("content", "checkpoint_id", "error", "metrics")}}
               for m in plan["models"]]
    replay = await asyncio.to_thread(db.save_case_replay, f"replay-{uuid.uuid4().hex[:10]}", case_id, thread_id,
                                     plan["models"], results)
    return {**replay_view(data, replay), "title": case["title"], "question": case["question"]}
