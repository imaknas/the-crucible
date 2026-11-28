"""Checking an issue list problem by problem: does each problem hold?

An issue list (synthesis mode "issues") collects every problem a set of
independent reviews raised, by who raised it. Whether each one holds is the
next question, and it is answered problem by problem against the source: the
question the reviews answered and the documents attached to it.

Each checker (by default every model that wrote one of the reviews) reads
the source and the problems, in its own seeded order, without who raised
them or how many did, and gives each a verdict: it holds, it doesn't, or the
source can't tell, with the passage the verdict rests on. Checkers don't see
each other. The verdicts are shown side by side, never tallied into one: a
problem the checkers disagree on is the one to read yourself. A verdict on a
problem the checker's own model raised is marked, since models favour what
they wrote.

The result is stored per list (core/database issue_checks), never written
into the thread and never fed into a synthesis.
"""

import asyncio
import logging
import random
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.core import database as db
from app.registry import display_name
from app.services.metrics import call_entry, priced, with_calls
from app.services.synthesis import Issue, parse_issues

log = logging.getLogger(__name__)

VERDICTS = ("holds", "does_not_hold", "cant_tell")
_VERDICT_WORDS = {
    "holds": "holds",
    "does not hold": "does_not_hold",
    "doesn't hold": "does_not_hold",
    "doesn’t hold": "does_not_hold",
    "can't tell": "cant_tell",
    "can’t tell": "cant_tell",
    "cannot tell": "cant_tell",
}
VERDICT_LINE = re.compile(
    r"^\s*[-*]*\s*\[?(\d+)\]?\**\s*[:：.)]\s*\**\s*("
    + "|".join(re.escape(w) for w in sorted(_VERDICT_WORDS, key=len, reverse=True))
    + r")\s*\**\s*[—–-]+\s*(.+?)\s*$",
    re.I,
)
# What a checker reads of the attached documents, at most: about what one
# turn's context holds (graph.sanitize_messages caps a request at 1.2M chars).
MAX_SOURCE_CHARS = 1_000_000


def check_prompt(question: str, documents: Mapping[str, str], issues: Sequence[Issue]) -> tuple[str, bool]:
    """What one checker reads, and whether the documents had to be cut."""
    source, used, truncated = [], 0, False
    for name, text in documents.items():
        room = MAX_SOURCE_CHARS - used
        if room <= 0:
            truncated = True
            break
        if len(text) > room:
            text, truncated = text[:room] + "\n[… the rest of this document is not shown]", True
        source.append(f"--- {name} ---\n{text}")
        used += len(text)
    problems = "\n".join(
        f"{i.number}. {i.problem}" + (f"\n   Reason given: {i.why}" if i.why else "") for i in issues
    )
    material = "\n\n".join(source) if source else "(no documents were attached; the question is the whole source)"
    prompt = (
        f"Question that was reviewed:\n{question}\n\n"
        f"Documents attached to it:\n{material}\n\n"
        "Reviewers raised the problems below. Check each problem below against the question and the "
        "documents above, and only those: decide whether it holds.\n"
        "- holds: the source shows the problem is real;\n"
        "- does not hold: the source shows it isn't (it is already handled, or rests on a misreading);\n"
        "- can't tell: the source doesn't settle it either way.\n"
        "Judge each problem on its own, whoever raised it.\n\n"
        f"Problems:\n{problems}\n\n"
        "Write one line per problem, in exactly this form and nothing else, quoting or pointing to the "
        "passage the verdict rests on:\n"
        "<number>: <holds | does not hold | can't tell> — <one-sentence reason>"
    )
    return prompt, truncated


def parse_verdicts(text: str, numbers: Sequence[int]) -> Dict[int, tuple[str, str]]:
    """number → (verdict, reason) for the expected numbers; ValueError when
    a checker gave none in the expected form."""
    found: Dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        m = VERDICT_LINE.match(line)
        if m and int(m.group(1)) in numbers:
            found[int(m.group(1))] = (_VERDICT_WORDS[m.group(2).lower()], m.group(3))
    if not found:
        raise ValueError("The check listed no verdicts in the expected form.")
    return found


