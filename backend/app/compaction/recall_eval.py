"""What a recall brings back, measured with no model in the loop.

A HistoryRecall is a mechanism: given the request and the hidden history,
it returns some of the hidden messages. For keyword and embedding recall
nothing in it is a language model, so what it returns for a scenario is a
property of the mechanism that no better model can change. This module
runs a recall over a scenario's hidden history and scores each probe by
fact key, never by matching text (the harness-bias lesson of 2026-10-25):

- *hit*: the turn where the fact was planted came back;
- *false positives*: other turns that came back (the reader has to ignore
  them, and they cost tokens);
- *stale*: a turn holding a superseded or rejected value came back;
- *stale without current*: it came back and the current statement did not,
  the case where even a perfect reader would answer with the old value.

"Hidden" is what a pruned call can't see: every turn but the newest
``keep_verbatim`` (the app's KEEP_VERBATIM, 5); a fact planted in that
window is visible anyway and is reported as such, not scored.

Lexical overlap (terms shared between the question and the planted
statement, with keyword recall's own tokenizer) is recorded per probe:
keyword recall cannot return a turn that shares no term with the request
(its score is zero), so its hit rate at zero overlap is zero by
construction, and the measured question is how often real questions sit
there and what an embedding recall does with them.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .probe import PlantedFact, Scenario
from .recall import HistoryRecall, _terms

KEEP_VERBATIM = 5


@dataclass
class RecallProbe:
    fact: str
    kind: str
    variant: str
    # Planted in the window a pruned call still sees: not scored.
    visible: bool
    hit: bool = False
    returned: int = 0
    false_positives: int = 0
    stale: bool = False
    stale_without_current: bool = False
    # Terms the question shares with the planted statement (keyword recall's tokenizer).
    overlap: int = 0
    returned_turns: List[int] = field(default_factory=list)


def overlap(question: str, statement: str) -> int:
    """Terms shared by a question and a statement, as keyword recall sees them."""
    return len(set(_terms(question)) & set(_terms(statement)))


def measure_recall(
    scenario: Scenario, recall: HistoryRecall, *, keep_verbatim: int = KEEP_VERBATIM
) -> List[RecallProbe]:
    """One RecallProbe per planted fact: what ``recall`` returns for its
    probe from the scenario's hidden history (turn indexes are the
    scenario's)."""
    hidden_count = max(0, len(scenario.turns) - keep_verbatim)
    candidates = [t.text for t in scenario.turns[:hidden_count]]
    probes = []
    for fact in scenario.facts:
        planted = scenario.positions[fact.key]
        extras = set(scenario.extra_positions.get(fact.key, []))
        question = scenario.question_for(fact)
        record = RecallProbe(fact=fact.key, kind=fact.kind, variant=fact.variant, visible=planted >= hidden_count,
                             overlap=overlap(question, fact.statement))
        if not record.visible:
            returned = sorted(recall.select(scenario.probe_prompt(fact), candidates))
            stale_turns = _stale_turns(fact, scenario, extras)
            record.returned_turns = returned
            record.returned = len(returned)
            record.hit = planted in returned
            record.false_positives = sum(1 for i in returned if i != planted and i not in extras)
            record.stale = any(i in stale_turns for i in returned)
            record.stale_without_current = record.stale and not record.hit
        probes.append(record)
    return probes


def _stale_turns(fact: PlantedFact, scenario: Scenario, extras: set) -> set:
    """Turns holding a value that must not be given: a superseded one
    (update) or a rejected proposal (distractor). Restatements of the same
    value (``+repeated``) are not stale."""
    if fact.variant.startswith("update") or fact.variant.startswith("distractor"):
        stale_texts = [x for x in fact.extras if not x.startswith("To repeat what was said earlier")]
        return {i for i in extras if any(x in scenario.turns[i].text for x in stale_texts)}
    return set()


def summarize(probes: Sequence[RecallProbe]) -> Dict[str, Any]:
    """Rates over the scored probes, overall, by variant and by overlap
    (0, 1, 2+ shared terms)."""
    scored = [p for p in probes if not p.visible]

    def rates(ps: Sequence[RecallProbe]) -> Dict[str, Any]:
        n = len(ps)
        if not n:
            return {"probes": 0}
        returned = sum(p.returned for p in ps)
        hits = sum(p.hit for p in ps)
        with_stale = [p for p in ps if p.variant.startswith(("update", "distractor"))]
        return {
            "probes": n,
            "hit_rate": round(hits / n, 3),
            # Of what came back, the share that was the fact's own turn.
            "precision": round(hits / returned, 3) if returned else None,
            "false_positives_per_probe": round(sum(p.false_positives for p in ps) / n, 2),
            "stale_rate": round(sum(p.stale for p in with_stale) / len(with_stale), 3) if with_stale else None,
            "stale_without_current_rate": (
                round(sum(p.stale_without_current for p in with_stale) / len(with_stale), 3) if with_stale else None
            ),
        }

    def bucket(p: RecallProbe) -> str:
        return "0" if p.overlap == 0 else "1" if p.overlap == 1 else "2+"

    by_variant: Dict[str, List[RecallProbe]] = {}
    by_overlap: Dict[str, List[RecallProbe]] = {}
    for p in scored:
        by_variant.setdefault(p.variant.split("+")[0], []).append(p)
        by_overlap.setdefault(bucket(p), []).append(p)
    return {
        "visible": sum(1 for p in probes if p.visible),
        "all": rates(scored),
        "by_variant": {k: rates(v) for k, v in sorted(by_variant.items())},
        "by_overlap": {k: rates(v) for k, v in sorted(by_overlap.items())},
    }


def probe_rows(probes: Sequence[RecallProbe]) -> List[Dict[str, Any]]:
    """The probes as plain rows, for a results file."""
    return [asdict(p) for p in probes]


def measure(
    scenarios: Sequence[Scenario], recalls: Sequence[HistoryRecall], *, keep_verbatim: int = KEEP_VERBATIM,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Every recall over every scenario: {label, keep_verbatim, recalls:
    {name: {summary, probes}}}. Pooled over scenarios."""
    out: Dict[str, Any] = {"label": label, "keep_verbatim": keep_verbatim, "recalls": {}}
    for recall in recalls:
        probes = [p for s in scenarios for p in measure_recall(s, recall, keep_verbatim=keep_verbatim)]
        out["recalls"][recall.name] = {"summary": summarize(probes), "probes": probe_rows(probes)}
    return out
