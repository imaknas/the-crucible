"""The prompt a synthesizer model answers, for Arena and for Debate.

The prompt has one shape: the question, the answers under a description of
what they are, then what to write. What the answers are and what to write
differ by where they came from, so both arrive in a SynthesisFraming chosen
by the caller:

  INDEPENDENT  Arena: answers written without seeing each other. Merging them
               into one answer is what the evidence supports: agreement
               between independent answers means something.
  ARGUMENT_MAP Debate: every round of each participant, written after
               reading the others. Their agreement is not independent, so the
               synthesizer maps the arguments for the reader to judge instead
               of declaring an answer.
"""

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SynthesisFraming:
    # What the answers are; `{n}` is the number of answers.
    described_as: str
    # What the synthesizer is asked to write from them.
    instruction: str


INDEPENDENT = SynthesisFraming(
    described_as="Independent answers from {n} models",
    instruction=(
        "Synthesize these into one answer. State where the models agree, resolve "
        "or flag where they contradict each other, and keep the strongest "
        "supported points. Attribute claims to models where it matters."
    ),
)

ARGUMENT_MAP = SynthesisFraming(
    described_as=(
        "A debate between {n} participants, participant by participant. Each "
        "participant's Round 1 is its independent answer, written before it saw "
        "the others; every later round was written after reading the others' "
        "previous round"
    ),
    instruction=(
        "Write an argument map of this debate for a reader who will weigh it "
        "themselves. Refer to participants by their labels.\n"
        "1. Positions: list the distinct positions taken, and which participants "
        "held each in Round 1 and at the end.\n"
        "2. Arguments: for each position, the strongest arguments and the "
        "evidence offered for it.\n"
        "3. Changes of position: where a participant changed position, from what "
        "to what, and the argument or evidence that changed it. Say so when a "
        "change came without a new argument or evidence.\n"
        "4. Unresolved: what remains disputed, and what information would "
        "settle each point.\n"
        "Do not declare a winner or a consensus. Agreement reached by debating "
        "is not evidence by itself: the participants read each other, and "
        "debaters drift toward the majority or the most confident voice. How "
        "many participants hold a position is not an argument for it."
    ),
)


def build_synthesis_prompt(
    question: str, answers: Iterable[Tuple[str, str]], framing: SynthesisFraming
) -> str:
    """`answers` is (author, content) pairs, already labelled as the
    synthesizer should see them."""
    answers = list(answers)
    body = "\n\n".join(f"[{author}]:\n{content}" for author, content in answers)
    return (
        f"Original question: {question}\n\n"
        f"{framing.described_as.format(n=len(answers))}:\n\n{body}\n\n"
        f"{framing.instruction}"
    )


COMPARE = SynthesisFraming(
    described_as="Answers from {n} models",
    instruction=(
        "Compare these answers for a reader choosing between them. Don't merge "
        "them into one answer and don't pick a winner.\n"
        "1. A table with one row per point on which the answers differ: the "
        "point, then one column per answer in the order given, each stating "
        "that answer's position in a few words (write \"not covered\" where an "
        "answer says nothing about it).\n"
        "2. Where all the answers agree, in a few bullets.\n"
        "3. What only one answer covers, and which one."
    ),
)


def checklist_merge(kept: Sequence[str]) -> SynthesisFraming:
    """Merge the answers keeping exactly the components the reader ticked
    (from the list `component_request` asked for)."""
    items = "\n".join(f"- {k}" for k in kept)
    return SynthesisFraming(
        described_as="Answers from {n} models",
        instruction=(
            "Write one answer from these, built from exactly the components the "
            f"reader chose to keep:\n{items}\n"
            "Leave out what isn't on that list. Where kept components conflict, "
            "say so instead of resolving it silently. Attribute claims to models "
            "where it matters."
        ),
    )


def ask_about(question: str) -> SynthesisFraming:
    """Answer the reader's question about a selection of answers."""
    return SynthesisFraming(
        described_as="{n} answers the reader selected",
        instruction=(
            f"The reader asks about these answers: {question}\n"
            "Answer that question from the answers above. Say which answer each "
            "point comes from, and say so where the answers don't settle it."
        ),
    )


# How a synthesis can be asked for. merge: one answer from many (INDEPENDENT);
# compare: a table of differences; checklist: one answer from the components
# the reader kept; ask: the reader's own question about the answers.
SYNTHESIS_MODES = ("merge", "compare", "checklist", "ask")


def synthesis_framing(mode: str = "merge", *, keep: Sequence[str] = (), question: Optional[str] = None) -> SynthesisFraming:
    """The framing for a synthesis mode; ValueError for an unknown mode or a
    mode missing what it needs."""
    if mode == "merge":
        return INDEPENDENT
    if mode == "compare":
        return COMPARE
    if mode == "checklist":
        kept = [k.strip() for k in keep if k and k.strip()]
        if not kept:
            raise ValueError("A checklist synthesis needs at least one component to keep.")
        return checklist_merge(kept)
    if mode == "ask":
        if not (question or "").strip():
            raise ValueError("Asking about answers needs a question.")
        return ask_about(question.strip())
    raise ValueError(f"Unknown synthesis mode {mode!r}; one of {', '.join(SYNTHESIS_MODES)}.")


# ─── Checklist: the components to choose from ────────────────────

COMPONENT_LINE = re.compile(r"^\s*(\d+)[.)]\s*\[([^\]]*)\]\s*(.+?)\s*$")


def component_request(question: str, answers: Iterable[Tuple[str, str]]) -> str:
    """Ask a model to split the answers into components the reader can tick:
    one numbered line each, naming which answers contain it."""
    answers = list(answers)
    body = "\n\n".join(f"[{author}]:\n{content}" for author, content in answers)
    return (
        f"Original question: {question}\n\n"
        f"Answers from {len(answers)} models:\n\n{body}\n\n"
        "List the distinct components of these answers: each separate claim, "
        "recommendation, step or caveat, merged where answers say the same "
        "thing. One per line, in this exact form and nothing else:\n"
        "1. [answer names that contain it, comma-separated] the component in one sentence"
    )


@dataclass(frozen=True)
class Component:
    text: str
    sources: Tuple[str, ...]


def parse_components(text: str) -> list[Component]:
    """The numbered lines of a component_request reply. ValueError when there
    are none: an empty checklist would look like answers with nothing in them."""
    out = []
    for line in text.splitlines():
        m = COMPONENT_LINE.match(line)
        if m:
            sources = tuple(s.strip() for s in m.group(2).split(",") if s.strip())
            out.append(Component(text=m.group(3), sources=sources))
    if not out:
        raise ValueError("The model's reply listed no components in the expected form; try again or another model.")
    return out
