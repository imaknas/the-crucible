"""What a debate cost: every reply, the agreement judge and the synthesis,
live on the socket and again from the stored transcript.

The app's lifespan graph and the debate socket, with the scripted LLM the
e2e suite uses (it reports usage and its model, so registry models get a
cost).
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.llm import use_model_factory
from app.llm.fake import ScriptedModelFactory
from app.main import server
from tests.storage_helpers import point
from tests.test_debate_continuation import _until

KEYS = {k: "test-key" for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")}
A, B = "gpt-5.4", "claude-sonnet-5"


@pytest.fixture
def client(tmp_path, monkeypatch):
    point(monkeypatch, db_path=str(tmp_path / "costs.sqlite"))
    with use_model_factory(ScriptedModelFactory(delay=0)), patch.dict(os.environ, KEYS), TestClient(server) as c:
        yield c


def test_a_debate_reports_what_each_call_cost(client):
    policy = {"max_rounds": 2, "convergence_threshold": None, "llm_judge": A, "mode": "all"}
    res = client.post("/debate/sessions", json={"parent_thread_id": "t", "participants": [A, B],
                                                 "termination_policy": policy, "auto_synthesize": True,
                                                 "synthesizer_model": A})
    sid = res.json()["session_id"]
    with client.websocket_connect(f"/debate/ws/{sid}") as ws:
        ws.send_json({"type": "debate_start", "prompt": "Is it?", "toggles": {}})
        frames = _until(ws, lambda f: f["type"] == "debate_session_status" and f["status"] == "completed")

    ends = [f for f in frames if f["type"] == "stream_end"]
    assert len(ends) == 4 and all(f["metrics"]["cost_usd"] > 0 for f in ends)
    # The judge reads the second round once per participant (each order).
    judged = [f for f in frames if f["type"] == "debate_round_end" and f.get("judge_usage")]
    assert [f["round"] for f in judged] == [1] and judged[0]["judge_usage"]["calls"] == 2
    synthesis = next(f for f in frames if f["type"] == "debate_synthesis_end")
    assert synthesis["metrics"]["cost_usd"] > 0

    # The stored transcript says the same after a reload.
    t = client.get(f"/debate/sessions/{sid}/transcript").json()
    by_round = {(r["round"], m): metrics for r in t["rounds"] for m, metrics in r["metrics"].items()}
    assert by_round == {(f["round"], f["model"]): f["metrics"] for f in ends}
    assert [r["judge_usage"] for r in t["rounds"]] == [None, judged[0]["judge_usage"]]
    assert t["synthesis"]["metrics"] == synthesis["metrics"]
    expected = sum(f["metrics"]["cost_usd"] for f in ends) + synthesis["metrics"]["cost_usd"] \
        + judged[0]["judge_usage"]["cost_usd"]
    assert t["total"]["cost_usd"] == pytest.approx(expected)
    assert t["total"]["answers"] == 5 and t["total"]["helpers"]["calls"] == 2
