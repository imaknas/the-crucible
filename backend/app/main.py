"""Application assembly: build the FastAPI app and wire its dependencies.

Routes live in app/api/*, behaviour in app/services/*. This module only:
applies third-party patches, compiles the graph once at startup (routers get
it via api.deps.get_graph_app), sets CORS and mounts the routers.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api import chat, config, debate, graph, history, models, threads, upload
from app.core import database as db
from app.patches import apply_langchain_patches
from app.services.graph import workflow

apply_langchain_patches()

ROUTERS = (chat, threads, history, upload, models, graph, config, debate)


def _report_configuration() -> None:
    from app.api.models import FAMILY_META
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    _report_configuration()
    async with AsyncSqliteSaver.from_conn_string(db.DB_PATH) as checkpointer:
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


def _cors_settings() -> dict:
    """Local frontends on any port by default; CORS_ORIGINS adds explicit origins.

    A wildcard let any web page the user visited drive the API, including
    /config/keys, from their browser.
    """
    extra = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    return {
        "allow_origins": extra,
        "allow_origin_regex": r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    }


def create_app() -> FastAPI:
    app = FastAPI(title="The Crucible API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, **_cors_settings(), allow_methods=["*"], allow_headers=["*"])
    for module in ROUTERS:
        app.include_router(module.router)
    return app


server = create_app()


if __name__ == "__main__":
    import uvicorn

    # Loopback by default; the Docker image sets HOST=0.0.0.0 and compose
    # publishes the port on 127.0.0.1 only.
    uvicorn.run(
        "app.main:server",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
