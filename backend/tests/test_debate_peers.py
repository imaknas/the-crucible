"""How debate participants are presented to each other (services/peers.py)."""

import re

import pytest

from app.core import database as db
from app.services import debate as debate_svc
from app.services.debate import _build_round_prompts, check_session_config
from app.services.peers import (
    PEER_PRESENTATIONS,
    AnonymousPeers,
    NamedPeers,
    labelled,
    peer_presentation,
)

MODELS = ["gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"]
PREV = {m: f"Position held by participant number {i}." for i, m in enumerate(MODELS)}
POLICY = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": None, "mode": "all"}
BRANDS = ("gpt", "claude", "gemini", "openai", "anthropic", "google")


def _prompts(peers, round_num=1, prev=PREV):
    return _build_round_prompts(round_num, "Which is better?", MODELS, dict(prev), peers)


# ─── Anonymous ───────────────────────────────────────────────────


def test_anonymous_prompts_name_no_model():
    for model_id, prompt in _prompts(AnonymousPeers("debate-1", MODELS)).items():
        lowered = prompt.lower()
        assert not [b for b in BRANDS if b in lowered], prompt
        assert "Participant" in prompt


def test_a_participant_is_told_its_label_and_reads_only_its_peers():
    peers = AnonymousPeers("debate-1", MODELS)
    prompts = _prompts(peers)
    for model_id, prompt in prompts.items():
        assert f"You are {peers.label(model_id)}." in prompt
        assert f"[{peers.label(model_id)}]:" not in prompt
        assert PREV[model_id] not in prompt
        assert all(PREV[p] in prompt for p in MODELS if p != model_id)


def test_labels_are_the_same_in_every_prompt_of_a_round():
    peers = AnonymousPeers("debate-1", MODELS)
    for model_id, prompt in _prompts(peers).items():
        for peer in MODELS:
            if peer != model_id:
                assert f"[{peers.label(peer)}]:\n{PREV[peer]}" in prompt


def test_labels_hold_for_the_whole_session():
    """Round 1's "Participant B is wrong" is read again in round 2: the letter
    has to keep meaning the same participant."""
    peers = AnonymousPeers("debate-1", MODELS)
    labels = {m: peers.label(m) for m in MODELS}
    assert sorted(labels.values()) == ["Participant A", "Participant B", "Participant C"]
    for round_num in range(1, 6):
        for model_id, prompt in _prompts(peers, round_num).items():
            for peer in MODELS:
                if peer != model_id:
                    assert f"[{labels[peer]}]:\n{PREV[peer]}" in prompt


def test_anonymous_prompts_are_reproducible():
    first = [_prompts(AnonymousPeers("debate-1", MODELS), r) for r in range(1, 4)]
    again = [_prompts(AnonymousPeers("debate-1", list(reversed(MODELS))), r) for r in range(1, 4)]
    assert first == again


def test_the_listing_order_is_reshuffled_by_round():
    peers = AnonymousPeers("debate-1", MODELS)

    def listed(round_num):
        prompt = _prompts(peers, round_num)[MODELS[0]]
        return re.findall(r"\[(Participant \w+)\]:", prompt)

    orders = {tuple(listed(r)) for r in range(1, 9)}
    # Same round, same order (reproducible); across rounds the order moves.
    assert listed(3) == listed(3)
    assert len(orders) > 1


def test_mapping_depends_on_the_session():
    mappings = {
        tuple(AnonymousPeers(f"debate-{i}", MODELS).label(m) for m in MODELS) for i in range(12)
    }
    assert len(mappings) > 1


def test_anonymous_rounds_do_not_run_in_deliberation_mode():
    # The graph's deliberation mode tags every turn with its model id and
    # tells the model its own id, which would pair the label with a name.
    assert AnonymousPeers("s", MODELS).names_in_history is False
    assert NamedPeers().names_in_history is True


def test_labelled_lists_answers_in_label_order():
    peers = AnonymousPeers("debate-1", MODELS)
    pairs = labelled(peers, PREV)
    assert [label for label, _ in pairs] == ["Participant A", "Participant B", "Participant C"]
    assert dict(pairs) == {peers.label(m): PREV[m] for m in MODELS}


# ─── Named ───────────────────────────────────────────────────────


def test_named_peers_reproduce_the_original_prompt():
    prompts = _build_round_prompts(
        1, "Q?", ["m1", "m2", "m3"], {"m1": "one", "m2": "two", "m3": "three"}, NamedPeers()
    )
    assert prompts["m2"] == (
        "Original question: Q?\n\n"
        "Other models' previous responses:\n[m1]:\none\n\n[m3]:\nthree\n\n"
        "You are m2. Critically analyze the other models' arguments. "
        "Where do you agree? Where do you disagree? What are they missing? "
        "State your position now. If it changed, name the argument or evidence that "
        "changed it; agreement alone, or how many models hold a view, is not a reason."
    )


def test_round_zero_is_the_question_alone_either_way():
    for peers in (NamedPeers(), AnonymousPeers("s", MODELS)):
        assert set(_prompts(peers, round_num=0, prev={}).values()) == {"Which is better?"}


# ─── Session config ──────────────────────────────────────────────


def test_peer_labels_must_be_a_known_presentation():
    for name in PEER_PRESENTATIONS:
        check_session_config(MODELS[:2], POLICY, peer_labels=name)
    with pytest.raises(ValueError, match="peer_labels must be one of: anonymous, named"):
        check_session_config(MODELS[:2], POLICY, peer_labels="pseudonymous")


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "peers.sqlite"))
    db.init_db()


def test_new_sessions_are_anonymous_and_keep_their_choice(tmp_db):
    default = debate_svc.create_session("t", MODELS[:2], dict(POLICY))
    named = debate_svc.create_session("t", MODELS[:2], dict(POLICY), peer_labels="named")
    assert db.get_debate_session(default["session_id"])["peer_labels"] == "anonymous"
    assert db.get_debate_session(named["session_id"])["peer_labels"] == "named"
    assert isinstance(debate_svc.session_peers(db.get_debate_session(default["session_id"])), AnonymousPeers)
    assert isinstance(debate_svc.session_peers(db.get_debate_session(named["session_id"])), NamedPeers)
    assert {s["session_id"]: s["peer_labels"] for s in db.list_debate_sessions()} == {
        default["session_id"]: "anonymous",
        named["session_id"]: "named",
    }


def test_a_session_stored_before_the_choice_keeps_named_peers(tmp_db):
    """Its earlier rounds already named each other; anonymizing what follows
    would hide nothing and misdescribe how the debate ran."""
    session = debate_svc.create_session("t", MODELS[:2], dict(POLICY))
    with db.get_db_connection() as conn:
        conn.execute("UPDATE debate_sessions SET peer_labels = NULL WHERE session_id = ?", (session["session_id"],))
    stored = db.get_debate_session(session["session_id"])
    assert stored["peer_labels"] is None
    assert isinstance(debate_svc.session_peers(stored), NamedPeers)
    assert debate_svc.peer_legend(stored) == {}
    assert isinstance(peer_presentation(None, "s", MODELS), NamedPeers)


def test_peer_legend_maps_models_to_their_labels(tmp_db):
    session = debate_svc.create_session("t", MODELS, dict(POLICY))
    peers = debate_svc.session_peers(session)
    assert debate_svc.peer_legend(session) == {m: peers.label(m) for m in MODELS}
