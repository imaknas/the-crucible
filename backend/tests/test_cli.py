from typer.testing import CliRunner
from unittest.mock import patch
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
