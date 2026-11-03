"""Process constraints the person states ("never touch the billing tables"),
kept verbatim outside the summary.

A constraint that only lives in a summary can be summarized away (Governance
Decay); one kept as the person wrote it can't, whatever the summarizer does:
that half is guaranteed by construction (KeepConstraints, tested in
tests/test_constraints.py). What has to be measured is the detector: which
messages state a constraint. It is a regex over marker phrases, so how much
it catches is a property of the wording, not of any model, and
``CONSTRAINT_PHRASINGS`` measures it.

The phrasings were written before the detector, half with a marker word
("never", "must not", "don't") and half without ("leave the billing tables
alone", "prod is off limits"): the honest number is the catch rate on each
half, and the false-positive rate on ordinary messages.
"""

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .retention import EarlierMessage, KeepRecent

# Written first, before the detector below, and not tuned to it.
WITH_MARKERS = (
    "Never restart the ingest pipeline during business hours.",
    "Don't touch the billing tables without a ticket.",
    "You must not change the public API without telling the partners first.",
    "Always run the migration on staging before production.",
    "Do not delete anything in the audit log.",
    "We must keep the old endpoint working until June.",
    "Under no circumstances push straight to main.",
    "Make sure every export is encrypted.",
    "Don't email customers directly; go through support.",
    "Never store card numbers in the logs.",
    "Avoid adding new dependencies to the mobile client.",
    "We agreed not to use Kafka for the event bus.",
    "It is not allowed to share the staging credentials over chat.",
    "Only ever deploy on weekdays.",
    "Please never run the cleanup job by hand.",
)
WITHOUT_MARKERS = (
    "Leave the billing tables alone.",
    "Prod is off limits for this experiment.",
    "Hands off the payment webhook until the audit is done.",
    "The legacy importer stays exactly as it is.",
    "Keep your changes inside the search module.",
    "No new services this quarter.",
    "Customer data stays in the EU.",
    "The release branch is frozen from Friday.",
    "Schema changes go through review first.",
    "Treat the config service as read-only.",
    "Nothing gets merged without two approvals.",
    "The rate limiter settings belong to the platform team, not us.",
    "Production access is for the on-call engineer only.",
    "Tests have to pass before anything ships.",
    "We're sticking with Postgres; that's settled.",
)
CONSTRAINT_PHRASINGS = WITH_MARKERS + WITHOUT_MARKERS
# Ordinary remarks that use a marker word without stating any rule, written
# with the phrasings above (the synthetic filler never does this, so it can't
# show these false positives).
MARKERS_WITHOUT_RULES = (
    "I always forget how the exporter is configured.",
    "Never mind, that was my mistake.",
    "You must be tired of this topic by now.",
    "Don't worry, the numbers looked fine yesterday.",
    "Make sure? I thought we already checked that.",
    "The old team never documented the importer.",
    "It doesn't matter much which dashboard we look at.",
    "We should not have waited this long, honestly.",
    "Avoiding the question won't help, so let's decide.",
    "Do not ask me why the build is slow today, I have no idea.",
)

# The detector: marker phrases that state a rule. Written after the phrasings.
_MARKERS = re.compile(
    r"\b(never|always|must(?:n't| not)?|do not|don't|does not|doesn't|should(?:n't| not)|"
    r"not allowed|forbidden|under no circumstances|only ever|make sure|agreed not to|avoid)\b",
    re.IGNORECASE,
)


def is_constraint(text: str) -> bool:
    """Whether a message states a process constraint, by its marker phrases."""
    return bool(_MARKERS.search(text))


class KeepConstraints:
    """The person's messages that state a constraint, verbatim, newest first
    up to ``budget`` tokens, on top of ``recent``: a rule the person gave is
    never left to the summarizer. Whole messages, as KeepUserMessages keeps
    them."""

    def __init__(self, budget: int = 2_000, recent: KeepRecent = KeepRecent()):
        self.budget = budget
        self.recent = recent
        self.name = "constraints"

    def keep(self, earlier: Sequence[EarlierMessage]) -> list[int]:
        kept = set(self.recent.keep(earlier))
        left = self.budget
        for i in range(len(earlier) - 1, -1, -1):
            m = earlier[i]
            if i in kept or m.role != "user" or not is_constraint(m.text):
                continue
            if m.tokens > left:
                continue
            kept.add(i)
            left -= m.tokens
        return sorted(kept)


@dataclass
class DetectorReport:
    with_markers: float
    without_markers: float
    # On the scenarios' ordinary messages, and on ordinary remarks that use a marker word.
    false_positives: float
    ordinary_messages: int
    false_positives_with_markers: float
    missed: list[str]
    flagged_remarks: list[str]


def measure_detector(ordinary: Iterable[str]) -> DetectorReport:
    """Catch rate on each half of CONSTRAINT_PHRASINGS, and how often
    ordinary messages (no constraint in them) are flagged anyway."""
    ordinary = list(ordinary)
    flagged = [t for t in ordinary if is_constraint(t)]
    remarks = [t for t in MARKERS_WITHOUT_RULES if is_constraint(t)]
    return DetectorReport(
        with_markers=round(sum(map(is_constraint, WITH_MARKERS)) / len(WITH_MARKERS), 3),
        without_markers=round(sum(map(is_constraint, WITHOUT_MARKERS)) / len(WITHOUT_MARKERS), 3),
        false_positives=round(len(flagged) / len(ordinary), 3) if ordinary else 0.0,
        ordinary_messages=len(ordinary),
        false_positives_with_markers=round(len(remarks) / len(MARKERS_WITHOUT_RULES), 3),
        missed=[t for t in CONSTRAINT_PHRASINGS if not is_constraint(t)],
        flagged_remarks=remarks,
    )
