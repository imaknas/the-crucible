from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks
import os
import shutil

from parser import extract_text_from_pdf
import rag_service

router = APIRouter(tags=["upload"])


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    thread_id: str = Form(...),
):
    if not file.filename:
        return {"error": "Missing filename"}

    # Security: Sanitize filename to prevent Path Traversal (e.g., ../../../etc/passwd)
    safe_filename = os.path.basename(file.filename)

    os.makedirs("uploads", exist_ok=True)
    file_path = os.path.join("uploads", safe_filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = ""
    if safe_filename.endswith(".pdf"):
        text = extract_text_from_pdf(file_path)
    else:
        with open(file_path, "r") as f:
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
