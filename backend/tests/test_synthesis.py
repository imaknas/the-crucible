"""The synthesis prompt Arena and Debate share."""

from app.services.synthesis import AFTER_DEBATE, INDEPENDENT, build_synthesis_prompt


def test_arena_and_debate_ask_for_the_same_synthesis():
    answers = [("m1", "yes"), ("m2", "no")]
    arena = build_synthesis_prompt("Q?", answers, INDEPENDENT)
    debate = build_synthesis_prompt("Q?", answers, AFTER_DEBATE)
    for prompt in (arena, debate):
        assert "[m1]:\nyes" in prompt and "[m2]:\nno" in prompt
        assert "flag where they contradict each other" in prompt
    assert "Independent answers from 2 models" in arena
    # A debate's agreement came from the models reading each other; the
    # synthesizer is told so instead of being asked for a consensus.
    assert "not evidence by itself" in debate
    assert "consensus" not in debate.lower()
