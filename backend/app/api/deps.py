"""FastAPI dependencies shared by the routers.

The compiled graph is created once in main.lifespan and stored on app.state;
routers receive it through ``Depends(get_graph_app)`` rather than importing a
global, so tests can put any graph (or a mock) on ``app.state``.
"""

from fastapi import HTTPException
from starlette.requests import HTTPConnection


def get_graph_app(conn: HTTPConnection):
    """The compiled LangGraph app. Works for HTTP and WebSocket routes."""
    graph_app = getattr(conn.app.state, "graph_app", None)
    if graph_app is None:
        raise HTTPException(503, "Graph not ready")
    return graph_app