_ANSWER_LABEL = re.compile(r"\bAnswer ([A-Z])\b", re.I)


def _by_letter(legend: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, str]:
    return {entry["label"].split()[-1].upper(): entry["model"] for entry in legend or []}


def raised_by_models(issue: Issue, models: Sequence[str],
                     legend: Optional[Sequence[Mapping[str, Any]]] = None) -> List[str]:
    """Which of the reviewing models an issue's "Raised by" names: by letter
    ("Answer B", through the list's ``legend``, tree.synthesis_legend), or,
    in a list written before letters, by display name (without an angle note
    or a "#2", arena.named_labels)."""
    letters = _by_letter(legend)
    bare = re.sub(r"\([^)]*\)", "", issue.raised_by)
    parts = [re.sub(r"\s*#\d+\s*$", "", part).strip(" .*[]") for part in re.split(r",|;|\band\b", bare)]
    named = {p.lower() for p in parts}
    lettered = {letters[m.group(1).upper()] for p in parts if (m := _ANSWER_LABEL.fullmatch(p)) and m.group(1).upper() in letters}
    return [m for m in models if m in lettered or display_name(m).lower() in named]


def revealed(raised_by: str, legend: Optional[Sequence[Mapping[str, Any]]]) -> str:
    """"Answer A, Answer C" as the reader needs it: "Answer A (GPT-6.2 Sol),
    Answer C (Gemini 4 Neon)". The list's own text keeps the letters the
    synthesizer wrote."""
    letters = _by_letter(legend)

    def name(m: re.Match) -> str:
        model = letters.get(m.group(1).upper())
        return f"{m.group(0)} ({display_name(model)})" if model else m.group(0)

    return _ANSWER_LABEL.sub(name, raised_by)


async def _source(graph_app, thread_id: str, list_state, states, store) -> Dict[str, Any]:
    """The reviews an issue list was written from, the question they
    answered and that question's attached documents."""
    from app.services.arena import _question_of, answer_at
    from app.services.tree import synthesis_details

    answer_ids = synthesis_details(list_state)["synthesis_answers"]
    if not answer_ids:
        raise ValueError("This issue list doesn't record which answers it was written from, so there is no source to check it against.")
    answers = [await answer_at(graph_app, thread_id, cid) for cid in answer_ids if cid in states]
    if not answers:
        raise ValueError("The answers this issue list was written from are gone.")
    questions = list(dict.fromkeys((a.get("question") or "").strip() for a in answers))
    documents: Dict[str, str] = {}
    for cid in answer_ids:
        asked = _question_of(states[cid], states) if cid in states else None
        if asked is None:
            continue
        values = asked.values or {}
        documents.update(values.get("documents") or {})
        names = [n for n in values.get("attached_documents") or [] if n not in documents]
        if names:
            documents.update(await asyncio.to_thread(store.load, thread_id, names))
    return {
        "answers": answers,
        "question": "\n\n".join(q for q in questions if q) or "(not recorded)",
        "documents": documents,
    }


