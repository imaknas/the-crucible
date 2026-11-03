"""Pinned constraints: a rule the person stated survives pruning whatever the
summary says (by construction), and what the detector behind it finds
(app/compaction/constraints.py)."""

from langchain_core.messages import AIMessage, HumanMessage

from app.compaction import EarlierMessage, KeepConstraints, KeepRecent, is_constraint
from app.compaction.constraints import (
    MARKERS_WITHOUT_RULES,
    WITH_MARKERS,
    WITHOUT_MARKERS,
    measure_detector,
)
from app.core.schema import summary_message
from app.services.graph import sanitize_messages

RULE = "Quick note on the billing tables. Never run the cleanup job by hand."


def _pruned_conversation():
    """A rule early on, 30 ordinary exchanges, then a summary that lost it."""
    msgs = [HumanMessage(content=RULE), AIMessage(content="Understood.")]
    for i in range(30):
        msgs += [HumanMessage(content=f"Ordinary question {i} about the rollout."), AIMessage(content=f"Answer {i}.")]
    msgs.append(summary_message("We discussed the rollout at length."))
    msgs += [HumanMessage(content="What did we agree about the cleanup job?")]
    return msgs


def _text(messages) -> str:
    return "\n".join(str(m.content) for m in messages)


def test_a_pinned_rule_survives_pruning_whatever_the_summary_says():
    kept = sanitize_messages(_pruned_conversation(), prune_history=True, retention=KeepConstraints())
    assert "Never run the cleanup job by hand" in _text(kept)
    # The app's default keeps only the newest messages: the rule is gone.
    default = sanitize_messages(_pruned_conversation(), prune_history=True, retention=KeepRecent())
    assert "Never run the cleanup job by hand" not in _text(default)


def test_only_the_persons_rules_are_pinned_newest_first_within_the_budget():
    earlier = [
        EarlierMessage("user", 900, "Never deploy on Fridays."),
        EarlierMessage("assistant", 50, "You must remember to tag releases."),
        EarlierMessage("user", 900, "Don't touch the billing tables."),
        EarlierMessage("user", 900, "Always run the tests first."),
        *[EarlierMessage("user", 10, f"Ordinary message {i}.") for i in range(6)],
    ]
    kept = KeepConstraints(budget=2_000).keep(earlier)
    # The two newest rules fit; the oldest doesn't; the assistant's never counts.
    assert 3 in kept and 2 in kept and 0 not in kept and 1 not in kept
    assert set(range(5, 10)) <= set(kept)  # the recent window


def test_the_detector_is_about_wording_not_intent():
    report = measure_detector(["Ordinary question about the rollout."])
    assert len(WITH_MARKERS) == len(WITHOUT_MARKERS) == 15
    assert report.with_markers == sum(map(is_constraint, WITH_MARKERS)) / 15
    assert report.missed == [t for t in (*WITH_MARKERS, *WITHOUT_MARKERS) if not is_constraint(t)]
    assert report.false_positives_with_markers == round(
        sum(map(is_constraint, MARKERS_WITHOUT_RULES)) / len(MARKERS_WITHOUT_RULES), 3
    )
