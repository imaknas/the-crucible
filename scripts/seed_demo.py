"""
Seed a presentable demo database for the README demo recording.

Unlike e2e/seed_db.py this makes **real** model calls, so the demo shows
genuine output rather than invented text attributed to named models. It runs
the app's own services (arena turns, synthesis, debate), so the database is
exactly what the web UI writes: turns carry their turn ids and show as
compare cards, replies continue their own conversations, the debate is
anonymous and ends in an argument map.

Prompts ask for three sentences: that keeps the cost down and, more usefully,
keeps replies short enough to read inside a tree node. Every call is metered
against the providers' prices (catalog/data/prices.json); the run stops
starting steps once --budget is spent, and any failed call stops it.

Writes to scripts/.demo/ (database and vector store). Never point this at
backend/checkpoints.sqlite.

Usage:
  uv run --project backend python scripts/seed_demo.py --estimate   # upper bound, no calls
  uv run --project backend python scripts/seed_demo.py --budget 3   # real calls
"""

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "scripts" / ".demo"
DB_PATH = DEMO_DIR / "demo.sqlite"

# Shown as the models' answers in the README, so they are the app's defaults.
MODELS = ["gpt-6.1-sol", "claude-sonnet-5-5", "gemini-3.1-pro-preview"]
SYNTHESIZER = "claude-sonnet-5-5"

# Appended to every prompt. Phrased as something a person would type, since
# the prompt itself appears in the demo.
BREVITY = " Answer in three sentences."

# ─── Thread 1: an arena turn, each model continuing, a branch, a synthesis ───
ARENA_THREAD = "thread_demo_arch"
ARENA_TITLE = "Monolith or microservices?"
ARENA_QUESTION = "A four-person team is starting a new B2B product. Monolith or microservices?"
FOLLOW_UP = "What is the first signal that we have outgrown that choice?"
BRANCH = "Argue the opposite case as strongly as you can."

# ─── Thread 2: an anonymous three-way debate ─────────────────────────────────
DEBATE_THREAD = "thread_demo_rag"
DEBATE_TITLE = "Is RAG a bridge or an architecture?"
DEBATE_QUESTION = (
    "Is retrieval-augmented generation a bridge technology that longer context "
    "windows will make obsolete, or a permanent part of serious LLM systems?"
)
DEBATE_ROUNDS = 2

