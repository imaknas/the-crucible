"""Anonymous peer review of a set of answers: how the models score each
other's answers, shown beside them as evidence, never as a verdict.

Each answer gets a letter; every model that wrote one of them scores the
others (never its own: models favour text they recognise as theirs) from 1 to
10 with a one-line reason, reading them in its own seeded order (position
bias). No model sees another's model name, and none can change its answer:
the review is about answers already written. Scores rather than a ranking,
because with two answers each reviewer sees only one other.

The result is stored per set of answers (core/database answer_reviews) and
is never fed into a synthesis prompt.
"""

import asyncio
import hashlib
import logging
import random
import re
from dataclasses import asdict, dataclass, field
from typing import Any, List, Mapping, Optional, Sequence

from app.core import database as db
from app.registry import display_name

log = logging.getLogger(__name__)

SCORE_LINE = re.compile(r"^\s*\[?([A-Z])\]?\s*[:：]\s*(\d{1,2})(?:\s*/\s*10)?\s*[—–-]+\s*(.+?)\s*$")


@dataclass
class Score:
    reviewer: str
    score: int
    reason: str


@dataclass
class ReviewedAnswer:
    label: str
    checkpoint_id: str
    model: str
    model_name: str
    scores: List[Score] = field(default_factory=list)

    @property
    def average(self) -> Optional[float]:
        return round(sum(s.score for s in self.scores) / len(self.scores), 2) if self.scores else None


def review_key(checkpoint_ids: Sequence[str]) -> str:
    """One stored review per set of answers, whatever order they were named in."""
    return hashlib.sha1("|".join(sorted(set(checkpoint_ids))).encode()).hexdigest()[:16]


def _letters(answers: Sequence[Mapping[str, Any]], key: str) -> List[str]:
    """A letter per answer, shuffled by the set's key: the order the answers
    were named in says nothing to the reviewers."""
    order = list(range(len(answers)))
    random.Random(f"{key}:labels").shuffle(order)
    letters = [""] * len(answers)
    for letter_index, answer_index in enumerate(order):
        letters[answer_index] = chr(ord("A") + letter_index)
    return letters


def review_prompt(question: str, others: Sequence[tuple[str, str]]) -> str:
    """What one reviewer reads: the question and the other answers, by letter."""
    body = "\n\n".join(f"[{label}]:\n{content}" for label, content in others)
    return (
        f"Question: {question}\n\n"
        f"Answers to it from other models, labelled by letter (yours is not among them):\n\n{body}\n\n"
        "Score each answer from 1 to 10 for accuracy and insight. Write one line per answer, "
        "in exactly this form and nothing else:\n"
        "<letter>: <score> — <one-sentence reason>"
    )


def parse_scores(text: str, labels: Sequence[str]) -> dict[str, tuple[int, str]]:
    """letter → (score, reason) for the expected letters; ValueError when a
    reviewer scored none of them in the expected form."""
    found = {}
    for line in text.splitlines():
        m = SCORE_LINE.match(line)
        if m and m.group(1) in labels and 1 <= int(m.group(2)) <= 10:
            found[m.group(1)] = (int(m.group(2)), m.group(3))
    if not found:
        raise ValueError("The review listed no scores in the expected form.")
    return found


async def review_answers(
    graph_app, thread_id: str, checkpoint_ids: Optional[Sequence[str]] = None, *, factory=None
) -> dict[str, Any]:
    """Have every model that wrote one of these answers score the others,
    anonymously, and store the result. Returns the stored review:
    {review_key, thread_id, checkpoint_ids, question, answers: [{label,
    checkpoint_id, model, model_name, average, scores: [{reviewer,
    reviewer_name, score, reason}]}], errors: {model: message}}. A reviewer
    that fails or answers in another form is an error, not a missing row.
    ``checkpoint_ids`` default to the answers to the thread's latest
    question. ValueError for fewer than two answers or answers by a single
    model."""
    from langchain_core.messages import HumanMessage

    from app.llm import model_factory_from
    from app.services.arena import answer_at, latest_turn_answers, resolve_models
    from app.services.recall import INTERNAL_TAG
    from app.utils.helpers import extract_text

    if checkpoint_ids:
        ids = list(dict.fromkeys(checkpoint_ids))
        answers = [await answer_at(graph_app, thread_id, cid) for cid in ids]
    else:
        answers = await latest_turn_answers(graph_app, thread_id)
        ids = [a["checkpoint_id"] for a in answers]
    if len(answers) < 2:
        raise ValueError(f"A peer review needs at least two answers; got {len(answers)}.")
    reviewers = list(dict.fromkeys(a["model"] for a in answers))
    if len(reviewers) < 2:
        raise ValueError("A peer review needs answers by at least two different models: none may review its own.")
    resolve_models(reviewers)

    key = review_key(ids)
    letters = _letters(answers, key)
    reviewed = [
        ReviewedAnswer(label=letter, checkpoint_id=a["checkpoint_id"], model=a["model"], model_name=display_name(a["model"]))
        for letter, a in zip(letters, answers)
    ]
    question = answers[0].get("question") or "(see the answers)"
    config = {"configurable": {"model_factory": factory}} if factory else {}

    async def review_by(reviewer: str) -> tuple[str, dict[str, tuple[int, str]]]:
        others = [(r.label, a["content"]) for r, a in zip(reviewed, answers) if a["model"] != reviewer]
        random.Random(f"{key}:{reviewer}").shuffle(others)
        llm = model_factory_from(config).chat(reviewer, {})
        response = await llm.ainvoke(
            [HumanMessage(content=review_prompt(question, others))], config={"tags": [INTERNAL_TAG]}
        )
        return reviewer, parse_scores(extract_text(response.content), [label for label, _ in others])

    results = await asyncio.gather(*(review_by(r) for r in reviewers), return_exceptions=True)
    errors: dict[str, str] = {}
    for reviewer, result in zip(reviewers, results):
        if isinstance(result, BaseException):
            log.warning("Peer review by %s failed: %s", reviewer, result)
            errors[reviewer] = str(result)
            continue
        _, scores = result
        for r in reviewed:
            if r.label in scores:
                score, reason = scores[r.label]
                r.scores.append(Score(reviewer=reviewer, score=score, reason=reason))

    review = {
        "review_key": key,
        "thread_id": thread_id,
        "checkpoint_ids": ids,
        "question": question,
        "answers": [
            {
                **{k: v for k, v in asdict(r).items() if k != "scores"},
                "average": r.average,
                "scores": [{**asdict(s), "reviewer_name": display_name(s.reviewer)} for s in r.scores],
            }
            for r in reviewed
        ],
        "errors": errors,
    }
    await asyncio.to_thread(db.save_answer_review, thread_id, key, review)
    return review


def reviews_of(thread_id: str) -> list[dict]:
    """Every stored peer review on a thread, newest first."""
    return db.list_answer_reviews(thread_id)
