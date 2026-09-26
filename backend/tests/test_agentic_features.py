import pytest
from fastapi.testclient import TestClient

from app.core import database as db
from app.main import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The real app with its lifespan (compiled graph) on a throwaway database."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "graph.sqlite"))
    with TestClient(server) as c:
        yield c


def test_api_graph_topology_empty(client):
    """Topology of a thread that doesn't exist is an empty graph."""
    data = client.get("/graph/non-existent-thread/topology").json()
    assert data["nodes"] == []
    assert data["edges"] == []


def test_api_node_path_missing(client):
    """A checkpoint that doesn't exist is a 404."""
    assert client.get("/graph/thread-1/path/missing-cid").status_code == 404


def test_graph_routes_report_unready_graph():
    """Without the lifespan there is no graph; routes say so instead of crashing."""
    bare = TestClient(server)  # no `with`: lifespan never runs
    assert bare.get("/graph/any/topology").status_code == 503
