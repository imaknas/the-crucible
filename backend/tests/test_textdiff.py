"""The answer diff's text logic (services/textdiff.py), without a graph.

frontend/src/lib/diff.test.ts checks the web UI's copy of the same contract
on the same kinds of input.
"""

from app.services.textdiff import diff_texts, split_sentences, units, word_diff


def _ops(diff):
    return [r["op"] for r in diff["rows"]]


def test_prose_is_compared_sentence_by_sentence():
    a = "The sky is blue. Water is wet. Fire is hot."
    b = "The sky is green. Water is wet. Ice is cold. Fire is hot."
    d = diff_texts(a, b)
    assert _ops(d) == ["changed", "same", "only_b", "same"]
    assert d["summary"]["sentences"] == {"same": 2, "changed": 1, "only_a": 0, "only_b": 1}
    assert d["summary_text"] == "2 sentences the same, 1 changed, 1 only in B"
    assert not d["identical"]


def test_a_changed_sentence_is_diffed_word_by_word():
    segments = word_diff("The sky is blue.", "The sky is green.")
    assert segments == [
        {"op": "same", "text": "The sky is "},
        {"op": "removed", "text": "blue"},
        {"op": "added", "text": "green"},
        {"op": "same", "text": "."},
    ]


def test_unrelated_sentences_in_the_same_spot_are_not_paired():
    d = diff_texts("Cats purr loudly.", "Quantum fields fluctuate.")
    assert _ops(d) == ["only_a", "only_b"]


def test_markdown_formatting_is_not_a_difference():
    a = "## Plan\n\n- **Bold** move with a [link](https://a.example).\n- Use `x`."
    b = "## Plan\n\n- Bold move with a link.\n- Use x."
    d = diff_texts(a, b)
    assert d["identical"]
    assert d["summary_text"] == "No differences: 3 sentences the same."


def test_headings_list_items_and_paragraphs_are_their_own_units():
    assert units("# Title\nFirst line\ncontinues here.\n\n1. Item one\n2. Item two") == [
        ("sentence", "Title"),
        ("sentence", "First line continues here."),
        ("sentence", "Item one"),
        ("sentence", "Item two"),
    ]


def test_sentence_boundaries():
    assert split_sentences("It rains, e.g. in spring. Then it stops! Why? “Quoted.” Next") == [
        "It rains, e.g. in spring.",
        "Then it stops!",
        "Why?",
        "“Quoted.”",
        "Next",
    ]
    assert split_sentences("天很藍。水是濕的！") == ["天很藍。", "水是濕的！"]


def test_code_is_compared_line_by_line():
    a = "Run this:\n\n```python\nx = 1\n\ny = 2\n```"
    b = "Run this:\n\n```python\nx = 1\ny = 3\n```"
    d = diff_texts(a, b)
    assert [(r["op"], r["kind"]) for r in d["rows"]] == [("same", "sentence"), ("same", "code"), ("changed", "code")]
    assert d["summary"]["lines"] == {"same": 1, "changed": 1, "only_a": 0, "only_b": 0}
    assert d["summary_text"] == "1 sentence the same; 1 line of code the same, 1 changed"


def test_json_key_order_and_whitespace_are_not_differences():
    a = '```json\n{"b": 1, "a": {"y": [1, 2], "x": null}}\n```'
    b = '```\n{"a": {"x": null,\n   "y": [1,2]}, "b": 1}\n```'
    assert diff_texts(a, b)["identical"]
    # A whole answer that is JSON counts too.
    assert diff_texts('{"k": 1, "j": 2}', '{"j": 2, "k": 1}')["identical"]
    d = diff_texts('{"k": 1, "j": 2}', '{"j": 2, "k": 3}')
    changed = [r for r in d["rows"] if r["op"] == "changed"]
    assert [(r["a"], r["b"]) for r in changed] == [('  "k": 1', '  "k": 3')]


def test_identical_and_empty_answers():
    d = diff_texts("Same text. Twice over.", "Same text. Twice over.")
    assert d["identical"] and d["summary_text"] == "No differences: 2 sentences the same."
    empty = diff_texts("", "  ")
    assert empty["rows"] == [] and empty["identical"]
    assert empty["summary_text"] == "Both answers are empty."
    one_sided = diff_texts("", "Only here.")
    assert _ops(one_sided) == ["only_b"]
    assert one_sided["summary_text"] == "0 sentences the same, 1 only in B"
