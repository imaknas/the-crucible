"""Shared fixtures for backend tests."""

import sys
import os

# Add backend root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.registry import provider_env_keys


@pytest.fixture(autouse=True)
def no_provider_keys(monkeypatch):
    """No test sees a real API key: a test that forgets to inject a fake model
    fails for want of a key instead of making a paid call. Tests that need
    keys set placeholders themselves."""
    for name in provider_env_keys():
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path_factory, monkeypatch):
    """Every test gets its own database, upload, Chroma and .env locations,
    set for the test and on the app (core/storage.py); storage_helpers.point
    moves one of them."""
    from app.core import database as db
    from app.core.storage import Storage, reset_storage, set_storage
    from app.main import server

    storage = Storage.from_env({}).under(str(tmp_path_factory.mktemp("storage")))
    token = set_storage(storage)
    monkeypatch.setattr(server.state, "storage", storage)
    db.init_db()
    yield storage
    reset_storage(token)
