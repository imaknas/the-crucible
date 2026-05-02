from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from app.cli import app

runner = CliRunner()


def test_threads_command():
    with patch("app.core.database.list_threads") as mock_list:
        mock_list.return_value = [
            {"id": "t1", "title": "Thread 1", "created_at": "2023-01-01"}
        ]
        result = runner.invoke(app, ["threads"])
        assert result.exit_code == 0
        assert "Thread 1" in result.stdout


def test_threads_rename_command():
    with patch("app.core.database.rename_thread") as mock_rename:
        result = runner.invoke(
            app, ["threads", "--rename", "t1", "--title", "New Title"]
        )
        assert result.exit_code == 0
        mock_rename.assert_called_once_with("t1", "New Title")


def test_threads_delete_command():
    with (
        patch("app.core.database.delete_thread_data") as mock_delete,
        patch("typer.confirm", return_value=True),
    ):
        result = runner.invoke(app, ["threads", "--delete", "t1"])
        assert result.exit_code == 0
        mock_delete.assert_called_once_with("t1")


def test_chat_command():
    with patch("app.cli._get_graph") as mock_get_graph, patch("app.cli._load_env"):
        mock_app = MagicMock()
        mock_saver = MagicMock()

        # Ensure saver is an async context manager
        async def mock_aenter():
            return mock_saver

        async def mock_aexit(*args):
            pass

        mock_saver.__aenter__ = mock_aenter
        mock_saver.__aexit__ = mock_aexit

        mock_get_graph.return_value = (mock_app, mock_saver)

        mock_state = MagicMock()
        mock_state.values = {}

        async def mock_aget_state(*args, **kwargs):
            return mock_state

        mock_app.aget_state = mock_aget_state

        async def mock_astream(*args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "metadata": {"langgraph_node": "draft"},
                "data": {"chunk": MagicMock(content="Hello ")},
            }

        mock_app.astream_events = mock_astream

        result = runner.invoke(app, ["chat", "Hello", "--model", "gpt-5.2"])
        assert result.exit_code == 0
        assert "Hello " in result.stdout


def test_arena_command():
    with (
        patch("app.services.graph.run_arena_streaming") as mock_run_arena,
        patch("app.cli._get_graph") as mock_get_graph,
        patch("app.cli_display.ArenaDisplay"),
        patch("app.cli._load_env"),
    ):
        mock_saver = MagicMock()

        async def mock_aenter():
            return mock_saver

        async def mock_aexit(*args):
            pass

        mock_saver.__aenter__ = mock_aenter
        mock_saver.__aexit__ = mock_aexit

        mock_get_graph.return_value = (MagicMock(), mock_saver)

        async def mock_stream(*args, **kwargs):
            yield {"type": "token", "model": "gpt-5.2", "token": "Hello"}
            yield {"type": "end", "model": "gpt-5.2", "content": "Hello"}
            yield {"type": "synthesis", "content": "Consensus"}

        mock_run_arena.return_value = mock_stream()

        result = runner.invoke(
            app, ["arena", "Discuss this", "--models", "gpt-5.2", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "Discuss this" in result.stdout or "Consensus" in result.stdout
