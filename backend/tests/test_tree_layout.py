"""Layout invariants for the tidy-tree and debate-lane layouts.

These replaced a per-level grid that packed each depth independently, which
interleaved siblings from different parents and made edges cross.
"""

from unittest.mock import MagicMock, patch

from app.services.tree import (
    LANE_WIDTH,
    NODE_SPACING_X,
    ROUND_HEIGHT,
    build_debate_tree,
    build_history_tree,
    build_significant_forest,
    tidy_tree_layout,
)


def _msg(content, msg_type="human"):
    m = MagicMock()
    m.content = content
    m.type = msg_type
    m.name = None
    m.additional_kwargs = {}
    m.response_metadata = {}
    return m


class _Chain:
    """Builds mock LangGraph states where each child inherits its parent's messages."""

    def __init__(self):
        self.states = []
        self._by_id = {}

    def add(self, cp_id, parent_id, text, msg_type):
        base = list(self._by_id[parent_id].values["messages"]) if parent_id else []
        s = MagicMock()
        s.config = {"configurable": {"checkpoint_id": cp_id}}
        s.parent_config = (
            {"configurable": {"checkpoint_id": parent_id}} if parent_id else None
        )
        s.values = {
            "messages": base + [_msg(text, msg_type)],
            "active_peer": "gpt-5.4",
            "current_thesis": "",
        }
        self._by_id[cp_id] = s
        self.states.append(s)
        return self


def _branching_thread():
    """root → a1 → three branches, one of which goes two levels deeper."""
    c = _Chain()
    c.add("root", None, "Q0", "human").add("a1", "root", "A0", "ai")
    c.add("b1", "a1", "Q1", "human").add("c1", "b1", "A1", "ai")
    c.add("b2", "a1", "Q2", "human").add("c2", "b2", "A2", "ai")
    c.add("b3", "a1", "Q3", "human").add("c3", "b3", "A3", "ai")
    c.add("d1", "c1", "Q4", "human").add("e1", "d1", "A4", "ai")
    return c.states


def _tree(states, saved_positions=None):
    with patch(
        "app.services.tree.load_node_positions", return_value=saved_positions or {}
    ):
        return build_history_tree("t", states, states[-1])


def _children_map(edges):
    kids = {}
    for e in edges:
        kids.setdefault(e["source"], []).append(e["target"])
    return kids


def _subtree_xs(node_id, kids, pos):
    xs = [pos[node_id][0]]
    for k in kids.get(node_id, []):
        xs += _subtree_xs(k, kids, pos)
    return xs


class TestTidyTreeLayout:
    def test_single_chain_is_a_straight_line(self):
        cols = tidy_tree_layout(["a"], {"a": ["b"], "b": ["c"]})
        assert cols["a"]["x"] == cols["b"]["x"] == cols["c"]["x"]
        assert cols["a"]["y"] < cols["b"]["y"] < cols["c"]["y"]

    def test_parent_is_centred_over_its_children(self):
        cols = tidy_tree_layout(["p"], {"p": ["l", "r"]})
        assert cols["p"]["x"] == (cols["l"]["x"] + cols["r"]["x"]) / 2

    def test_leaves_get_distinct_columns(self):
        cols = tidy_tree_layout(["p"], {"p": ["a", "b", "c"]})
        xs = [cols[n]["x"] for n in ("a", "b", "c")]
        assert len(set(xs)) == 3
        assert min(xs) == 0 and max(xs) == 2 * NODE_SPACING_X

    def test_independent_roots_do_not_overlap(self):
        cols = tidy_tree_layout(["r1", "r2"], {"r1": ["a"], "r2": ["b"]})
        assert cols["r1"]["x"] < cols["r2"]["x"]

    def test_deep_chain_does_not_recurse(self):
        """A long linear thread must not blow the Python stack."""
        depth = 5000
        kids = {f"n{i}": [f"n{i + 1}"] for i in range(depth)}
        cols = tidy_tree_layout(["n0"], kids)
        assert len(cols) == depth + 1


