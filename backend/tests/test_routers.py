import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from main import server as app


@pytest.fixture
def mock_graph_app():
    return MagicMock()


@pytest.fixture
def mock_db():
    with (
        patch("db.get_thread_checkpoint_graph") as mock_graph,
        patch("db.list_threads") as mock_threads,
        patch("db.get_all_checkpoint_ids") as mock_cids,
    ):
        yield {"graph": mock_graph, "threads": mock_threads, "cids": mock_cids}


@pytest.fixture
def client(mock_graph_app):
    """Provides a TestClient that triggers lifespan events."""
    with TestClient(app) as c:
        # Manually inject graph_app into state to ensure it's always there for tests
        c.app.state.graph_app = mock_graph_app
        yield c


def test_get_all_threads(client, mock_db):
    mock_db["threads"].return_value = [
        {"id": "t1", "title": "Thread 1"},
        {"id": "t2", "title": "Thread 2"},
    ]

    response = client.get("/threads")
    assert response.status_code == 200
    data = response.json()
    assert len(data["threads"]) == 2
    assert data["threads"][0]["id"] == "t1"


def test_search_history_empty(client, mock_db):
    mock_db["cids"].return_value = set()

    response = client.get("/history/t1/search?q=test")
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_get_history_missing_thread(client, mock_db):
    mock_db["graph"].return_value = []

    response = client.get("/history/nonexistent")
    assert response.status_code == 200
    assert response.json()["nodes"] == []


def test_delete_thread(client, mock_db):
    with patch("db.delete_thread_data") as mock_del:
        response = client.delete("/threads/t1")
        assert response.status_code == 200
        mock_del.assert_called_once_with("t1")
