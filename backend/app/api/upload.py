from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
import os

from app.utils.parser import extract_text_from_pdf
from app.services import rag as rag_service

router = APIRouter(tags=["upload"])

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# Absolute path anchored to the backend root (two levels up from app/api/)
_UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads")),
)


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

    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(_UPLOAD_DIR, safe_filename)

    # Read and size-check before writing
    contents = await file.read()
    if len(contents) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400, detail="File exceeds the 10 MB size limit."
        )

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
