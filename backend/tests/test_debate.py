"""Tests for debate coordinator, convergence detection, and tree builder."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.debate import _build_round_prompts, create_session, make_synthesis_thread_id, make_thread_id
from app.services.convergence import _compute_sync, _cosine_similarity


# ─── Pure function tests ──────────────────────────────────────────────────────


def test_make_thread_id():
    assert make_thread_id("thread-abc", "debate-1", "claude-sonnet-4-6") == "thread-abc::debate-1::claude-sonnet-4-6"
    assert make_synthesis_thread_id("thread-abc", "debate-1") == "thread-abc::debate-1::synthesis"


def test_build_round_prompts_round_0():
    prompts = _build_round_prompts(
        round_num=0,
        prompt="Is Python better than JavaScript?",
        participants=["gpt-5.2", "claude-sonnet-4-6"],
        prev_round_responses={},
    )
    assert prompts["gpt-5.2"] == "Is Python better than JavaScript?"
    assert prompts["claude-sonnet-4-6"] == "Is Python better than JavaScript?"


def test_build_round_prompts_round_1_includes_peer_context():
    prompts = _build_round_prompts(
        round_num=1,
        prompt="Is Python better than JavaScript?",
        participants=["gpt-5.2", "claude-sonnet-4-6"],
        prev_round_responses={
            "gpt-5.2": "Python has better data science libraries.",
            "claude-sonnet-4-6": "JavaScript is essential for web development.",
        },
    )
    # gpt-5.2's prompt should contain claude's response, not its own
    assert "claude-sonnet-4-6" in prompts["gpt-5.2"]
    assert "JavaScript is essential" in prompts["gpt-5.2"]
    assert "Python has better" not in prompts["gpt-5.2"]

    # claude's prompt should contain gpt's response
    assert "gpt-5.2" in prompts["claude-sonnet-4-6"]
    assert "Python has better" in prompts["claude-sonnet-4-6"]
    assert "JavaScript is essential" not in prompts["claude-sonnet-4-6"]


def test_build_round_prompts_round_1_missing_peer_skipped():
    """If a participant has no previous response, they are skipped in peer context."""
    prompts = _build_round_prompts(
        round_num=1,
        prompt="Test prompt",
        participants=["model-a", "model-b"],
        prev_round_responses={"model-a": "response from a"},
        # model-b has no prior response
    )
    # model-a's prompt: no peer context for model-b
    assert "model-b" not in prompts["model-a"]
    # model-b's prompt: should include model-a's context
    assert "model-a" in prompts["model-b"]


# ─── Convergence tests ────────────────────────────────────────────────────────


def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_compute_sync_every_model_stable():
    # Create mock embeddings that return identical vectors → similarity = 1.0
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.side_effect = lambda text: [1.0, 0.0, 0.0]

    with patch("app.services.rag.get_embeddings", return_value=mock_embeddings):
        score, converged = _compute_sync(
            prev_responses={"m1": "text A", "m2": "text B"},
            curr_responses={"m1": "text A", "m2": "text B"},
            threshold=0.92,
        )
    assert score == pytest.approx(1.0)
    assert converged is True


def test_compute_sync_not_converged():
    vectors = {
        "prev_text": [1.0, 0.0, 0.0],
        "curr_text": [0.0, 1.0, 0.0],  # orthogonal → similarity = 0
    }
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.side_effect = lambda text: vectors.get(text, [0.0] * 3)

    with patch("app.services.rag.get_embeddings", return_value=mock_embeddings):
        score, converged = _compute_sync(
            prev_responses={"m1": "prev_text"},
            curr_responses={"m1": "curr_text"},
            threshold=0.92,
        )
    assert score == pytest.approx(0.0)
    assert converged is False


def test_compute_sync_one_stable_model_is_not_enough():
    def embed(text):
        return [1.0, 0.0, 0.0] if text == "same" else [0.0, 1.0, 0.0] if text == "different1" else [0.0, 0.0, 1.0]

    score, stable = _compute_sync(
        prev_responses={"m1": "same", "m2": "different1"},
        curr_responses={"m1": "same", "m2": "different2"},
        threshold=0.92,
        embed=embed,
    )
    assert score == pytest.approx(0.5)
    assert stable is False  # m1 = 1.0, but m2 moved


def test_compute_sync_empty_responses():
    mock_embeddings = MagicMock()
    with patch("app.services.rag.get_embeddings", return_value=mock_embeddings):
        score, converged = _compute_sync(
            prev_responses={},
            curr_responses={"m1": "text"},
            threshold=0.92,
        )
    assert score == 0.0
    assert converged is False


# ─── Session creation tests ───────────────────────────────────────────────────


def test_create_session_structure():
    with patch("app.services.debate.db.create_debate_session") as mock_create:
        session = create_session(
            parent_thread_id="thread-xyz",
            participants=["gpt-5.2", "claude-sonnet-4-6"],
            termination_policy={"max_rounds": 3, "convergence_threshold": None, "llm_judge": None, "mode": "all"},
        )

    assert session["parent_thread_id"] == "thread-xyz"
    assert session["participants"] == ["gpt-5.2", "claude-sonnet-4-6"]
    sid = session["session_id"]
    # Scoped to the session, and the synthesis thread is stored, not derived.
    assert session["thread_ids"] == {
        "gpt-5.2": f"thread-xyz::{sid}::gpt-5.2",
        "claude-sonnet-4-6": f"thread-xyz::{sid}::claude-sonnet-4-6",
        "synthesis": f"thread-xyz::{sid}::synthesis",
    }
    assert session["status"] == "running"
    assert session["current_round"] == 0
    assert session["session_id"].startswith("debate-")
    mock_create.assert_called_once()


# ─── run_debate event sequence test ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_debate_event_sequence():
    """Verify that run_debate yields the expected event types in order."""
    from app.services.debate import run_debate

    # Build a minimal mock graph_app that yields one on_chat_model_stream + on_chain_end
    async def fake_astream_events(state, config, version="v2", **_kwargs):
        chunk = MagicMock()
        chunk.content = "Hello"
        yield {"event": "on_chat_model_stream", "metadata": {"langgraph_node": "draft"}, "data": {"chunk": chunk}}

        output_msg = MagicMock()
        output_msg.type = "ai"
        output_msg.name = "gpt-5.2"
        output_msg.content = "Hello"
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "metadata": {"checkpoint_id": "cp-001"},
            "data": {"output": {"messages": [output_msg]}},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = fake_astream_events

    session_id = "debate-test-001"
    session_data = {
        "session_id": session_id,
        "parent_thread_id": "thread-parent",
        "participants": ["gpt-5.2", "claude-sonnet-4-6"],
        "thread_ids": {
            "gpt-5.2": "thread-parent::gpt-5.2",
            "claude-sonnet-4-6": "thread-parent::claude-sonnet-4-6",
        },
        "current_round": 0,
        "status": "running",
        "termination_policy": {"max_rounds": 1, "convergence_threshold": None, "llm_judge": None, "mode": "all"},
        "auto_synthesize": False,
        "synthesizer_model": None,
    }

    with patch("app.services.debate.db.get_debate_session", return_value=session_data), \
         patch("app.services.debate.db.get_thread_title", return_value="titled"), \
         patch("app.services.debate.db.update_debate_session"):

        events = []
        async for event in run_debate(
            graph_app=mock_graph,
            session_id=session_id,
            prompt="Test debate prompt",
            toggles={},
            documents={},
        ):
            events.append(event)

    event_types = [e["type"] for e in events]
    assert "debate_session_created" in event_types
    assert "debate_round_start" in event_types
    assert "stream_start" in event_types
    assert "stream_token" in event_types
    assert "stream_end" in event_types
    assert "debate_round_end" in event_types
    assert "debate_session_status" in event_types
    assert events[-1] == {"type": "debate_session_status", "session_id": session_id, "status": "completed"}
