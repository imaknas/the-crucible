"""Tests for history_tree.py — pure graph functions.

No DB or LLM calls — all state objects are mocked.
"""

from unittest.mock import MagicMock, patch


def _make_state(cp_id, parent_id=None, messages=None, active_peer="gpt-5.2"):
    """Helper to create a mock state object."""
    state = MagicMock()
    state.config = {"configurable": {"checkpoint_id": cp_id}}
    state.parent_config = (
        {"configurable": {"checkpoint_id": parent_id}} if parent_id else None
    )
    state.values = {
        "messages": messages or [],
        "active_peer": active_peer,
        "current_thesis": "",
    }
    return state


def _make_message(content, msg_type="human"):
    msg = MagicMock()
    msg.content = content
    msg.type = msg_type
    msg.name = None  # Ensure it doesn't return a new MagicMock for name
    msg.additional_kwargs = {}
    msg.response_metadata = {}
    return msg


class TestGetCheckpointRole:
    def test_empty_messages(self):
        from history_tree import get_checkpoint_role

        state = _make_state("cp1")
        assert get_checkpoint_role(state) == "system"

    def test_human_message(self):
        from history_tree import get_checkpoint_role

        state = _make_state("cp1", messages=[_make_message("Hello", "human")])
        assert get_checkpoint_role(state) == "user"

    def test_ai_message(self):
        from history_tree import get_checkpoint_role

        state = _make_state("cp1", messages=[_make_message("Reply", "ai")])
        assert get_checkpoint_role(state) == "assistant"


class TestGetContentKey:
    def test_empty_messages(self):
        from history_tree import get_content_key

        state = _make_state("cp1")
        assert get_content_key(state) == "EMPTY"

    def test_unique_key(self):
        from history_tree import get_content_key

        s1 = _make_state("cp1", messages=[_make_message("Hello", "human")])
        s2 = _make_state("cp2", messages=[_make_message("World", "human")])
        assert get_content_key(s1) != get_content_key(s2)

    def test_same_key_for_identical(self):
        from history_tree import get_content_key

        s1 = _make_state("cp1", messages=[_make_message("Hello", "human")])
        s2 = _make_state("cp2", messages=[_make_message("Hello", "human")])
        assert get_content_key(s1) == get_content_key(s2)


class TestBuildGraphStructure:
    def test_single_root(self):
        from history_tree import build_graph_structure

        root = _make_state("root")
        child_map, state_map, roots = build_graph_structure([root])
        assert roots == ["root"]
        assert "root" in state_map
        assert child_map == {}

    def test_linear_chain(self):
        from history_tree import build_graph_structure

        s1 = _make_state("cp1")
        s2 = _make_state("cp2", parent_id="cp1")
        s3 = _make_state("cp3", parent_id="cp2")
        child_map, state_map, roots = build_graph_structure([s1, s2, s3])

        assert roots == ["cp1"]
        assert "cp2" in child_map.get("cp1", [])
        assert "cp3" in child_map.get("cp2", [])

    def test_branch(self):
        from history_tree import build_graph_structure

        s1 = _make_state("cp1")
        s2 = _make_state("cp2", parent_id="cp1")
        s3 = _make_state("cp3", parent_id="cp1")  # Branch from cp1
        child_map, _, _ = build_graph_structure([s1, s2, s3])

        children_of_cp1 = child_map.get("cp1", [])
        assert "cp2" in children_of_cp1
        assert "cp3" in children_of_cp1


class TestDeduplicateCheckpoints:
    def test_no_duplicates(self):
        from history_tree import build_graph_structure, deduplicate_checkpoints

        s1 = _make_state("cp1", messages=[_make_message("Hello", "human")])
        s2 = _make_state(
            "cp2", parent_id="cp1", messages=[_make_message("Reply", "ai")]
        )
        # all_states must be newest-first (LangGraph order); deduplicate_checkpoints reverses internally
        all_states = [s2, s1]
        child_map, state_map, roots = build_graph_structure(all_states)
        id_to_vis, sig_ids = deduplicate_checkpoints(roots, child_map, state_map)

        assert "cp1" in sig_ids
        assert "cp2" in sig_ids

    def test_deduplicates_same_content(self):
        from history_tree import build_graph_structure, deduplicate_checkpoints

        msg = [_make_message("Hello", "human")]
        s1 = _make_state("cp1", messages=msg)
        s2 = _make_state("cp2", parent_id="cp1", messages=msg)  # Same content → dedup
        all_states = [s2, s1]  # newest-first
        child_map, state_map, roots = build_graph_structure(all_states)
        id_to_vis, sig_ids = deduplicate_checkpoints(roots, child_map, state_map)

        # cp2 should map to cp1 since content is identical
        assert id_to_vis["cp2"] == "cp1"


class TestFormatMessages:
    def test_human_message(self):
        from history_tree import format_messages

        state = _make_state(
            "cp1", messages=[_make_message("Hello", "human")], active_peer="gpt-5.2"
        )
        state_map = {"cp1": state}
        result = format_messages("cp1", state_map)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert result[0]["model"] == "user"

    def test_ai_message(self):
        from history_tree import format_messages

        state = _make_state(
            "cp1", messages=[_make_message("Reply", "ai")], active_peer="gpt-5.2"
        )
        state_map = {"cp1": state}
        result = format_messages("cp1", state_map)
        assert result[0]["role"] == "assistant"
        assert result[0]["model"] == "gpt-5.2"

    def test_mixed_messages(self):
        from history_tree import format_messages

        s1 = _make_state("cp1", messages=[_make_message("Hello", "human")])
        s2 = _make_state(
            "cp2",
            parent_id="cp1",
            messages=[_make_message("Reply", "ai")],
            active_peer="gpt-4",
        )
        s3 = _make_state(
            "cp3", parent_id="cp2", messages=[_make_message("Follow up", "human")]
        )

        state_map = {"cp1": s1, "cp2": s2, "cp3": s3}
        result = format_messages("cp3", state_map)
        assert len(result) == 3
        assert result[0]["content"] == "Hello"
        assert result[1]["content"] == "Reply"
        assert result[1]["model"] == "gpt-4"
        assert result[2]["content"] == "Follow up"
        assert result[2]["role"] == "user"


class TestBuildHistoryTree:
    @patch("history_tree.load_node_positions", return_value={})
    def test_full_pipeline(self, _):
        from history_tree import build_history_tree

        s1 = _make_state("cp1", messages=[_make_message("Hello", "human")])
        s2 = _make_state(
            "cp2",
            parent_id="cp1",
            messages=[
                _make_message("Hello", "human"),
                _make_message("Reply", "ai"),
            ],
        )

        result = build_history_tree("thread-1", [s2, s1], s2)  # newest-first
        assert "nodes" in result
        assert "edges" in result
        assert "messages" in result
        assert "current_checkpoint" in result
        assert len(result["messages"]) == 2

    @patch("history_tree.load_node_positions", return_value={})
    def test_branching_tree(self, _):
        from history_tree import build_history_tree

        root = _make_state("root", messages=[_make_message("Start", "human")])
        branch_a = _make_state(
            "bA",
            parent_id="root",
            messages=[
                _make_message("Start", "human"),
                _make_message("Branch A reply", "ai"),
            ],
        )
        branch_b = _make_state(
            "bB",
            parent_id="root",
            messages=[
                _make_message("Start", "human"),
                _make_message("Branch B reply", "ai"),
            ],
        )

        result = build_history_tree(
            "thread-1", [branch_b, branch_a, root], branch_a
        )  # newest-first
        assert len(result["edges"]) >= 1  # At least root→branchA
