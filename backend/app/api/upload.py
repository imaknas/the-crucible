from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException

from app.services import rag as rag_service
from app.services.uploads import UPLOAD_DIR, check_size, checked_filename, save_upload

router = APIRouter(tags=["upload"])

# backend/uploads unless UPLOAD_DIR is set; one directory per thread inside.
_UPLOAD_DIR = UPLOAD_DIR


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
        doc = save_upload(thread_id, file.filename, bytes(contents), _UPLOAD_DIR)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Asynchronously index the document into ChromaDB
    background_tasks.add_task(rag_service.index_document, doc.text, doc.filename, thread_id)

    return {
        "filename": doc.filename,
        "content_preview": doc.text[:500],
        "full_content": doc.text,
    }
