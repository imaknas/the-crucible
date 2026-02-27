from fastapi import APIRouter, UploadFile, File
import os
import shutil

from parser import extract_text_from_pdf

router = APIRouter(tags=["upload"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        return {"error": "Missing filename"}
    os.makedirs("uploads", exist_ok=True)
    file_path = os.path.join("uploads", file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = ""
    if file.filename.endswith(".pdf"):
        text = extract_text_from_pdf(file_path)
    else:
        with open(file_path, "r") as f:
            text = f.read()
    return {
        "filename": file.filename,
        "content_preview": text[:500],
        "full_content": text,
    }