# The calls the run makes, for --estimate: (model, input tokens at most).
# Output is bounded at OUTPUT_BOUND tokens a call: three sentences plus
# whatever reasoning a thinking model spends, which bills as output.
OUTPUT_BOUND = 4000
PLANNED_CALLS = (
    [(m, 500) for m in MODELS]  # the arena turn
    + [(m, 1000) for m in MODELS]  # each continues its own reply
    + [("claude-sonnet-5-5", 1000)]  # the branch
    + [(SYNTHESIZER, 2000)]  # synthesis of the first turn
    + [(m, 500) for m in MODELS]  # debate round 1, independent answers
    + [(m, 3000) for m in MODELS] * (DEBATE_ROUNDS - 1)  # cross-examination
    + [(SYNTHESIZER, 6000)]  # the argument map
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--estimate", action="store_true", help="print an upper bound on the cost and exit")
    parser.add_argument("--budget", type=float, help="USD; required for a real run")
    parser.add_argument("--env-file", type=Path, default=ROOT / "backend" / ".env", help="provider keys")
    args = parser.parse_args()
    if not args.estimate and args.budget is None:
        parser.error("a real run needs --budget (USD); --estimate shows what it may cost")
    return args


def upper_bound(prices) -> float:
    total = 0.0
    for model, input_tokens in PLANNED_CALLS:
        price = prices.price(model)
        if price is None:
            raise SystemExit(f"{model} has no price in catalog/data/prices.json")
        total += price.cost(input_tokens, OUTPUT_BOUND)
    return total


async def drain(run, label: str, spend) -> list[dict]:
    """Every event of one service run; stops the seed on a failed call."""
    events = [e async for e in run]
    failed = [e for e in events if e.get("error") or e.get("type") == "error"]
    if failed or spend.errors:
        raise SystemExit(f"{label} failed: {failed or spend.errors}")
    print(f"  {label}: ${spend.total:.3f} so far")
    return events


async def seed(spend, factory):
    from app.core import database as db
    from app.llm import use_model_factory
    from app.services import debate as debate_svc
    from app.services.arena import open_graph, run_arena, synthesize_thread

    toggles = {"use_rag": False, "use_web_search": False}
    async with open_graph() as app:
        with use_model_factory(factory):
            db.rename_thread(ARENA_THREAD, ARENA_TITLE)
            first = await drain(
                run_arena(app, ARENA_QUESTION + BREVITY, ARENA_THREAD, models=MODELS, toggles=toggles),
                "arena turn",
                spend,
            )
            answers = {e["model"]: e["checkpoint_id"] for e in first if e.get("type") == "end"}
            spend.check()
            # No parent: each model continues its own reply, as Send does.
            await drain(
                run_arena(app, FOLLOW_UP + BREVITY, ARENA_THREAD, models=MODELS, toggles=toggles),
                "each continues its own",
                spend,
            )
            spend.check()
            await drain(
                run_arena(
                    app,
                    BRANCH + BREVITY,
                    ARENA_THREAD,
                    models=["claude-sonnet-5-5"],
                    toggles=toggles,
                    parent_checkpoint_id=answers["claude-sonnet-5-5"],
                ),
                "branch",
                spend,
            )
            spend.check()
            # Last, so the next Send in the demo still continues each model's
            # own reply rather than the synthesis.
            await drain(
                synthesize_thread(
                    app, ARENA_THREAD, SYNTHESIZER, toggles, checkpoint_ids=[answers[m] for m in MODELS]
                ),
                "synthesis",
                spend,
            )
            spend.check()

            db.rename_thread(DEBATE_THREAD, DEBATE_TITLE)
            session = debate_svc.create_session(
                parent_thread_id=DEBATE_THREAD,
                participants=MODELS,
                termination_policy={
                    "max_rounds": DEBATE_ROUNDS,
                    "convergence_threshold": 0.9,
                    "llm_judge": None,
                    "mode": "all",
                },
                auto_synthesize=True,
                synthesizer_model=SYNTHESIZER,
            )
            events = await drain(
                debate_svc.run_debate(app, session["session_id"], DEBATE_QUESTION + BREVITY, toggles),
                "debate",
                spend,
            )
            status = [e["status"] for e in events if e.get("type") == "debate_session_status"]
            print(f"  debate {session['session_id']}: {status[-1] if status else 'no status'}")


def main():
    args = parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app.catalog.prices import PriceBook, load_prices

    prices = PriceBook(load_prices(), date.today().isoformat())
    bound = upper_bound(prices)
    print(f"{len(PLANNED_CALLS)} model calls, at most ${bound:.2f} (≤{OUTPUT_BOUND} output tokens a call)")
    if args.estimate:
        return

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    os.environ["DATABASE_PATH"] = str(DB_PATH)
    os.environ["CHROMA_DIR"] = str(DEMO_DIR / "chroma")

    from dotenv import load_dotenv

    load_dotenv(args.env_file)

    from app.core.storage import Storage, set_storage
    from app.llm import CallableModelFactory
    from app.llm.factory import ProviderModelFactory
    from app.services.compaction_eval import Spend

    set_storage(Storage.from_env())
    spend = Spend(prices, limit=args.budget)
    real = ProviderModelFactory()
    factory = CallableModelFactory(lambda model, toggles: real.chat(model, toggles).with_config(callbacks=[spend]))
    try:
        asyncio.run(seed(spend, factory))
    finally:
        print(f"\nspent ${spend.total:.3f}" + (f" (unpriced calls: {spend.unpriced})" if spend.unpriced else ""))
        for model, cost in sorted(spend.by_model.items()):
            print(f"  {model}: ${cost:.3f}")
    print(f"seeded {DB_PATH}")


if __name__ == "__main__":
    main()
