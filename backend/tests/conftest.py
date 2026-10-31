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
    """Every test gets its own database and upload directory; tests that set
    their own still win (their monkeypatch runs after this one)."""
    from app.core import database as db
    from app.services import uploads

    root = tmp_path_factory.mktemp("storage")
    monkeypatch.setattr(db, "DB_PATH", str(root / "test.sqlite"))
    monkeypatch.setattr(uploads, "UPLOAD_DIR", str(root / "uploads"))
    db.init_db()
