import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import server as app


@pytest.fixture
def mock_graph_app():
    return MagicMock()


@pytest.fixture
def mock_db():
    with (
        patch("app.core.database.get_thread_checkpoint_graph") as mock_graph,
        patch("app.core.database.list_threads") as mock_threads,
        patch("app.core.database.get_all_checkpoint_ids") as mock_cids,
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
    with patch("app.core.database.delete_thread_data") as mock_del:
        response = client.delete("/threads/t1")
        assert response.status_code == 200
        mock_del.assert_called_once_with("t1")


def test_rename_thread(client):
    with patch("app.core.database.rename_thread") as mock_rename:
        response = client.patch("/threads/t1/rename", json={"title": "New Title"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_rename.assert_called_once_with("t1", "New Title")


def test_delete_checkpoint(client, mock_graph_app):
    with (
        patch("app.core.database.get_all_checkpoint_ids") as mock_get_all,
        patch("app.core.database.get_thread_checkpoint_graph") as mock_graph,
        patch("app.core.database.delete_checkpoint_data") as mock_del,
    ):
        mock_get_all.return_value = {"cp1", "cp2", "cp3"}
        # Graph: cp1 is root, cp2 child of cp1, cp3 child of cp2
        # If we delete cp2, it should also delete cp3
        mock_graph.return_value = [("cp1", "root"), ("cp2", "cp1"), ("cp3", "cp2")]

        # mock aget_state
        mock_state = MagicMock()
        mock_state.values = {"messages": []}

        async def mock_aget_state(*args, **kwargs):
            return mock_state

        mock_graph_app.aget_state = mock_aget_state


        with patch("app.services.tree.get_content_key", return_value="hash"):
            response = client.delete("/history/t1/checkpoints/cp2")

        assert response.status_code == 200

        # Check what was deleted
        args = mock_del.call_args[0][1]  # set of ids
        assert "cp2" in args
        assert "cp3" in args
        assert "cp1" not in args


def test_save_node_positions(client):
    with patch("app.core.database.save_node_positions") as mock_save:
        payload = [{"node_id": "n1", "x": 10.5, "y": 20.0}]
        response = client.post("/history/t1/positions", json=payload)
        assert response.status_code == 200
        mock_save.assert_called_once()


def test_upload_file(client):
    # Pass background tasks, no index_document required here in test but we can mock it
    with patch("app.services.rag.index_document", return_value=5):
        from io import BytesIO

        file_data = {"file": ("test.txt", BytesIO(b"Hello world"), "text/plain")}

        response = client.post("/upload", data={"thread_id": "t1"}, files=file_data)
        assert response.status_code == 200
        assert response.json()["filename"] == "test.txt"
        assert "Hello world" in response.json()["full_content"]


def test_get_graph_topology(client, mock_graph_app):
    with patch("app.core.database.get_thread_checkpoint_graph") as mock_graph:
        mock_graph.return_value = [("cp1", None), ("cp2", "cp1")]


        async def mock_aget_state(*args, **kwargs):
            mock_state = MagicMock()
            mock_state.values = {"messages": []}
            return mock_state

        mock_graph_app.aget_state = mock_aget_state

        response = client.get("/graph/t1/topology")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1


def test_search_history_with_results(client, mock_graph_app):
    with patch("app.core.database.get_thread_checkpoint_graph") as mock_get_graph:
        mock_get_graph.return_value = [("cp1", "root")]

        # mock aget_state to return state with messages
        from langchain_core.messages import HumanMessage

        mock_state = MagicMock()
        mock_state.values = {
            "messages": [
                HumanMessage(content="This is a search query match inside a message.")
            ]
        }


        async def mock_aget_state(*args, **kwargs):
            return mock_state

        mock_graph_app.aget_state = mock_aget_state

        with patch("app.services.tree.get_checkpoint_role", return_value="user"):
            response = client.get("/history/t1/search?q=search")

        assert response.status_code == 200
        assert len(response.json()["results"]) == 1
        assert "search query match" in response.json()["results"][0]["excerpt"]


def test_get_node_path(client, mock_graph_app):
    mock_state = MagicMock()
    mock_state.values = {"messages": [{"role": "user", "content": "msg"}]}
    mock_state.config = {"configurable": {"checkpoint_id": "cp1"}}


    async def mock_aget_state(*args, **kwargs):
        return mock_state

    mock_graph_app.aget_state = mock_aget_state

    async def mock_history(*args, **kwargs):
        yield mock_state

    mock_graph_app.aget_state_history = mock_history

    with patch("app.services.tree.format_messages", return_value=[{"text": "msg"}]):
        response = client.get("/graph/t1/path/cp1")
        assert response.status_code == 200
        assert response.json()["messages"][0]["text"] == "msg"


def test_chat_endpoint(client, mock_graph_app):

    async def mock_ainvoke(*args, **kwargs):
        return {"messages": []}

    mock_graph_app.ainvoke = mock_ainvoke

    mock_state = MagicMock()
    mock_state.values = {"toggles": {}}
    mock_state.config = {"configurable": {"checkpoint_id": "new-cp"}}

    async def mock_aget_state(*args, **kwargs):
        return mock_state

    mock_graph_app.aget_state = mock_aget_state

    response = client.post("/chat", json={"message": "Hello", "thread_id": "t1"})

    assert response.status_code == 200
    assert response.json()["checkpoint_id"] == "new-cp"
