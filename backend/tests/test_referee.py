"""Who combines answers when no one is named (services/referee.py).

The same cases are in frontend/src/lib/referee.test.ts, which mirrors the rule
for the web UI's "Synthesize answers"."""

from app.services.referee import default_synthesizer

GPT, CLAUDE, GEMINI, GROK = "gpt-6.2-sol", "claude-sonnet-5-5", "gemini-4-neon", "grok-4.7"
KEYS = {"OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "k", "GOOGLE_API_KEY": "k", "XAI_API_KEY": "k"}


def _without(key):
    return {k: v for k, v in KEYS.items() if k != key}


def test_it_comes_from_a_provider_that_wrote_none_of_the_answers():
    assert default_synthesizer([GPT, CLAUDE], env=KEYS) == GEMINI
    assert default_synthesizer([GPT, CLAUDE, GEMINI], env=KEYS) == GROK


def test_it_needs_that_providers_key():
    assert default_synthesizer([GPT, CLAUDE], env=_without("GOOGLE_API_KEY")) == GROK


def test_it_is_the_first_answering_model_when_there_is_no_outsider():
    assert default_synthesizer([GPT, CLAUDE, GEMINI], env=_without("XAI_API_KEY")) == GPT
