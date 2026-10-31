import asyncio
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_thread_deleter
from app.services import threads as threads_svc

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("")
async def list_threads():
    return {"threads": await asyncio.to_thread(threads_svc.list_threads)}


@router.patch("/{thread_id}/rename")
async def rename_thread(thread_id: str, payload: Dict[str, str]):
    try:
        await asyncio.to_thread(threads_svc.rename_thread, thread_id, payload.get("title") or "")
    except threads_svc.ThreadNotFound as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, delete=Depends(get_thread_deleter)):
    try:
        # Chroma and SQLite calls are blocking.
        await asyncio.to_thread(threads_svc.delete_thread, thread_id, delete)
    except threads_svc.ThreadNotFound as e:
        raise HTTPException(404, str(e))
    return {"status": "ok"}
