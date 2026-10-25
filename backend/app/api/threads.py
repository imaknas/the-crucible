import asyncio
from typing import Dict

from fastapi import APIRouter, Depends

from app.api.deps import get_thread_deleter
from app.core import database as db

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("")
async def list_threads():
    try:
        threads = db.list_threads()
        return {"threads": threads}
    except Exception as e:
        return {"error": str(e)}


@router.patch("/{thread_id}/rename")
async def rename_thread(thread_id: str, payload: Dict[str, str]):
    title = payload.get("title")
    if not title:
        return {"error": "Title is required"}
    try:
        await asyncio.to_thread(db.rename_thread, thread_id, title)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, delete=Depends(get_thread_deleter)):
    try:
        # Chroma and SQLite calls are blocking.
        await asyncio.to_thread(delete, thread_id)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}
