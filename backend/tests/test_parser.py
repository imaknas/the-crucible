from unittest.mock import patch, MagicMock
from app.utils.parser import extract_text_from_pdf


def test_extract_text_from_pdf_success():
    with patch("app.utils.parser.fitz.open") as mock_open:
        mock_doc = MagicMock()
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Line 1\n\n\n\nLine 2"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Page 2"

        # Iterating over doc yields pages
        mock_doc.__iter__.return_value = [mock_page1, mock_page2]
        mock_open.return_value = mock_doc

        result = extract_text_from_pdf("dummy.pdf")
        # Should collapse excessive newlines
        assert "Line 1\n\nLine 2Page 2" in result
        mock_doc.close.assert_called_once()


def test_extract_text_from_pdf_exception():
    with patch("app.utils.parser.fitz.open", side_effect=Exception("File not found")):
        result = extract_text_from_pdf("nonexistent.pdf")
        assert "Error parsing PDF: File not found" in result
