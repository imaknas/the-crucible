from app.utils.helpers import extract_text, get_preview_text, clean_string


def test_clean_string():
    assert clean_string("hello\x00world") == "helloworld"
    assert clean_string(None) == ""
    assert clean_string(123) == "123"


def test_get_preview_text():
    assert get_preview_text(None) == ""
    assert get_preview_text("Short text") == "Short text"

    # Strip markdown
    assert get_preview_text("**Bold** and _italic_") == "Bold and italic"

    # Strip think tags
    assert (
        get_preview_text("<think>Thinking process</think> Final answer")
        == "Final answer"
    )
    assert get_preview_text("<think>Unclosed thinking") == ""

    # Truncation
    long_text = "This is a very long text that should be truncated because it exceeds the fifty character limit completely."
    preview = get_preview_text(long_text, max_length=50)
    assert len(preview) <= 53  # + "..."
    assert preview.endswith("...")

    # Truncation without spaces
    long_nospace = "a" * 100
    assert get_preview_text(long_nospace, max_length=10) == "aaaaaaaaaa..."


def test_extract_text_string():
    assert extract_text("hello") == "hello"


def test_extract_text_list():
    content = [
        {"type": "text", "text": "Hello "},
        {"type": "thinking", "thinking": "Let me think"},
        {"text": "World"},
        "!",
    ]
    # No wrap thinking
    assert extract_text(content) == "Hello Let me thinkWorld!"

    # Wrap thinking
    content2 = [
        {"type": "thinking", "text": "Thought"},
        {"type": "thinking", "thinking": "More Thought"},
    ]
    extracted = extract_text(content2, wrap_thinking=True)
    assert "<think>\nThought\n</think>" in extracted
    assert "<think>\nMore Thought\n</think>" in extracted


def test_extract_text_dict():
    # type text
    assert extract_text({"type": "text", "text": "Hello"}) == "Hello"
    # type thinking
    assert (
        extract_text({"type": "thinking", "thinking": "Hmm"}, wrap_thinking=True)
        == "<think>\nHmm\n</think>"
    )
    assert (
        extract_text({"type": "thinking", "thinking": "Hmm"}, wrap_thinking=False)
        == "Hmm"
    )
    # base text
    assert extract_text({"text": "fallback"}) == "fallback"
    # empty fallback
    assert extract_text({"other": "value"}) == ""


def test_extract_text_fallback():
    assert extract_text(None) == ""
    assert extract_text(123) == "123"
