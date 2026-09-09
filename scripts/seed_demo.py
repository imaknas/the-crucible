"""
Seed a presentable demo database for the README screenshots.

Unlike e2e/seed_db.py this makes **real** model calls, so the screenshots show
genuine output rather than invented text attributed to named models. Prompts ask
for two or three sentences: that keeps the cost to a few cents and, more
usefully, keeps replies short enough to read inside a tree node.

Writes to scripts/.demo/demo.sqlite. Never point this at backend/checkpoints.sqlite.

Usage:  uv run --project backend python scripts/seed_demo.py
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "scripts" / ".demo" / "demo.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_PATH"] = str(DB_PATH)
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402

import app.services.graph as graph_mod  # noqa: E402
from app.core import database as db  # noqa: E402
from app.services import debate as debate_svc  # noqa: E402

# Appended to every prompt: short answers cost less and, more importantly,
# stay readable inside a tree node. Phrased as something a user would type,
# since the prompt itself appears in the screenshots.
BREVITY = " Answer in three sentences."

# ─── Thread 1: a branching comparison ────────────────────────────────────────
TREE_THREAD = "thread_demo_arch"
TREE_TITLE = "Monolith or microservices?"

# ─── Thread 2: a three-way debate ────────────────────────────────────────────
DEBATE_THREAD = "thread_demo_rag"
DEBATE_TITLE = "Is RAG a bridge or an architecture?"
DEBATE_QUESTION = (
    "Is retrieval-augmented generation a bridge technology that longer context "
    "windows will make obsolete, or a permanent part of serious LLM systems?"
)
DEBATE_MODELS = ["gpt-5.4", "claude-sonnet-5", "gemini-3.1-pro-preview"]


async def turn(app, thread_id, model, text, parent=None):
    cfg = {"configurable": {"thread_id": thread_id}}
    if parent:
        cfg["configurable"]["checkpoint_id"] = parent
    await app.ainvoke(
        {
            "active_peer": model,
            "messages": [("user", text)],
            "toggles": {"use_rag": False, "use_web_search": False},
            "is_deliberation": False,
            "current_thesis": "",
            "documents": {},
        },
        cfg,
    )
    snapshot = await app.aget_state({"configurable": {"thread_id": thread_id}})
    return snapshot.config["configurable"]["checkpoint_id"]


async def main():
    db.init_db()

    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as saver:
        app = graph_mod.workflow.compile(checkpointer=saver)

        # ── A thread that forks, so the tree shows a real branch point ──
        db.rename_thread(TREE_THREAD, TREE_TITLE)
        root = await turn(
            app,
            TREE_THREAD,
            "gpt-5.4",
            "A four-person team is starting a new B2B product. Monolith or "
            "microservices?" + BREVITY,
        )
        await turn(
            app,
            TREE_THREAD,
            "gpt-5.4",
            "What is the first signal that we have outgrown that choice?" + BREVITY,
        )
        # Same question, different model, branched from the same checkpoint.
        await turn(
            app,
            TREE_THREAD,
            "claude-sonnet-5",
            "Argue the opposite case as strongly as you can." + BREVITY,
            parent=root,
        )
        print("  tree thread done")

        # ── A real debate: 3 models, 2 rounds, convergence scored, synthesised ──
        db.rename_thread(DEBATE_THREAD, DEBATE_TITLE)
        session = debate_svc.create_session(
            parent_thread_id=DEBATE_THREAD,
            participants=DEBATE_MODELS,
            termination_policy={
                "max_rounds": 2,
                "convergence_threshold": 0.9,
                "llm_judge": None,
                "mode": "any",
            },
            auto_synthesize=True,
            synthesizer_model="claude-sonnet-5",
        )
        async for event in debate_svc.run_debate(
            graph_app=app,
            session_id=session["session_id"],
            prompt=DEBATE_QUESTION + BREVITY,
            toggles={"use_rag": False, "use_web_search": False},
            documents={},
        ):
            kind = event.get("type")
            if kind in {"debate_round_start", "debate_converged", "debate_session_status"}:
                print(f"  {kind}: {event.get('round', event.get('status', ''))}")
            elif kind == "debate_round_end" and "convergence_score" in event:
                print(f"  round {event['round']} convergence {event['convergence_score']:.3f}")
            elif kind == "error":
                print(f"  ERROR {event.get('model')}: {event.get('message')}")

    print(f"\nseeded {DB_PATH}")
    print(f"  threads={len(db.list_threads())} debates={len(db.list_debate_sessions())}")


if __name__ == "__main__":
    asyncio.run(main())
