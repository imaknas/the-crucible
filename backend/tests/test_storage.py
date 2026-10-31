"""Where the app stores things is chosen by the entry point (core/storage.py)."""

import asyncio
import contextvars

import pytest
from fastapi.testclient import TestClient

from app.core import database as db
from app.core.storage import NoStorage, Storage, current_storage, reset_storage, set_storage


def test_two_storages_in_one_process_stay_apart(tmp_path):
    a = Storage.from_env({}).under(str(tmp_path / "a"))
    b = Storage.from_env({}).under(str(tmp_path / "b"))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    async def title(storage, name):
        set_storage(storage)  # this task's own context
        await asyncio.to_thread(db.init_db)
        await asyncio.to_thread(db.rename_thread, "t", name)
        return await asyncio.to_thread(db.get_thread_title, "t")

    async def both():
        return await asyncio.gather(title(a, "in a"), title(b, "in b"))

    assert asyncio.run(both()) == ["in a", "in b"]
    token = set_storage(a)
    try:
        assert db.get_thread_title("t") == "in a"
    finally:
        reset_storage(token)


def test_a_run_given_no_storage_fails_instead_of_using_the_apps():
    def outside():
        set_storage(None)  # a context nobody chose a storage for
        with pytest.raises(NoStorage, match="No storage was set"):
            current_storage()
        with pytest.raises(NoStorage):
            db.get_db_connection()

    contextvars.copy_context().run(outside)


def test_the_server_uses_the_storage_it_was_built_with(tmp_path):
    from app.main import create_app

    storage = Storage.from_env({}).under(str(tmp_path))
    app = create_app(storage=storage)
    with TestClient(app) as client:
        assert client.get("/threads").json() == {"threads": []}
    assert (tmp_path / "checkpoints.sqlite").exists()


def test_the_model_listing_carries_dated_prices():
    from app.services.arena import list_models

    luna = next(m for m in list_models(day="2026-10-31") if m["id"] == "gpt-6-luna")
    assert luna["price_per_mtok"]["input"] > 0 and luna["price_per_mtok"]["output"] > 0
    assert luna["context_window"]
