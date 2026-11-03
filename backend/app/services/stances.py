"""How a debate's participants are told to argue: a strategy per session,
selected by the stored stance (debate_sessions.stance), like peers.py for
how they see each other.

- ``OpenStance``: each says what it thinks; Round 1 is its independent
  answer and later rounds may change position for a new argument. The
  original debate.
- ``AssignedSides``: each argues the side it was given, whatever it thinks:
  the setup in which debate measurably helps the person judging (Khan et
  al. 2024, Kenton et al. 2024), who sees the strongest case for every side.
  Round 1 is each one's opening case. Everyone knows the sides: they are
  shown beside the labels.
- ``DevilsAdvocate``: one participant answers Round 1 independently like
  the others, then argues against whatever the others hold in common. The
  others are not told which participant it is (they would discount it);
  the person, the synthesizer and the record are.

Neither assigned stance can stop early on agreement: nobody is meant to
agree. The stability check still can ("answers stopped changing").
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol, Sequence

from app.services.synthesis import ADVOCATE_MAP, ARGUMENT_MAP, ASSIGNED_SIDES_MAP, SynthesisFraming

STANCE_MODES = ("open", "sides", "advocate")
SIDE_MAX_CHARS = 200
_NO_INVENTION = "Don't invent facts, sources or quotes."


class Stance(Protocol):
    mode: str
    # An LLM judge looking for agreement makes sense.
    allows_agreement_check: bool
    # How the synthesizer is asked to map the debate.
    framing: SynthesisFraming
    # What a question's first round is, in the transcript and the record.
    first_round_label: str

    def first_round(self, model: str) -> Optional[str]:
        """Added to the question in a question's first round, or None."""
        ...

    def closing(self, model: str, introduce: str) -> Optional[str]:
        """The instruction ending a later round's prompt (it replaces the open
        one), or None for the open instruction. ``introduce`` is the peer
        presentation's sentence telling the model who it is."""
        ...

    def public_note(self, model: str) -> Optional[str]:
        """Shown beside the model's label to the other participants."""
        ...

    def note(self, model: str) -> Optional[str]:
        """Shown to the person, the synthesizer and the debate's record."""
        ...

    def describe(self) -> Dict[str, Any]:
        """The stored form: {mode, sides: {model: side} | None, advocate}."""
        ...


@dataclass(frozen=True)
class OpenStance:
    mode: str = "open"
    allows_agreement_check: bool = True
    framing: SynthesisFraming = ARGUMENT_MAP
    first_round_label: str = "independent answer"

    def first_round(self, model: str) -> Optional[str]:
        return None

    def closing(self, model: str, introduce: str) -> Optional[str]:
        return None

    def public_note(self, model: str) -> Optional[str]:
        return None

    def note(self, model: str) -> Optional[str]:
        return None

    def describe(self) -> Dict[str, Any]:
        return {"mode": "open", "sides": None, "advocate": None}


@dataclass(frozen=True)
class AssignedSides:
    sides: Mapping[str, str] = field(default_factory=dict)
    mode: str = "sides"
    allows_agreement_check: bool = False
    framing: SynthesisFraming = ASSIGNED_SIDES_MAP
    first_round_label: str = "opening case"

    def first_round(self, model: str) -> Optional[str]:
        return (
            f"You have been assigned a side in a debate. Your side: {self.sides[model]}\n"
            "Make the strongest honest case for it, whatever you think yourself. "
            f"{_NO_INVENTION} If part of your side can't be defended honestly, say so and defend what you can."
        )

    def closing(self, model: str, introduce: str) -> Optional[str]:
        return (
            f"{introduce} Your assigned side is still: {self.sides[model]}. Answer the other sides' strongest "
            "arguments directly, show where they fail, and strengthen your own case. Don't switch sides. "
            f"{_NO_INVENTION} Where a point against your side is right, concede that point and say why your side "
            "still holds."
        )

    def public_note(self, model: str) -> Optional[str]:
        return f"arguing: {self.sides[model]}"

    def note(self, model: str) -> Optional[str]:
        return f"assigned to argue: {self.sides[model]}"

    def describe(self) -> Dict[str, Any]:
        return {"mode": "sides", "sides": dict(self.sides), "advocate": None}


