import pytest
from fastapi.testclient import TestClient
from app.main import server
from app.mcp_server import invoke_arena, get_thread_status
from unittest.mock import AsyncMock, patch

client = TestClient(server)


@pytest.mark.asyncio
async def test_mcp_get_thread_status_empty():
    """Test MCP status tool with non-existent thread."""
    result = await get_thread_status("non-existent-thread")
    assert "not found" in result.lower()


@pytest.mark.asyncio
@patch("app.mcp_server.run_crucible_arena", new_callable=AsyncMock)
async def test_mcp_invoke_arena_mock(mock_run):
    """Test MCP arena tool with mocked core execution."""
    mock_run.return_value = "Synthesized thesis"
    result = await invoke_arena("Test prompt")
    assert "Consensus Thesis" in result
    assert "Synthesized thesis" in result
    assert "Thread ID: mcp-" in result


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
