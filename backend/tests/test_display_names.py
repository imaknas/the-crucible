"""Names a person reads: a provider's dated snapshot name gets the model's name.

Older replies record the model that answered as the provider reported it
("gpt-5.2-2025-12-11"), which format_messages prefers over the run's model,
so the transcript showed the raw id.
"""

from langchain_core.messages import AIMessage, HumanMessage

from app.registry import MODEL_REGISTRY, display_name
from app.catalog.names import is_dated_snapshot, listed_id
from app.catalog.prices import PriceBook, load_prices


def test_a_dated_snapshot_is_shown_by_its_models_name():
    assert display_name("gpt-5.2-2025-12-11") == MODEL_REGISTRY["gpt-5.2"]["name"]
    assert display_name("gpt-5.4-nano-2026-03-17") == MODEL_REGISTRY["gpt-5.4-nano"]["name"]


def test_another_model_that_shares_a_prefix_is_not_renamed():
    # "-turbo" is not a date: this is not GPT-5.4.
    assert display_name("gpt-5.4-turbo") == "gpt-5.4-turbo"
    assert display_name("totally-unknown") == "totally-unknown"
    assert display_name(None) == ""


def test_snapshot_helpers():
    known = ["gpt-5.4", "gpt-5.4-nano"]
    assert listed_id("gpt-5.4-nano-2026-03-17", known) == "gpt-5.4-nano"
    assert listed_id("models/GPT-5.4", known) == "gpt-5.4"
    assert listed_id("claude-x", known) is None
    assert is_dated_snapshot("claude-haiku-4-5-20251001", "claude-haiku-4-5")
    assert not is_dated_snapshot("gpt-5.4-pro", "gpt-5.4")


def test_price_book_still_resolves_snapshots():
    book = PriceBook(load_prices(), "2026-10-30")
    assert book.resolve("gpt-5.4-nano-2026-03-17") == "gpt-5.4-nano"


def test_a_transcript_reply_recorded_under_a_snapshot_name_shows_the_models_name():
    from types import SimpleNamespace

    from app.services.tree import format_messages

    def state(cid, parent, messages):
        return SimpleNamespace(
            values={"messages": messages, "active_peer": "gpt-5.2"},
            metadata={},
            config={"configurable": {"checkpoint_id": cid}},
            parent_config={"configurable": {"checkpoint_id": parent}} if parent else None,
        )

    reply = AIMessage(content="Answer", response_metadata={"model_name": "gpt-5.2-2025-12-11"})
    states = {
        "c1": state("c1", None, [HumanMessage(content="Q")]),
        "c2": state("c2", "c1", [HumanMessage(content="Q"), reply]),
    }
    shown = format_messages("c2", states)
    assert shown[1]["model_name"] == MODEL_REGISTRY["gpt-5.2"]["name"]
