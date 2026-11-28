"""Ways to ask for a synthesis: merge (one answer), compare (a table of
differences), issues (every problem the answers raise), checklist (one answer from the components the reader keeps)
and ask (the reader's own question about the answers), across any branches.

The CLI, MCP and the chat socket reach the same service; the reply records
its mode (and the reader's question) so the tree and transcript can say what
it is."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.llm import CallableModelFactory, use_model_factory
from app.registry import display_name
from app.services import arena, history
from app.services.synthesis import COMPARE, INDEPENDENT, ISSUES, SYNTHESIS_MODES, parse_components, synthesis_framing
from tests.storage_helpers import point

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B, C = "gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"
COMPONENTS = "1. [GPT-5.4, Claude Sonnet 5] Start with a monolith.\n2. [Claude Sonnet 5] Split out billing first."
SEEN: list = []


def _text(content) -> str:
    if isinstance(content, list):
        return "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


class _Recorder(FakeListChatModel):
    """Answers with a fixed reply and records every prompt it gets."""

    def _call(self, messages, *args, **kwargs):
        SEEN.append(_text(messages[-1].content))
        return super()._call(messages, *args, **kwargs)

    def _stream(self, messages, *args, **kwargs):
        SEEN.append(_text(messages[-1].content))
        yield from super()._stream(messages, *args, **kwargs)


def _model(model_id, _toggles):
    # C writes component lists; A and B answer.
    return _Recorder(responses=[COMPONENTS if model_id == C else f"reply from {model_id}"])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    SEEN.clear()
    point(monkeypatch, db_path=str(tmp_path / "modes.sqlite"))
    monkeypatch.setattr("app.cli._load_env", lambda: None)
    with use_model_factory(CallableModelFactory(_model)), patch.dict(os.environ, KEYS):
        yield


async def _turn(graph_app, thread_id, prompt="Monolith or microservices?"):
    result = await arena.collect(arena.run_arena(graph_app, prompt, thread_id, [A, B], {}, synthesizer=None))
    return [result["answers"][m]["checkpoint_id"] for m in (A, B)]


# ─── Framings ────────────────────────────────────────────────────


def test_each_mode_has_its_framing_and_says_what_it_lacks():
    assert synthesis_framing("merge") is INDEPENDENT
    assert synthesis_framing("compare") is COMPARE
    assert synthesis_framing("issues") is ISSUES
    assert "Keep this" in synthesis_framing("checklist", keep=["Keep this"]).instruction
    assert "Why?" in synthesis_framing("ask", question="Why?").instruction
    for mode, kwargs, message in [
        ("checklist", {}, "component to keep"),
        ("ask", {"question": "  "}, "needs a question"),
        ("vote", {}, "Unknown synthesis mode"),
    ]:
        with pytest.raises(ValueError, match=message):
            synthesis_framing(mode, **kwargs)


def test_every_mode_builds_a_framing():
    for mode in SYNTHESIS_MODES:
        assert synthesis_framing(mode, keep=["a part"], question="Why?").instruction


def test_the_issue_list_keeps_a_problem_one_reviewer_raised_and_leaves_judging_it_to_the_reader():
    """A union, not a vote: dropping or ranking problems by how many reviews
    raise them would lose the one only one reviewer saw."""
    text = ISSUES.instruction
    assert "keep problems that only one review raises" in text
    assert "don't order or drop any by how many reviews raise it" in text
    assert "Raised by:" in text
    assert "Don't judge whether a problem holds" in text


def test_components_parse_from_numbered_lines_and_an_empty_list_is_an_error():
    parsed = parse_components("Here you go:\n" + COMPONENTS)
    assert [(c.text, c.sources) for c in parsed] == [
        ("Start with a monolith.", ("GPT-5.4", "Claude Sonnet 5")),
        ("Split out billing first.", ("Claude Sonnet 5",)),
    ]
    with pytest.raises(ValueError, match="no components"):
        parse_components("I can't split these.")


def test_answers_to_different_questions_are_labelled_with_theirs():
    blind = arena.blind_labels([
        {"model": A, "content": "x", "question": "Q1?"},
        {"model": A, "content": "y", "question": "Q2?"},
    ])
    assert "several questions" in blind.question
    assert [label for label, _ in blind.pairs] == ["Answer A, answering: Q1?", "Answer B, answering: Q2?"]
    named = arena.named_labels([
        {"model": A, "content": "x", "question": "Q1?"},
        {"model": A, "content": "y", "question": "Q2?"},
    ])
    assert [label for label, _ in named.pairs] == ["GPT-5.4 #1, answering: Q1?", "GPT-5.4 #2, answering: Q2?"]
    assert named.legend == []


def test_one_turns_answers_take_the_letters_blind_comparison_gives_them():
    from app.services.votes import blind_order

    answers = [{"model": m, "content": f"from {m}", "question": "Q?", "turn_id": "turn-1", "checkpoint_id": f"cp-{m}"}
               for m in (A, B, C)]
    labelled = arena.blind_labels(answers)
    assert [a["model"] for a in labelled.answers] == blind_order("turn-1", [A, B, C])
    assert [label for label, _ in labelled.pairs] == ["Answer A", "Answer B", "Answer C"]
    assert [(e["label"], e["model"], e["checkpoint_id"]) for e in labelled.legend] == [
        (f"Answer {x}", m, f"cp-{m}") for x, m in zip("ABC", blind_order("turn-1", [A, B, C]))
    ]
    # No model is named to the synthesizer, angles still are.
    angled = arena.blind_labels([{**answers[0], "angle": "security"}, answers[1]])
    prompt = "\n".join(label for label, _ in angled.pairs)
    assert "GPT" not in prompt and "Claude" not in prompt and "(asked to answer from this angle: security)" in prompt
    # A model's reply names answers back by letter; anything else isn't one.
    first = labelled.answers[0]["model"]
    assert labelled.model_of("Answer A") == labelled.model_of("answer a.") == first
    assert labelled.model_of("Answer A (asked to answer from this angle: security)") == first
    assert labelled.model_of("Answer Z") is None and labelled.model_of("all answers") is None


def test_only_a_readers_own_question_shows_the_answers_by_name():
    answers = [{"model": A, "content": "x", "question": "Q?"}, {"model": B, "content": "y", "question": "Q?"}]
    for mode, kw in (("merge", {}), ("compare", {}), ("issues", {}), ("checklist", {"keep": ["x"]})):
        ask = arena.synthesis_ask(answers, mode, **kw)
        assert "[Answer A]:" in ask.prompt and "GPT-5.4" not in ask.prompt, mode
        assert ask.note["crucible_synthesis_labels"] == f"A={A},B={B}"
    ask = arena.synthesis_ask(answers, "ask", question="What did GPT-5.4 get wrong?")
    assert "[GPT-5.4]:" in ask.prompt and ask.legend == [] and "crucible_synthesis_labels" not in ask.note


def test_panel_warnings_say_what_weakens_the_answers():
    from app.registry import DEFAULT_ARENA_MODELS

    keyed = DEFAULT_ARENA_MODELS[:1]
    [dropped] = arena.panel_warnings(None, keyed)
    assert "No API key for" in dropped and "only" in dropped
    # Asked for by name: no warning about defaults; one provider is one.
    assert arena.panel_warnings(["gpt-5.4", "gpt-5.4-mini"], ["gpt-5.4", "gpt-5.4-mini"]) == [
        "Every answer comes from one provider (OpenAI): their mistakes tend to be alike, "
        "so agreement between them is weak evidence."
    ]
    [own] = arena.panel_warnings([A, B], [A, B], synthesizer=A)
    assert "also answered" in own
    assert arena.panel_warnings([A, B], [A, B], synthesizer=C) == []
    # One model with no synthesis is a chat turn.
    assert arena.panel_warnings([A], [A]) == []


# ─── Through the graph ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_comparison_is_a_synthesis_reply_that_says_it_compares():
    async with arena.open_graph() as graph_app:
        ids = await _turn(graph_app, "t-compare")
        SEEN.clear()
        result = await arena.collect(arena.synthesize_thread(graph_app, "t-compare", A, checkpoint_ids=ids, mode="compare"))
        tree = await history.thread_tree(graph_app, "t-compare")
        path = await history.path_at(graph_app, "t-compare", result["synthesis"]["checkpoint_id"])

    assert "A table with one row per point" in SEEN[-1]
    node = next(n for n in tree["nodes"] if n["id"] == result["synthesis"]["checkpoint_id"])
    assert (node["type"], node["metadata"]["synthesis_mode"]) == ("synthesis", "compare")
    reply = path["messages"][-1] if isinstance(path, dict) else path[-1]
    assert (reply["kind"], reply["synthesis_mode"]) == ("synthesis", "compare")


@pytest.mark.asyncio
async def test_an_issue_list_is_a_synthesis_reply_that_says_it_lists_problems():
    async with arena.open_graph() as graph_app:
        ids = await _turn(graph_app, "t-issues")
        SEEN.clear()
        result = await arena.collect(arena.synthesize_thread(graph_app, "t-issues", A, checkpoint_ids=ids, mode="issues"))
        tree = await history.thread_tree(graph_app, "t-issues")

    assert "List every problem" in SEEN[-1] and "Independent reviews from 2 models" in SEEN[-1]
    node = next(n for n in tree["nodes"] if n["id"] == result["synthesis"]["checkpoint_id"])
    assert (node["type"], node["metadata"]["synthesis_mode"]) == ("synthesis", "issues")


@pytest.mark.asyncio
async def test_an_arena_synthesis_records_the_answers_it_merged():
    async with arena.open_graph() as graph_app:
        result = await arena.collect(arena.run_arena(graph_app, "Q?", "t-auto", [A, B], {}, synthesizer=A))
        tree = await history.thread_tree(graph_app, "t-auto")
    node = next(n for n in tree["nodes"] if n["id"] == result["synthesis"]["checkpoint_id"])
    # In the order the synthesizer read them, lettered, with who each one is.
    legend = node["metadata"]["synthesis_legend"]
    assert node["metadata"]["synthesis_answers"] == [e["checkpoint_id"] for e in legend]
    assert {e["checkpoint_id"]: e["model"] for e in legend} == {result["answers"][m]["checkpoint_id"]: m for m in (A, B)}
    assert [e["label"] for e in legend] == ["Answer A", "Answer B"] and result["synthesis"]["legend"] == legend
    assert "GPT-5.4" not in SEEN[-1] and "[Answer A]:" in SEEN[-1]


@pytest.mark.asyncio
async def test_asking_about_answers_from_two_branches_keeps_the_question():
    async with arena.open_graph() as graph_app:
        first = await _turn(graph_app, "t-ask", "First question?")
        second = await _turn(graph_app, "t-ask", "Second question?")
        SEEN.clear()
        result = await arena.collect(arena.synthesize_thread(
            graph_app, "t-ask", A, checkpoint_ids=[first[0], second[1]], mode="ask", question="Which is riskier?"))
        tree = await history.thread_tree(graph_app, "t-ask")

    assert "Which is riskier?" in SEEN[-1]
    assert "answering: First question?" in SEEN[-1] and "answering: Second question?" in SEEN[-1]
    node = next(n for n in tree["nodes"] if n["id"] == result["synthesis"]["checkpoint_id"])
    assert node["metadata"]["synthesis_question"] == "Which is riskier?"
    # The replies it was written from, so the transcript can show them above it.
    assert node["metadata"]["synthesis_answers"] == [first[0], second[1]]


@pytest.mark.asyncio
async def test_a_checklist_lists_components_without_writing_then_merges_the_kept_ones():
    async with arena.open_graph() as graph_app:
        ids = await _turn(graph_app, "t-check")
        before = len((await history.thread_tree(graph_app, "t-check"))["nodes"])
        components = (await arena.answer_components(graph_app, "t-check", ids, C))["components"]
        assert len((await history.thread_tree(graph_app, "t-check"))["nodes"]) == before  # nothing written
        SEEN.clear()
        result = await arena.collect(arena.synthesize_thread(
            graph_app, "t-check", A, checkpoint_ids=ids, mode="checklist", keep=[components[1]["text"]]))

    assert [c["text"] for c in components] == ["Start with a monolith.", "Split out billing first."]
    assert "- Split out billing first." in SEEN[-1] and "Start with a monolith" not in SEEN[-1].split("keep:")[-1]
    assert result["synthesis"]["error"] is None


@pytest.mark.asyncio
async def test_a_component_list_read_by_letter_names_its_sources_by_model():
    lettered = "1. [Answer A, Answer B] Start with a monolith.\n2. [answer b] Split out billing first.\n3. [all answers] Test."
    async with arena.open_graph() as graph_app:
        ids = await _turn(graph_app, "t-letters")
        with use_model_factory(CallableModelFactory(lambda m, _t: _Recorder(responses=[lettered]))):
            SEEN.clear()
            listed = await arena.answer_components(graph_app, "t-letters", ids)
    shown = arena.blind_labels([{"model": m, "content": ""} for m in (A, B)])  # no turn ids: in the order given
    assert "[Answer A]:" in SEEN[-1] and "GPT-5.4" not in SEEN[-1]
    first, second = (display_name(a["model"]) for a in shown.answers)
    assert [c["sources"] for c in listed["components"]] == [[first, second], [second], ["all answers"]]


# ─── CLI and MCP ─────────────────────────────────────────────────


runner = CliRunner()


def _cli(*args):
    return runner.invoke(cli_app, list(args))


def test_cli_modes():
    assert _cli("arena", "Q?", "-m", A, "-m", B, "--no-synthesize", "-t", "t-cli").exit_code == 0
    compare = json.loads(_cli("synthesize", "-t", "t-cli", "--mode", "compare", "--format", "json").stdout)
    assert compare["synthesis"]["error"] is None

    listed = _cli("synthesize", "-t", "t-cli", "--mode", "checklist", "-j", C, "--format", "json")
    assert listed.exit_code == 0, listed.stderr
    texts = [c["text"] for c in json.loads(listed.stdout)["components"]]
    assert texts == ["Start with a monolith.", "Split out billing first."]

    kept = _cli("synthesize", "-t", "t-cli", "--mode", "checklist", "--keep", texts[0], "--format", "json")
    assert kept.exit_code == 0 and json.loads(kept.stdout)["synthesis"]["error"] is None

    assert _cli("synthesize", "-t", "t-cli", "--mode", "ask").exit_code == 2  # needs --question
    assert _cli("synthesize", "-t", "t-cli", "--mode", "vote").exit_code == 2


@pytest.mark.asyncio
async def test_mcp_modes():
    from app.mcp_server import mcp

    async with Client(mcp) as client:
        turn = (await client.call_tool("invoke_arena", {"prompt": "Q?", "models": [A, B], "synthesize": False})).data
        thread = turn["thread_id"]
        listed = (await client.call_tool("list_answer_components", {"thread_id": thread, "model": C})).data
        assert [c["text"] for c in listed["components"]][0] == "Start with a monolith."
        asked = (await client.call_tool(
            "synthesize_answers", {"thread_id": thread, "mode": "ask", "question": "Which is cheaper?"})).data
        assert asked["synthesis"]["error"] is None
        with pytest.raises(ToolError, match="component to keep"):
            await client.call_tool("synthesize_answers", {"thread_id": thread, "mode": "checklist"})


def test_the_chat_socket_synthesizes_in_the_mode_its_frame_names():
    from fastapi.testclient import TestClient

    from app.main import server

    with TestClient(server) as client:
        with client.websocket_connect("/ws/t-sock") as ws:
            for model in (A, B):
                ws.send_json({"message": "Q?", "model": model})
            ends = []
            while len(ends) < 2:
                msg = ws.receive_json()
                if msg["type"] == "stream_end":
                    ends.append(msg["checkpoint_id"])
            SEEN.clear()
            ws.send_json({"type": "synthesis", "model": A, "answer_checkpoint_ids": ends,
                          "synthesis_mode": "ask", "synthesis_question": "Which is simpler?"})
            while (msg := ws.receive_json())["type"] not in ("stream_end", "error"):
                pass
        tree = client.get("/history/t-sock").json()
        bad = client.post("/synthesis/components", json={"thread_id": "t-sock", "checkpoint_ids": ends[:1]})

    assert msg["type"] == "stream_end", msg
    assert "Which is simpler?" in SEEN[-1]
    node = next(n for n in tree["nodes"] if n["id"] == msg["checkpoint_id"])
    assert (node["metadata"]["synthesis_mode"], node["metadata"]["synthesis_question"]) == ("ask", "Which is simpler?")
    assert node["metadata"]["synthesis_answers"] == ends
    reply = tree["messages"][-1]
    assert (reply["kind"], reply["synthesis_answers"]) == ("synthesis", ends)
    assert bad.status_code == 400 and "at least two answers" in bad.json()["detail"]
