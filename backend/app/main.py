"""Application assembly: build the FastAPI app and wire its dependencies.

Routes live in app/api/*, behaviour in app/services/*. This module only:
applies third-party patches, compiles the graph once at startup (routers get
it via api.deps.get_graph_app), wires the browser guards (api/security.py)
and mounts the routers.
"""

import asyncio
import logging
import os
from collections.abc import Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api import chat, config, debate, graph, history, models, threads, upload
from app.api.security import (
    OriginPolicy,
    SimpleRequestGuard,
    TrustedHostGuard,
    WebSocketOriginGuard,
    allowed_hosts_from_env,
)
from app.core import database as db
from app.core.storage import Storage, current_storage, has_storage, reset_storage, set_storage
from app.patches import apply_langchain_patches
from app.services.graph import workflow

apply_langchain_patches()

ROUTERS = (chat, threads, history, upload, models, graph, config, debate)


def _report_configuration() -> None:
    from app.registry import FAMILY_META
    from app.llm import fake as fake_llm

    env_keys = [meta["env_key"] for meta in FAMILY_META.values()]
    available = [k for k in env_keys if os.getenv(k)]
    missing = [k for k in env_keys if not os.getenv(k)]
    if not available:
        print(f"\n⚠️  WARNING: No API keys found! Set at least one of: {', '.join(env_keys)}")
        print("   See .env.example for details.\n")
    else:
        print(f"\n✅ API keys loaded: {', '.join(available)}")
        if missing:
            print(f"   ℹ️  Not configured: {', '.join(missing)}\n")
    if fake_llm.enabled():
        print("⚠️  CRUCIBLE_FAKE_LLM is set: every model is a scripted fake (tests only).")


def _configure_logging() -> None:
    """The server's own diagnostics ([INVOKE], [RAG], …) at INFO, on stderr."""
    logger = logging.getLogger("app")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class StorageMiddleware:
    """Sets the app's storage (``app.state.storage``) for every request and
    socket, and for whatever they start: handlers, background tasks and the
    tasks a socket spawns all inherit it."""

    def __init__(self, app, owner: FastAPI):
        self.app = app
        self.owner = owner

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = set_storage(self.owner.state.storage)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_storage(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    token = set_storage(app.state.storage)
    try:
        async with _serving(app):
            yield
    finally:
        reset_storage(token)


@asynccontextmanager
async def _serving(app: FastAPI):
    db.init_db()
    # Not in init_db: the CLI runs that too, while a server may be mid-debate.
    await asyncio.to_thread(db.interrupt_running_debates)
    _report_configuration()
    async with AsyncSqliteSaver.from_conn_string(app.state.storage.db_path) as checkpointer:
        # Create LangGraph's tables now rather than on first write, so reads of
        # a fresh database (thread lists, topology) don't hit "no such table".
        await checkpointer.setup()
        app.state.graph_app = workflow.compile(checkpointer=checkpointer)
        try:
            yield
        finally:
            # The checkpointer closes with this block; don't leave a graph
            # behind that points at it.
            app.state.graph_app = None


def create_app(
    origin_policy: OriginPolicy | None = None,
    allowed_hosts: Sequence[str] | None = None,
    storage: Storage | None = None,
) -> FastAPI:
    """Build the app. All three default to the environment (CORS_ORIGINS,
    ALLOWED_HOSTS; DATABASE_PATH, UPLOAD_DIR, CHROMA_DIR via Storage.from_env).

    No wildcard origin: it let any web page the user visited drive the API,
    including /config/keys, from their browser.
    """
    origin_policy = origin_policy or OriginPolicy.from_env(os.environ)
    if allowed_hosts is None:
        allowed_hosts = allowed_hosts_from_env(os.environ)
    app = FastAPI(title="The Crucible API", lifespan=lifespan)
    # The storage already in effect (a test, a program embedding the app),
    # else the app's own locations.
    app.state.storage = storage or (current_storage() if has_storage() else Storage.from_env())
    # add_middleware wraps: the last one added runs first. CORS sits outside
    # SimpleRequestGuard so preflights are answered before the header check.
    app.add_middleware(SimpleRequestGuard)
    app.add_middleware(WebSocketOriginGuard, policy=origin_policy)
    app.add_middleware(CORSMiddleware, **origin_policy.cors_options(), allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(TrustedHostGuard, allowed_hosts=allowed_hosts)
    app.add_middleware(StorageMiddleware, owner=app)
    for module in ROUTERS:
        app.include_router(module.router)
    return app


server = create_app()


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv

    # The entry point reads backend/.env (the reloader's worker inherits the
    # environment); importing app modules never does.
    load_dotenv()

    # Loopback by default; the Docker image sets HOST=0.0.0.0 and compose
    # publishes the port on 127.0.0.1 only.
    uvicorn.run(
        "app.main:server",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
