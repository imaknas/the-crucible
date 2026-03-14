from fastmcp import FastMCP
from uuid import uuid4
from typing import Optional, List
from contextlib import asynccontextmanager

from app.services.graph import workflow, run_crucible_arena
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.core import database as db

# Initialize FastMCP
mcp = FastMCP("The Crucible")


@asynccontextmanager
async def get_persistent_graph():
    """Context manager to provide a compiled graph with a valid checkpointer."""
    async with AsyncSqliteSaver.from_conn_string(db.DB_PATH) as saver:
        yield workflow.compile(checkpointer=saver)


@mcp.tool()
async def invoke_arena(
    prompt: str,
    thread_id: Optional[str] = None,
    models: Optional[List[str]] = None,
    use_rag: bool = False,
    cot_enabled: bool = True,
    strict_logic: bool = False,
) -> str:
    """
    Invoke the multi-model Arena for a given prompt.
    This triggers parallel deliberation across major models (OpenAI, Anthropic, Google)
    and returns a synthesized consensus thesis.

    Args:
        prompt: The research question or topic to deliberate.
        thread_id: Optional existing thread ID to continue from.
        models: Optional list of model IDs to include in the arena (e.g. ['gpt-4o', 'claude-sonnet-4-6']).
        use_rag: Whether to search uploaded documents (RAG).
        cot_enabled: Whether to enable Chain-of-Thought (deep reasoning).
        strict_logic: Whether to enforce step-by-step logical constraints.
    """
    try:
        async with get_persistent_graph() as graph_app:
            if not thread_id:
                thread_id = f"mcp-{uuid4().hex[:8]}"
                db.rename_thread(thread_id, f"Arena: {prompt[:30]}...")

            overrides = {
                "use_rag": use_rag,
                "cot_enabled": cot_enabled,
                "strict_logic": strict_logic,
            }

            results = await run_crucible_arena(
                graph_app, prompt, thread_id, overrides=overrides, models=models
            )

            if not results:
                return f"Thread ID: {thread_id}\n\nArena deliberation completed, but no consensus thesis was generated."

            return f"Thread ID: {thread_id}\n\nConsensus Thesis:\n{results}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_thread_summary(thread_id: str) -> str:
    """
    Retrieve a summarized technical brief of the entire conversation path.
    Useful for agents to quickly catch up on context without reading full history.
    """
    try:
        async with get_persistent_graph() as graph_app:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            state = await graph_app.aget_state(config)

            if not state.values:
                return f"Thread {thread_id} not found."

            messages = state.values.get("messages", [])
            # Search for the most recent system summary marker
            summary = "No summary available yet. Run 'invoke_arena' to generate insights."
            for msg in reversed(messages):
                content = str(msg.content)
                if "PREVIOUS CONTEXT SUMMARY:" in content:
                    summary = content.split("PREVIOUS CONTEXT SUMMARY:")[1].strip()
                    break
            
            thesis = state.values.get("current_thesis", "N/A")
            return f"--- Thread Summary ({thread_id}) ---\n\nLatest Thesis: {thesis}\n\nContext Brief: {summary}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
async def get_thread_status(thread_id: str) -> str:
    """
    Fetch the latest status and current thesis for an existing Crucible thread.
    """
    try:
        async with get_persistent_graph() as graph_app:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            state = await graph_app.aget_state(config)

            if not state.values:
                return f"Thread {thread_id} not found or has no state."

            thesis = state.values.get("current_thesis", "No thesis identified.")
            peer = state.values.get("active_peer", "None")

            return (
                f"Thread: {thread_id}\nActive Model: {peer}\nCurrent Thesis: {thesis}"
            )
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run()
