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

from dataclasses import dataclass
from typing import Iterable, Tuple


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
