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
