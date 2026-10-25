from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
import os
import uuid

from app.utils.parser import extract_text_from_pdf
from app.services import rag as rag_service
from app.services.uploads import UPLOAD_DIR, thread_upload_dir

router = APIRouter(tags=["upload"])

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# backend/uploads unless UPLOAD_DIR is set; one directory per thread inside.
_UPLOAD_DIR = UPLOAD_DIR


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    thread_id: str = Form(...),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    # Security: Sanitize filename to prevent Path Traversal (e.g., ../../../etc/passwd)
    safe_filename = os.path.basename(file.filename)
    _, ext = os.path.splitext(safe_filename.lower())

    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not supported. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    # Read in chunks and stop at the limit instead of buffering the whole body.
    contents = bytearray()
    while chunk := await file.read(1024 * 1024):
        contents.extend(chunk)
        if len(contents) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400, detail="File exceeds the 10 MB size limit."
            )

    # Under the thread's own directory, so deleting the thread removes it.
    # Unique on disk: a shared name let two concurrent uploads of the same
    # filename read back (and index into their thread) each other's content.
    thread_dir = thread_upload_dir(thread_id, _UPLOAD_DIR)
    os.makedirs(thread_dir, exist_ok=True)
    file_path = os.path.join(thread_dir, f"{uuid.uuid4().hex}_{safe_filename}")

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    text = ""
    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
    else:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

    # Asynchronously index the document into ChromaDB
    background_tasks.add_task(
        rag_service.index_document, text, safe_filename, thread_id
    )

    return {
        "filename": safe_filename,
        "content_preview": text[:500],
        "full_content": text,
    }
