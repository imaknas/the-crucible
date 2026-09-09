"""
Build a deterministic SQLite fixture for the Playwright suite.

Runs the real LangGraph workflow so the checkpoints are genuine — the tree
endpoints walk LangGraph's own parent/child links, and hand-written rows would
not exercise that. The only thing stubbed is the LLM: every model resolves to a
canned-response fake, so seeding makes no network calls and costs nothing.

Writes to the path given as argv[1] (default: e2e/.fixtures/e2e.sqlite),
replacing whatever was there. Never point this at backend/checkpoints.sqlite.

Usage:  uv run --project backend python e2e/seed_db.py [path]
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "e2e" / ".fixtures" / "e2e.sqlite"

DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()

# Must be set before app modules import, so database.DB_PATH picks it up.
os.environ["DATABASE_PATH"] = str(DB_PATH)
# get_model() refuses to build a model when the family key is missing; the
# fake never reads them, but the guard runs before the patch takes effect.
for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
    os.environ.setdefault(key, "e2e-fixture-not-a-real-key")

sys.path.insert(0, str(ROOT / "backend"))

from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    FakeListChatModel,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402

import app.services.graph as graph_mod  # noqa: E402
from app.core import database as db  # noqa: E402
from app.services import debate as debate_svc  # noqa: E402

# ─── Fixture content ─────────────────────────────────────────────────────────

THREAD_ID = "thread_e2e_main"
THREAD_TITLE = "E2E Reference Thread"

DEBATE_THREAD_ID = "thread_e2e_debate"
DEBATE_TITLE = "E2E Debate Thread"
DEBATE_MODELS = ["gpt-5.4", "claude-sonnet-5"]

# Long enough that the 40-char node preview truncates, which is what the
# level-of-detail assertions care about.
REPLIES = [
    "Branching a conversation tree lets you compare model answers from the same "
    "checkpoint without losing either path, which is the whole point of the arena.",
    "Deliberation re-reads the thread with attribution so each model can see who "
    "said what before it commits to a position of its own.",
    "Convergence is measured as cosine similarity between consecutive rounds, so "
    "a high score means the models stopped moving rather than that they are right.",
    "Synthesis runs last and treats every lane as evidence rather than as a vote, "
    "which keeps a single confident model from dominating the result.",
]


def _fake_model(*_args, **_kwargs):
    """Stand-in for get_model(); cycles through the canned replies."""
    return FakeListChatModel(responses=REPLIES)


async def _invoke(app, thread_id, model, text, parent_checkpoint_id=None):
    """Run one turn and return the resulting checkpoint id."""
    cfg = {"configurable": {"thread_id": thread_id}}
    if parent_checkpoint_id:
        cfg["configurable"]["checkpoint_id"] = parent_checkpoint_id
    state = {
        "active_peer": model,
        "messages": [("user", text)],
        "toggles": {"use_rag": False, "use_web_search": False},
        "is_deliberation": False,
        "current_thesis": "",
        "documents": {},
    }
    await app.ainvoke(state, cfg)
    snapshot = await app.aget_state({"configurable": {"thread_id": thread_id}})
    return snapshot.config["configurable"]["checkpoint_id"]


async def main():
    # Stub the LLM everywhere the graph reaches for one.
    graph_mod.get_model = _fake_model

    db.init_db()

    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as saver:
        app = graph_mod.workflow.compile(checkpointer=saver)

        # ── A linear thread that then forks, so the layout has a real branch ──
        db.rename_thread(THREAD_ID, THREAD_TITLE)
        cp1 = await _invoke(app, THREAD_ID, "gpt-5.4", "What does branching buy me?")
        cp2 = await _invoke(app, THREAD_ID, "gpt-5.4", "And what is deliberation for?")
        # Fork from the FIRST checkpoint — two children, one parent.
        await _invoke(
            app,
            THREAD_ID,
            "claude-sonnet-5",
            "Answer the same question differently.",
            parent_checkpoint_id=cp1,
        )
        assert cp2

        # ── A debate: 2 models x 2 rounds, then synthesis ──
        db.rename_thread(DEBATE_THREAD_ID, DEBATE_TITLE)
        session = debate_svc.create_session(
            parent_thread_id=DEBATE_THREAD_ID,
            participants=DEBATE_MODELS,
            termination_policy={
                "max_rounds": 2,
                "convergence_threshold": None,
                "llm_judge": None,
                "mode": "all",
            },
            auto_synthesize=False,
            synthesizer_model=None,
        )

        for round_num in range(2):
            for model in DEBATE_MODELS:
                await _invoke(
                    app,
                    session["thread_ids"][model],
                    model,
                    f"Round {round_num}: state your position.",
                )
        db.update_debate_session(
            session["session_id"], current_round=1, status="completed"
        )
        # Recorded scores drive the round-band badges in the tree view.
        db.record_round_score(session["session_id"], 1, 0.91)

        # Synthesis lane
        await _invoke(
            app,
            debate_svc.make_synthesis_thread_id(DEBATE_THREAD_ID),
            "gpt-5.4",
            "Synthesize the debate.",
        )

    counts = {
        "threads": len(db.list_threads()),
        "debate_sessions": len(db.list_debate_sessions()),
        "main_checkpoints": len(db.get_thread_checkpoint_graph(THREAD_ID)),
    }
    print(f"seeded {DB_PATH}")
    print(f"  {counts}")


if __name__ == "__main__":
    asyncio.run(main())
