"""The synthesis prompt: Arena's independent-answer merge and Debate's argument map."""

from app.services.synthesis import ARGUMENT_MAP, INDEPENDENT, SynthesisFraming, build_synthesis_prompt

ANSWERS = [("m1", "yes"), ("m2", "no")]


def test_arena_prompt_is_unchanged():
    # Arena merges independent answers into one; the debate's argument map
    # must not leak into it. Pinned as a literal so any drift shows.
    assert build_synthesis_prompt("Q?", ANSWERS, INDEPENDENT) == (
        "Original question: Q?\n\n"
        "Independent answers from 2 models:\n\n"
        "[m1]:\nyes\n\n[m2]:\nno\n\n"
        "Synthesize these into one answer. State where the models agree, resolve "
        "or flag where they contradict each other, and keep the strongest "
        "supported points. Attribute claims to models where it matters."
    )


def test_the_framing_supplies_both_the_description_and_the_instruction():
    framing = SynthesisFraming(described_as="{n} things", instruction="Do X.")
    assert build_synthesis_prompt("Q?", ANSWERS, framing) == (
        "Original question: Q?\n\n2 things:\n\n[m1]:\nyes\n\n[m2]:\nno\n\nDo X."
    )


def test_debate_asks_for_an_argument_map_not_an_answer():
    debate = build_synthesis_prompt("Q?", ANSWERS, ARGUMENT_MAP)
    assert "[m1]:\nyes" in debate and "[m2]:\nno" in debate
    assert "A debate between 2 participants" in debate
    # The sections the reader needs to judge the debate themselves.
    for section in ("Positions:", "Arguments:", "Changes of position:", "Unresolved:"):
        assert section in debate
    assert "came without a new argument" in debate
    assert "what information would settle" in debate
    # Round 1 is marked as the participants' independent answers.
    assert "Round 1 is its independent answer" in debate
    # It does not pick a side or present agreement as the result.
    assert "Do not declare a winner or a consensus" in debate
    assert "Agreement reached by debating is not evidence by itself" in debate
    # Arena's merge instruction is not in it.
    assert "Synthesize these into one answer" not in debate
