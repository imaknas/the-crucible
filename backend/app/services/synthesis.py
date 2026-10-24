"""The prompt a synthesizer model answers, shared by Arena and Debate.

Both ask for the same thing: one answer that keeps what the models agree on
and flags what they don't. Only the description of the answers differs —
Arena's were written independently, a debate's after the models had read
each other, so agreement among them is weaker evidence.
"""

from typing import Iterable, Tuple

INDEPENDENT = "Independent answers from {n} models"
AFTER_DEBATE = (
    "Final positions of {n} models after debating each other. They read each "
    "other's arguments, so agreement among them is not evidence by itself"
)


def build_synthesis_prompt(question: str, answers: Iterable[Tuple[str, str]], described_as: str) -> str:
    """`answers` is (model, content) pairs; `described_as` is INDEPENDENT or
    AFTER_DEBATE, with `{n}` for the number of answers."""
    answers = list(answers)
    body = "\n\n".join(f"[{model}]:\n{content}" for model, content in answers)
    return (
        f"Original question: {question}\n\n"
        f"{described_as.format(n=len(answers))}:\n\n{body}\n\n"
        "Synthesize these into one answer. State where the models agree, resolve "
        "or flag where they contradict each other, and keep the strongest "
        "supported points. Attribute claims to models where it matters."
    )
