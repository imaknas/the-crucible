import {
  align,
  diffAnswers,
  diffSummaryText,
  splitSentences,
  units,
  wordDiff,
} from "./diff";

const ops = (a: string, b: string) => diffAnswers(a, b).rows.map((r) => r.op);

describe("diffAnswers: prose", () => {
  it("compares sentence by sentence", () => {
    const d = diffAnswers(
      "The sky is blue. Water is wet. Fire is hot.",
      "The sky is green. Water is wet. Ice is cold. Fire is hot.",
    );
    expect(d.rows.map((r) => r.op)).toEqual([
      "changed",
      "same",
      "only_b",
      "same",
    ]);
    expect(d.summary.sentences).toEqual({
      same: 2,
      changed: 1,
      only_a: 0,
      only_b: 1,
    });
    expect(diffSummaryText(d.summary)).toBe(
      "2 sentences the same, 1 changed, 1 only in B",
    );
    expect(d.identical).toBe(false);
  });

  it("diffs a changed sentence word by word", () => {
    expect(wordDiff("The sky is blue.", "The sky is green.")).toEqual([
      { op: "same", text: "The sky is " },
      { op: "removed", text: "blue" },
      { op: "added", text: "green" },
      { op: "same", text: "." },
    ]);
    const row = diffAnswers(
      "It sits on the Seine.",
      "It sits on the river Seine.",
    ).rows[0];
    expect(row).toMatchObject({
      op: "changed",
      a: "It sits on the Seine.",
      b: "It sits on the river Seine.",
    });
    expect(row.op === "changed" && row.segments).toContainEqual({
      op: "added",
      text: "river ",
    });
  });

  it("does not pair unrelated sentences that happen to sit in the same spot", () => {
    expect(ops("Cats purr loudly.", "Quantum fields fluctuate.")).toEqual([
      "only_a",
      "only_b",
    ]);
    // Shared punctuation is not likeness.
    expect(ops("Yes, at first.", "No, after all.")).toEqual([
      "only_a",
      "only_b",
    ]);
  });

  it("counts every kind of difference in the summary", () => {
    const d = diffAnswers(
      "Paris is the capital of France. It sits on the Seine. Its museums are famous.",
      "Paris is the capital of France. It sits on the river Seine. Lyon is the second city.",
    );
    expect(diffSummaryText(d.summary)).toBe(
      "1 sentence the same, 1 changed, 1 only in A, 1 only in B",
    );
  });

  it("ignores markdown formatting", () => {
    const d = diffAnswers(
      "## Plan\n\n- **Bold** move with a [link](https://a.example).\n- Use `x`.",
      "## Plan\n\n- Bold move with a link.\n- Use x.",
    );
    expect(d.identical).toBe(true);
    expect(diffSummaryText(d.summary)).toBe(
      "No differences: 3 sentences the same.",
    );
  });

  it("keeps headings, list items and paragraphs apart", () => {
    expect(
      units("# Title\nFirst line\ncontinues here.\n\n1. Item one\n2. Item two"),
    ).toEqual([
      { kind: "sentence", text: "Title" },
      { kind: "sentence", text: "First line continues here." },
      { kind: "sentence", text: "Item one" },
      { kind: "sentence", text: "Item two" },
    ]);
  });

  it("reads table rows as units and drops the separator row", () => {
    expect(units("| Name | Age |\n|---|:--:|\n| Ann | 3 |")).toEqual([
      { kind: "sentence", text: "Name | Age" },
      { kind: "sentence", text: "Ann | 3" },
    ]);
  });

  it("ends sentences where a reader would", () => {
    expect(
      splitSentences(
        "It rains, e.g. in spring. Then it stops! Why? “Quoted.” Next",
      ),
    ).toEqual([
      "It rains, e.g. in spring.",
      "Then it stops!",
      "Why?",
      "“Quoted.”",
      "Next",
    ]);
    expect(splitSentences("天很藍。水是濕的！")).toEqual([
      "天很藍。",
      "水是濕的！",
    ]);
  });
});

describe("diffAnswers: code and JSON", () => {
  it("compares code line by line", () => {
    const d = diffAnswers(
      "Run this:\n\n```python\nx = 1\n\ny = 2\n```",
      "Run this:\n\n```python\nx = 1\ny = 3\n```",
    );
    expect(d.rows.map((r) => [r.op, r.kind])).toEqual([
      ["same", "sentence"],
      ["same", "code"],
      ["changed", "code"],
    ]);
    expect(d.summary.lines).toEqual({
      same: 1,
      changed: 1,
      only_a: 0,
      only_b: 0,
    });
    expect(diffSummaryText(d.summary)).toBe(
      "1 sentence the same; 1 line of code the same, 1 changed",
    );
  });

  it("ignores JSON key order and whitespace", () => {
    expect(
      diffAnswers(
        '```json\n{"b": 1, "a": {"y": [1, 2], "x": null}}\n```',
        '```\n{"a": {"x": null,\n   "y": [1,2]}, "b": 1}\n```',
      ).identical,
    ).toBe(true);
    // A whole answer that is JSON counts too.
    expect(diffAnswers('{"k": 1, "j": 2}', '{"j": 2, "k": 1}').identical).toBe(
      true,
    );
    const changed = diffAnswers(
      '{"k": 1, "j": 2}',
      '{"j": 2, "k": 3}',
    ).rows.filter((r) => r.op === "changed");
    expect(changed).toMatchObject([
      { kind: "json", a: '  "k": 1', b: '  "k": 3' },
    ]);
  });

  it("keeps a code block that isn't JSON as code, even after a json fence", () => {
    expect(units("```json\n{ not json }\n```")).toEqual([
      { kind: "code", text: "{ not json }" },
    ]);
  });
});

describe("diffAnswers: edges", () => {
  it("says when two answers are the same", () => {
    const d = diffAnswers("Same text. Twice over.", "Same text. Twice over.");
    expect(d.identical).toBe(true);
    expect(diffSummaryText(d.summary)).toBe(
      "No differences: 2 sentences the same.",
    );
  });

  it("handles empty answers", () => {
    const empty = diffAnswers("", "  ");
    expect(empty.rows).toEqual([]);
    expect(empty.identical).toBe(true);
    expect(diffSummaryText(empty.summary)).toBe("Both answers are empty.");
    const oneSided = diffAnswers("", "Only here.");
    expect(oneSided.rows.map((r) => r.op)).toEqual(["only_b"]);
    expect(diffSummaryText(oneSided.summary)).toBe(
      "0 sentences the same, 1 only in B",
    );
  });

  it("gives up on an alignment too large to compute and calls the middle one change", () => {
    const blocks = align(
      ["s", "x", "y", "e"],
      ["s", "y", "x", "e"],
      (t) => t,
      1,
    );
    expect(blocks).toEqual([
      { equal: true, a: ["s"], b: ["s"] },
      { equal: false, a: ["x", "y"], b: ["y", "x"] },
      { equal: true, a: ["e"], b: ["e"] },
    ]);
    // With room to compute, the common element is found.
    expect(
      align(["x", "y"], ["y", "x"], (t) => t).filter((b) => b.equal),
    ).toHaveLength(1);
  });
});
