"""How debate participants are shown to each other, as interchangeable strategies.

A debating model reads its peers' previous answers. What it is told about who
wrote them is a variable in itself: models defer to majorities and to peers
they believe stronger, and a model id ("[claude-…]:") is exactly such a cue.
The same strategy labels the answers the agreement judge and the debate
synthesizer read, so none of the models weighing arguments sees who made them.

  AnonymousPeers  "Participant A/B/C…", assigned once per session from its id
                  (so round 1's "Participant B is wrong" still means B in
                  round 2) and listed in an order reshuffled every round, so
                  no participant is always read first. Both are seeded, so a
                  session's prompts are reproducible.
  NamedPeers      the model ids, in participant order: what debates did
                  before peers were anonymous.

The human-facing UI keeps showing display names whichever is used.
A session stores its choice by name (PEER_PRESENTATIONS).
"""

import random
from typing import Callable, Mapping, Protocol, Sequence


class PeerPresentation(Protocol):
    # Whether a round may run in the graph's deliberation mode, which tags
    # every earlier turn with its model id and tells the model its own id.
    names_in_history: bool

    def label(self, model_id: str) -> str:
        """What the other models (and the judge, and the synthesizer) call this participant."""
        ...

    def order(self, model_ids: Sequence[str], round_num: int) -> list[str]:
        """The order peers' answers are listed in for one round."""
        ...

    def introduce(self, model_id: str) -> str:
        """The sentence telling a participant who it is in the debate."""
        ...


def _letters(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA: a label for any number of participants."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


class AnonymousPeers:
    names_in_history = False

    def __init__(self, session_id: str, participants: Sequence[str]):
        self.session_id = session_id
        # Sorted first, so the mapping depends only on the session and who
        # takes part, not on the order the participants were listed in.
        shuffled = sorted(dict.fromkeys(participants))
        random.Random(f"{session_id}:labels").shuffle(shuffled)
        self._labels = {m: f"Participant {_letters(i)}" for i, m in enumerate(shuffled)}

    def label(self, model_id: str) -> str:
        return self._labels.get(model_id, "Participant ?")

    def order(self, model_ids: Sequence[str], round_num: int) -> list[str]:
        ordered = sorted(model_ids, key=self.label)
        random.Random(f"{self.session_id}:{round_num}").shuffle(ordered)
        return ordered

    def introduce(self, model_id: str) -> str:
        return (
            f"You are {self.label(model_id)}. Refer to the others by their labels, "
            "and don't say which model or company you are."
        )


class NamedPeers:
    names_in_history = True

    def __init__(self, session_id: str = "", participants: Sequence[str] = ()):
        pass

    def label(self, model_id: str) -> str:
        return model_id

    def order(self, model_ids: Sequence[str], round_num: int) -> list[str]:
        return list(model_ids)

    def introduce(self, model_id: str) -> str:
        return f"You are {model_id}."


PEER_PRESENTATIONS: Mapping[str, Callable[[str, Sequence[str]], PeerPresentation]] = {
    "anonymous": AnonymousPeers,
    "named": NamedPeers,
}

# New sessions: peers are anonymous unless a session asks otherwise.
DEFAULT_PEER_LABELS = "anonymous"
# Sessions stored before the choice existed ran with model ids: their
# prompts and replies already name each other, so anonymizing a later round
# or their synthesis would hide nothing and misdescribe what was run.
STORED_PEER_LABELS = "named"


def peer_presentation(peer_labels: str | None, session_id: str, participants: Sequence[str]) -> PeerPresentation:
    """The strategy a session names (a stored session without one: STORED_PEER_LABELS)."""
    return PEER_PRESENTATIONS[peer_labels or STORED_PEER_LABELS](session_id, participants)


def labelled(peers: PeerPresentation, responses: Mapping[str, str]) -> list[tuple[str, str]]:
    """(label, content) pairs in label order, for readers that see a whole
    round at once (the judge, the synthesizer) rather than one round's peers."""
    return [(peers.label(m), responses[m]) for m in sorted(responses, key=peers.label)]
