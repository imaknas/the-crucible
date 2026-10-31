"""The sidebar lists threads by recent activity, not by their random ids."""

import time

import pytest

from app.core import database as db
from app.services.arena import open_graph
from app.services.runs import resolve_fork_point


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "order.sqlite"))


def test_checkpoint_time_reads_the_uuid6_timestamp():
    from langgraph.checkpoint.base.id import uuid6

    before = time.time()
    stamp = db.checkpoint_time(str(uuid6()))
    assert before - 1 <= stamp <= time.time() + 1
    assert db.checkpoint_time("not-a-uuid") == 0.0
    assert db.checkpoint_time(None) == 0.0


@pytest.mark.asyncio
async def test_threads_are_listed_newest_activity_first():
    async with open_graph() as graph_app:
        # Ids sort opposite to the order they are written in.
        await resolve_fork_point(graph_app, "thread_zzz")
        await resolve_fork_point(graph_app, "thread_mmm")
        await resolve_fork_point(graph_app, "thread_aaa")
        assert [t["id"] for t in db.list_threads()] == ["thread_aaa", "thread_mmm", "thread_zzz"]

        # A debate on the oldest thread writes only to its sub-threads; that
        # still counts as activity on the thread.
        await resolve_fork_point(graph_app, "thread_zzz::debate-1::gpt-5.4")
        assert [t["id"] for t in db.list_threads()] == ["thread_zzz", "thread_aaa", "thread_mmm"]


@pytest.mark.asyncio
async def test_sub_threads_are_never_listed_and_titles_are_kept():
    async with open_graph() as graph_app:
        await resolve_fork_point(graph_app, "thread_one")
        await resolve_fork_point(graph_app, "thread_one::debate-1::gpt-5.4")
    db.rename_thread("thread_one", "Named")
    assert [{"id": t["id"], "title": t["title"]} for t in db.list_threads()] == [{"id": "thread_one", "title": "Named"}]