async def check_issues(
    graph_app,
    thread_id: str,
    checkpoint_id: str,
    models: Optional[Sequence[str]] = None,
    *,
    factory=None,
    store=None,
) -> Dict[str, Any]:
    """Check every problem of an issue list (a reply of synthesis mode
    "issues", by any of its checkpoints) against the question and documents
    the reviews answered, and store the result. Returns {thread_id,
    checkpoint_id (the list's node), question, documents (names),
    source_truncated, checkers: [{model, model_name}], issues: [{number,
    problem, raised_by (letters given with their models), raised_by_models,
    why, verdicts: [{checker, checker_name, verdict,
    reason, own}], disagree}], errors: {model: message}}. ``models``
    default to the models that wrote the reviews. ValueError for a
    checkpoint that isn't an issue list, a list in another form, or unusable
    models."""
    from langchain_core.messages import HumanMessage

    from app.core.database import ThreadDocumentStore
    from app.llm import model_factory_from
    from app.services.arena import resolve_models
    from app.services.chat import node_checkpoint, thread_state_map
    from app.services.recall import INTERNAL_TAG
    from app.services.tree import is_synthesis_reply, synthesis_details
    from app.utils.helpers import extract_text

    if not await asyncio.to_thread(db.thread_exists, thread_id):
        raise ValueError(f"Thread {thread_id} not found.")
    states = await thread_state_map(graph_app, thread_id)
    snapshot = states.get(checkpoint_id)
    if snapshot is None:
        raise ValueError(f"Checkpoint {checkpoint_id} is not on thread {thread_id}.")
    if not is_synthesis_reply(snapshot) or synthesis_details(snapshot)["synthesis_mode"] != "issues":
        raise ValueError("Only an issue list (synthesis mode \"issues\") can be checked problem by problem.")
    node = node_checkpoint(snapshot, states)
    issues = parse_issues(extract_text(snapshot.values["messages"][-1].content))
    source = await _source(graph_app, thread_id, snapshot, states, store or ThreadDocumentStore())
    reviewers = list(dict.fromkeys(a["model"] for a in source["answers"]))
    checkers = resolve_models(list(dict.fromkeys(models)) if models else reviewers)
    config = {"configurable": {"model_factory": factory}} if factory else {}
    truncated = False

    calls: list = []

    async def check_by(checker: str) -> Dict[int, tuple[str, str]]:
        nonlocal truncated
        order = list(issues)
        random.Random(f"{node}:{checker}").shuffle(order)
        prompt, cut = check_prompt(source["question"], source["documents"], order)
        truncated = truncated or cut
        # No toggles: a check reads the source it is given, not the web.
        llm = model_factory_from(config).chat(checker, {})
        response = await llm.ainvoke([HumanMessage(content=prompt)], config={"tags": [INTERNAL_TAG]})
        calls.append(call_entry(response, checker, "issue check"))
        return parse_verdicts(extract_text(response.content), [i.number for i in issues])

    results = await asyncio.gather(*(check_by(c) for c in checkers), return_exceptions=True)
    errors: Dict[str, str] = {}
    verdicts: Dict[str, Dict[int, tuple[str, str]]] = {}
    for checker, result in zip(checkers, results):
        if isinstance(result, BaseException):
            log.warning("Issue check by %s failed: %s", checker, result)
            errors[checker] = str(result)
        else:
            verdicts[checker] = result

    rows = []
    legend = synthesis_details(snapshot)["synthesis_legend"]
    for issue in issues:
        raised = raised_by_models(issue, reviewers, legend)
        given = [
            {
                "checker": c,
                "checker_name": display_name(c),
                "verdict": verdicts[c][issue.number][0],
                "reason": verdicts[c][issue.number][1],
                "own": c in raised,
            }
            for c in checkers if c in verdicts and issue.number in verdicts[c]
        ]
        rows.append({
            "number": issue.number,
            "problem": issue.problem,
            "raised_by": revealed(issue.raised_by, legend),
            "raised_by_models": raised,
            "why": issue.why,
            "verdicts": given,
            "disagree": len({v["verdict"] for v in given}) > 1,
        })

    check = {
        "thread_id": thread_id,
        "checkpoint_id": node,
        "question": source["question"],
        "documents": list(source["documents"]),
        "source_truncated": truncated,
        "checkers": [{"model": c, "model_name": display_name(c)} for c in checkers],
        "issues": rows,
        "errors": errors,
    }
    check = with_calls(check, calls)
    await asyncio.to_thread(db.save_issue_check, thread_id, node, check)
    return priced(check)


def checks_of(thread_id: str) -> List[dict]:
    """Every stored check of an issue list on a thread, newest first."""
    return [priced(c) for c in db.list_issue_checks(thread_id)]
