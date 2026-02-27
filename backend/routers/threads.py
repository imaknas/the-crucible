from fastapi import APIRouter
from typing import Dict

import db

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
        db.rename_thread(thread_id, title)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str):
    try:
        db.delete_thread_data(thread_id)
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}
