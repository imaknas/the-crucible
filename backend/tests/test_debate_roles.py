"""Who judges and who writes the argument map, and how fairly they read.

Models favour text they recognise as their own, and LLM judges have a
systematic position bias: the map is written by a model outside the debate
when one has a key, the agreement judge reads the answers in both orders,
and a judge or synthesizer that is also debating is named in a warning."""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from app.llm import CallableModelFactory
from app.services import debate as debate_svc
from app.services.convergence import JudgeCheck
from app.services.peers import AnonymousPeers

GPT, CLAUDE, GEMINI = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"
ALL_KEYS = {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GOOGLE_API_KEY": "k"}


def test_the_default_synthesizer_comes_from_a_provider_that_is_not_debating():
    chosen = debate_svc.default_synthesizer([GPT, CLAUDE], env=ALL_KEYS)
    assert chosen.startswith("gemini")


def test_an_outsider_needs_a_key():
    env = {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k"}
    assert debate_svc.default_synthesizer([GPT, CLAUDE], env=env) == GPT


def test_with_every_provider_debating_the_first_participant_writes_it():
    assert debate_svc.default_synthesizer([GPT, CLAUDE, GEMINI], env=ALL_KEYS) == GPT


def _session(**kw):
    return {
        "session_id": "s",
        "participants": [GPT, CLAUDE],
        "termination_policy": {"llm_judge": None},
        "auto_synthesize": True,
        "synthesizer_model": GEMINI,
        **kw,
    }


def test_no_warning_when_judge_and_synthesizer_are_outsiders():
    assert debate_svc.role_warnings(_session(termination_policy={"llm_judge": GEMINI})) == []


def test_a_debating_synthesizer_and_judge_are_each_named():
    warnings = debate_svc.role_warnings(_session(synthesizer_model=GPT, termination_policy={"llm_judge": CLAUDE}))
    assert len(warnings) == 2
    assert "writes the argument map and is also debating" in warnings[0]
    assert "judges agreement and is also debating" in warnings[1]


def test_a_session_that_writes_no_map_warns_about_no_synthesizer():
    assert debate_svc.role_warnings(_session(auto_synthesize=False, synthesizer_model=None)) == []


# ─── The judge reads both orders ─────────────────────────────────


class _OrderSensitiveJudge:
    """Says yes only when Participant A's answer comes first: a pure
    position bias, which reading both orders must cancel."""

    def __init__(self):
        self.prompts = []

    def invoke(self, messages):
        prompt = messages[0].content
        self.prompts.append(prompt)
        first = prompt.index("[Participant A]") < prompt.index("[Participant B]")
        return AIMessage(content="CONVERGED: yes, same answer" if first else "CONVERGED: no, they differ")


def _judge(model):
    peers = AnonymousPeers("s", [GPT, CLAUDE])
    return JudgeCheck(GEMINI, peers, factory=CallableModelFactory(lambda _id, _t: model))


def test_a_verdict_that_flips_with_the_order_does_not_count():
    model = _OrderSensitiveJudge()
    verdict = asyncio.run(_judge(model).evaluate({}, {GPT: "yes", CLAUDE: "yes"}))
    assert not verdict.converged
    assert "changed with the order" in verdict.reason
    # Both orders were asked, with the same answers.
    assert len(model.prompts) == 2 and model.prompts[0] != model.prompts[1]


@pytest.mark.parametrize("answer, converged", [("CONVERGED: yes, same", True), ("CONVERGED: no, apart", False)])
def test_a_verdict_both_orders_agree_on_stands(answer, converged):
    class Steady:
        def invoke(self, messages):
            return AIMessage(content=answer)

    verdict = asyncio.run(_judge(Steady()).evaluate({}, {GPT: "a", CLAUDE: "b"}))
    assert verdict.converged is converged
    assert "error" not in verdict.reason.lower()


class _MiddleFavouringJudge:
    """Says yes only when Participant B's answer sits in the middle of three:
    reversing the order would keep it there; rotating doesn't."""

    def __init__(self):
        self.prompts = []

    def invoke(self, messages):
        prompt = messages[0].content
        self.prompts.append(prompt)
        order = sorted(["A", "B", "C"], key=lambda x: prompt.index(f"[Participant {x}]"))
        return AIMessage(content="CONVERGED: yes, fine" if order[1] == "B" else "CONVERGED: no, apart")


def test_with_three_answers_every_answer_takes_every_position():
    model = _MiddleFavouringJudge()
    peers = AnonymousPeers("s", [GPT, CLAUDE, GEMINI])
    judge = JudgeCheck(GEMINI, peers, factory=CallableModelFactory(lambda _id, _t: model))
    verdict = asyncio.run(judge.evaluate({}, {GPT: "x", CLAUDE: "y", GEMINI: "z"}))
    assert not verdict.converged
    assert len(model.prompts) == 3
    firsts = {p[p.index("[Participant"):][:14] for p in model.prompts}
    assert len(firsts) == 3  # each participant led one reading


def test_the_referee_list_is_its_own_list():
    """The referee shortlist is kept apart from the default debate, which it
    has to outnumber by a family to ever find an outsider."""
    from app.registry import DEFAULT_ARENA_MODELS, REFEREE_MODELS

    assert REFEREE_MODELS is not DEFAULT_ARENA_MODELS
    assert set(DEFAULT_ARENA_MODELS) <= set(REFEREE_MODELS)
