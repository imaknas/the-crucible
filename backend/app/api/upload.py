import asyncio

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException

from app.core.database import ThreadDocumentStore

from app.services import rag as rag_service
from app.services.uploads import check_size, checked_filename, keep_upload, save_upload

router = APIRouter(tags=["upload"])



@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    thread_id: str = Form(...),
):
    try:
        checked_filename(file.filename)
        # Read in chunks and stop at the limit instead of buffering the whole body.
        contents = bytearray()
        while chunk := await file.read(1024 * 1024):
            contents.extend(chunk)
            check_size(len(contents))
        # Off the loop: writing the file and extracting a PDF's text block.
        doc = await asyncio.to_thread(save_upload, thread_id, file.filename, bytes(contents))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Kept before answering: the next frame may name the file. Indexing
    # loads the embedding model, so it runs after the response.
    store = ThreadDocumentStore()
    await asyncio.to_thread(store.save, thread_id, {doc.filename: doc.text})
    background_tasks.add_task(keep_upload, thread_id, doc, rag_service.index_document, store)

    return {
        "filename": doc.filename,
        "content_preview": doc.text[:500],
        "full_content": doc.text,
    }
