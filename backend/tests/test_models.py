"""Tests for routers/models.py — static catalog structure and availability."""

import os
from unittest.mock import patch
from routers.models import _build_families


class TestEndpointStructure:
    """Tests for the /models endpoint response structure."""

    @patch.dict(os.environ, {}, clear=True)
    def test_response_has_families(self):
        families = _build_families()
        assert len(families) == 3

    @patch.dict(os.environ, {}, clear=True)
    def test_family_keys(self):
        families = _build_families()
        keys = [f["key"] for f in families]
        assert keys == ["openai", "anthropic", "google"]

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