class TestHistoryTreeLayout:
    def test_no_two_nodes_share_a_position(self):
        res = _tree(_branching_thread())
        pos = [(n["position"]["x"], n["position"]["y"]) for n in res["nodes"]]
        assert len(set(pos)) == len(pos)

    def test_sibling_subtrees_never_interleave(self):
        res = _tree(_branching_thread())
        pos = {n["id"]: (n["position"]["x"], n["position"]["y"]) for n in res["nodes"]}
        kids = _children_map(res["edges"])
        for parent, children in kids.items():
            spans = sorted(
                (min(_subtree_xs(k, kids, pos)), max(_subtree_xs(k, kids, pos)))
                for k in children
            )
            for (_, right), (left, _) in zip(spans, spans[1:]):
                assert right < left, f"subtrees under {parent} overlap"

    def test_every_edge_points_downward(self):
        res = _tree(_branching_thread())
        pos = {n["id"]: n["position"] for n in res["nodes"]}
        for e in res["edges"]:
            assert pos[e["target"]]["y"] > pos[e["source"]]["y"]

    def test_saved_position_wins_without_shifting_siblings(self):
        """Pinning one node must not move any other node."""
        states = _branching_thread()
        baseline = {
            n["id"]: (n["position"]["x"], n["position"]["y"])
            for n in _tree(states)["nodes"]
        }
        pinned_id = next(iter(baseline))
        res = _tree(states, {pinned_id: {"x": 9999, "y": 8888}})

        for n in res["nodes"]:
            got = (n["position"]["x"], n["position"]["y"])
            if n["id"] == pinned_id:
                assert got == (9999, 8888)
            else:
                assert got == baseline[n["id"]]

    def test_layout_is_stable_across_repeated_builds(self):
        """Child ordering must be deterministic or nodes jump between refetches."""
        states = _branching_thread()
        runs = [
            {n["id"]: (n["position"]["x"], n["position"]["y"]) for n in _tree(states)["nodes"]}
            for _ in range(3)
        ]
        assert runs[0] == runs[1] == runs[2]


class TestSignificantForest:
    def test_pass_through_nodes_are_reparented(self):
        """A filtered node's children attach to the nearest significant ancestor."""
        id_to_vis = {"a": "a", "skip": "skip", "c": "c"}
        state_map = {}
        for cp, parent in (("a", None), ("skip", "a"), ("c", "skip")):
            s = MagicMock()
            s.parent_config = (
                {"configurable": {"checkpoint_id": parent}} if parent else None
            )
            state_map[cp] = s
        children, parents, roots = build_significant_forest(
            id_to_vis, state_map, {"a", "c"}
        )
        assert roots == ["a"]
        assert parents["c"] == "a"
        assert children["a"] == ["c"]


class TestDebateTree:
    def _debate_states(self, rounds=3):
        c = _Chain()
        prev = None
        for r in range(rounds):
            c.add(f"h{r}", prev, f"prompt {r}", "human")
            c.add(f"a{r}", f"h{r}", f"answer {r}", "ai")
            prev = f"a{r}"
        return c.states

    def _build(self, participants=("m1", "m2"), rounds=3):
        session = {
            "session_id": "s1",
            "parent_thread_id": "t",
            "participants": list(participants),
            "status": "completed",
            "current_round": rounds - 1,
        }
        return build_debate_tree(
            session=session,
            all_thread_states={m: self._debate_states(rounds) for m in participants},
            synthesis_states=[],
            family_colors={m: "#123456" for m in participants},
        )

    def test_only_ai_responses_become_lane_nodes(self):
        tree = self._build()
        lane_nodes = [n for n in tree["nodes"] if n["metadata"].get("lane_index") is not None]
        assert len(lane_nodes) == 2 * 3
        assert all(n["metadata"]["role"] == "ai" for n in lane_nodes)

    def test_round_num_counts_debate_rounds_not_checkpoint_depth(self):
        """Each round writes a prompt AND a response checkpoint; y must not double."""
        tree = self._build(rounds=3)
        for lane in range(2):
            ys = sorted(
                n["position"]["y"]
                for n in tree["nodes"]
                if n["metadata"].get("lane_index") == lane
            )
            assert ys == [0, ROUND_HEIGHT, 2 * ROUND_HEIGHT]

    def test_lanes_are_horizontally_separated(self):
        tree = self._build()
        for lane in range(2):
            xs = {
                n["position"]["x"]
                for n in tree["nodes"]
                if n["metadata"].get("lane_index") == lane
            }
            assert xs == {lane * LANE_WIDTH}

    def test_prompt_node_is_shared_and_fans_out(self):
        tree = self._build()
        prompts = [n for n in tree["nodes"] if n["id"] == "debate::prompt"]
        assert len(prompts) == 1, "the question must appear once, not once per lane"
        assert prompts[0]["position"]["y"] < 0
        targets = {e["target"] for e in tree["edges"] if e["source"] == "debate::prompt"}
        assert len(targets) == 2

    def test_pending_synthesis_node_sits_below_every_lane(self):
        tree = self._build()
        pending = next(n for n in tree["nodes"] if n["id"] == "synthesis::pending")
        lane_ys = [
            n["position"]["y"]
            for n in tree["nodes"]
            if n["metadata"].get("lane_index") is not None
        ]
        assert pending["position"]["y"] > max(lane_ys)
        assert {e["source"] for e in tree["edges"] if e["target"] == "synthesis::pending"}
