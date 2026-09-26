from fastapi.testclient import TestClient
from app.main import server

client = TestClient(server)


def test_api_graph_topology_empty():
    """Test topology API with non-existent thread."""
    response = client.get("/graph/non-existent-thread/topology")
    assert response.status_code == 200
    data = response.json()
    assert data["nodes"] == []
    assert data["edges"] == []


def test_api_node_path_missing():
    """Test node path API with missing checkpoint."""
    response = client.get("/graph/thread-1/path/missing-cid")
    # Should error because checkpoint doesn't exist in DB
    assert (
        response.status_code == 500
    )  # Current implementation raises Exception if state not found
