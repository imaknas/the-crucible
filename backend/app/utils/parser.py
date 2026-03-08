import fitz  # type: ignore  # PyMuPDF
import re


def extract_text_from_pdf(file_path: str) -> str:
    """Extracts and cleans text from a PDF file."""
    text = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            page_text = page.get_text()
            if page_text:
                text += str(page_text)
        doc.close()
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return f"Error parsing PDF: {e}"

    # Aggressive cleaning of control characters that might confuse LLM parsers
    # Keep standard whitespace (newlines, tabs, spaces) but strip others.
    text = "".join(c for c in text if c.isprintable() or c in "\n\r\t")
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
