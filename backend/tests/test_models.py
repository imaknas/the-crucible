"""Tests for routers/models.py — static catalog structure and availability."""

import os
from unittest.mock import patch
from app.api.models import _build_families


class TestEndpointStructure:
    """Tests for the /models endpoint response structure."""

    @patch.dict(os.environ, {}, clear=True)
    def test_response_has_families(self):
        families = _build_families()
        assert len(families) == 4

    @patch.dict(os.environ, {}, clear=True)
    def test_family_keys(self):
        families = _build_families()
        keys = [f["key"] for f in families]
        assert keys == ["openai", "anthropic", "google", "xai"]

    @patch.dict(os.environ, {}, clear=True)
    def test_family_structure(self):
        families = _build_families()
        for fam in families:
            assert "key" in fam
            assert "label" in fam
            assert "color" in fam
            assert "available" in fam
            assert "models" in fam
            assert isinstance(fam["models"], list)
            for m in fam["models"]:
                assert "id" in m
                assert "name" in m
                assert "desc" in m

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True)
    def test_availability_flag(self):
        families = _build_families()
        fam_map = {str(f["key"]): f for f in families}
        assert fam_map["openai"]["available"] is True
        assert fam_map["anthropic"]["available"] is False
        assert fam_map["google"]["available"] is False
        assert fam_map["xai"]["available"] is False


def test_each_family_has_its_own_colour_apart_from_synthesis():
    # Google shared the synthesis violet, so a violet card or node could be
    # Gemini, a synthesis or a debate's map.
    from app.registry import FAMILY_META, SYNTHESIS_COLOR

    colours = [meta["color"] for meta in FAMILY_META.values()]
    assert len(set(colours)) == len(colours)
    assert SYNTHESIS_COLOR not in colours
