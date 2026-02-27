"""Tests for graph.py — model selection logic.

All LLM constructors are mocked — no API keys or tokens consumed.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


def _patch_constructor(family: str):
    """Patch the constructor in _FAMILY_CONSTRUCTORS for a given family."""
    import graph

    original = graph._FAMILY_CONSTRUCTORS[family]
    mock_cls = MagicMock()

    class _Ctx:
        def __enter__(self):
            graph._FAMILY_CONSTRUCTORS[family] = (original[0], mock_cls)
            return mock_cls

        def __exit__(self, *args):
            graph._FAMILY_CONSTRUCTORS[family] = original

    return _Ctx()


# ─── get_model() ──────────────────────────────────────────────────


class TestGetModel:
    """Tests for the get_model() function that maps model IDs to LLM instances."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-123"})
    def test_exact_match_openai(self):
        from graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("gpt-5.2")
            mock_cls.assert_called_once_with(model="gpt-5.2")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-123"})
    def test_exact_match_openai_pro(self):
        from graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("gpt-5.2-pro")
            mock_cls.assert_called_once_with(model="gpt-5.2-pro")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"})
    def test_exact_match_anthropic(self):
        from graph import get_model

        with _patch_constructor("anthropic") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("claude-sonnet-4-6")
            mock_cls.assert_called_once_with(model="claude-sonnet-4-6")

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "goog-test"})
    def test_exact_match_google(self):
        from graph import get_model

        with _patch_constructor("google") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("gemini-3-flash-preview")
            mock_cls.assert_called_once_with(model="gemini-3-flash-preview")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_openai_key_raises(self):
        from graph import get_model

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            get_model("gpt-5.2")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_anthropic_key_raises(self):
        from graph import get_model

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_model("claude-sonnet-4-6")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_google_key_raises(self):
        from graph import get_model

        with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
            get_model("gemini-3-flash-preview")

    @patch.dict(os.environ, {}, clear=True)
    def test_unknown_model_not_in_whitelist(self):
        from graph import get_model

        with pytest.raises(ValueError, match="not supported in the whitelist"):
            get_model("totally-unknown-model")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_case_insensitive(self):
        from graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("GPT-5.2")
            mock_cls.assert_called_once_with(model="gpt-5.2")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
    def test_strips_whitespace(self):
        from graph import get_model

        with _patch_constructor("openai") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_model("  gpt-5.2  ")
            mock_cls.assert_called_once_with(model="gpt-5.2")