@dataclass(frozen=True)
class DevilsAdvocate:
    advocate: str = ""
    mode: str = "advocate"
    allows_agreement_check: bool = False
    framing: SynthesisFraming = ADVOCATE_MAP
    first_round_label: str = "independent answer"

    def first_round(self, model: str) -> Optional[str]:
        # Everyone's first answer is their own, the advocate's included: what
        # it thinks is worth having beside what it argues later.
        return None

    def closing(self, model: str, introduce: str) -> Optional[str]:
        if model != self.advocate:
            return None
        return (
            f"{introduce} Your role from now on: devil's advocate. Find what the other participants now hold in "
            "common and argue against it as strongly as you honestly can: the best counterarguments, evidence "
            f"they overlooked, cases where it fails. You don't have to believe it. {_NO_INVENTION}"
        )

    def public_note(self, model: str) -> Optional[str]:
        return None

    def note(self, model: str) -> Optional[str]:
        return "devil's advocate from round 2" if model == self.advocate else None

    def describe(self) -> Dict[str, Any]:
        return {"mode": "advocate", "sides": None, "advocate": self.advocate}


OPEN = OpenStance()


def stance_from(stored: Optional[Mapping[str, Any]]) -> Stance:
    """The strategy for a stored stance; None (sessions from before stances) is open."""
    mode = (stored or {}).get("mode") or "open"
    if mode == "sides":
        return AssignedSides(dict(stored["sides"]))
    if mode == "advocate":
        return DevilsAdvocate(stored["advocate"])
    return OPEN


def check_stance(stance: Optional[Mapping[str, Any]], participants: Sequence[str], judge: Optional[str]) -> None:
    """ValueError (with a caller-facing message) if the stance can't run with these participants."""
    if not stance:
        return
    mode = stance.get("mode") or "open"
    if mode not in STANCE_MODES:
        raise ValueError(f"The stance is one of: {', '.join(STANCE_MODES)}")
    if mode != "open" and judge:
        raise ValueError(
            "An agreement judge can't be used with assigned sides or a devil's advocate: nobody is meant to agree. "
            "Stop on stability or the round count instead."
        )
    if mode == "sides":
        sides = stance.get("sides") or {}
        missing = [m for m in participants if not str(sides.get(m) or "").strip()]
        if missing:
            raise ValueError(f"Every participant needs a side; none for: {', '.join(missing)}")
        if any(m not in participants for m in sides):
            raise ValueError("Sides are given only to the debate's participants.")
        if any(len(str(s)) > SIDE_MAX_CHARS for s in sides.values()):
            raise ValueError(f"A side is at most {SIDE_MAX_CHARS} characters.")
        if len({" ".join(str(sides[m]).split()).lower() for m in participants}) < 2:
            raise ValueError("Assigned sides need at least two different sides.")
    if mode == "advocate" and stance.get("advocate") not in participants:
        raise ValueError("The devil's advocate must be one of the participants.")


def stance_from_choices(
    participants: Sequence[str], sides: Optional[Sequence[str]] = None, advocate: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """A stance from the CLI's and MCP's simpler arguments: ``sides`` given to
    the participants in turn (round-robin), or one ``advocate``. None for an
    open debate. ValueError for both at once."""
    if sides and advocate:
        raise ValueError("Choose assigned sides or a devil's advocate, not both.")
    if sides:
        cleaned = [" ".join(s.split()) for s in sides]
        return {"mode": "sides", "sides": {m: cleaned[i % len(cleaned)] for i, m in enumerate(participants)},
                "advocate": None}
    if advocate:
        return {"mode": "advocate", "sides": None, "advocate": advocate}
    return None


def noted(stance: Stance, label: str, model: str) -> str:
    """A label with the stance's note for the person and the synthesizer: "Participant A (assigned to argue: Yes)"."""
    note = stance.note(model)
    return f"{label} ({note})" if note else label
