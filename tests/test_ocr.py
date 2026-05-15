import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import MagicMock, patch


def test_ocr_page_returns_text_from_pytesseract():
    from ocr import ocr_page

    mock_page = MagicMock()
    mock_pixmap = MagicMock()
    mock_pixmap.tobytes.return_value = b"\x89PNG\r\n\x1a\n"
    mock_page.get_pixmap.return_value = mock_pixmap

    with patch("PIL.Image.open", return_value=MagicMock()):
        with patch("pytesseract.image_to_string", return_value="northing easting\n1 100.0 200.0 50.0"):
            result = ocr_page(mock_page)

    assert result == "northing easting\n1 100.0 200.0 50.0"
    mock_page.get_pixmap.assert_called_once_with(dpi=300)


def test_ocr_page_raises_runtime_error_when_tesseract_not_installed():
    import pytesseract
    from ocr import ocr_page

    mock_page = MagicMock()
    mock_pixmap = MagicMock()
    mock_pixmap.tobytes.return_value = b"\x89PNG\r\n\x1a\n"
    mock_page.get_pixmap.return_value = mock_pixmap

    with patch("PIL.Image.open", return_value=MagicMock()):
        with patch("pytesseract.image_to_string", side_effect=pytesseract.TesseractNotFoundError):
            with pytest.raises(RuntimeError, match="Tesseract is not installed"):
                ocr_page(mock_page)


def test_ocr_page_returns_empty_string_when_pixmap_fails():
    from ocr import ocr_page

    mock_page = MagicMock()
    mock_page.get_pixmap.side_effect = Exception("render error")

    result = ocr_page(mock_page)

    assert result == ""


def test_ocr_page_returns_empty_string_when_image_open_fails():
    from ocr import ocr_page

    mock_page = MagicMock()
    mock_pixmap = MagicMock()
    mock_pixmap.tobytes.return_value = b"not a valid png"
    mock_page.get_pixmap.return_value = mock_pixmap

    with patch("PIL.Image.open", side_effect=OSError("invalid image")):
        result = ocr_page(mock_page)

    assert result == ""


def test_configure_tesseract_sets_cmd_when_frozen_and_binary_exists():
    import sys
    import os
    import pytesseract
    import ocr

    fake_exe = os.path.join('/', 'fake', 'ControlPointExtractor', 'ControlPointExtractor.exe')
    expected_cmd = os.path.join(os.path.dirname(fake_exe), 'Tesseract-OCR', 'tesseract.exe')

    with patch.object(sys, 'frozen', True, create=True):
        with patch('sys.executable', fake_exe):
            with patch('ocr.os.path.exists', return_value=True):
                ocr._configure_tesseract()

    assert pytesseract.pytesseract.tesseract_cmd == expected_cmd
    pytesseract.pytesseract.tesseract_cmd = 'tesseract'


def test_configure_tesseract_no_op_when_not_frozen():
    import pytesseract
    import ocr

    original_cmd = pytesseract.pytesseract.tesseract_cmd

    # sys.frozen is not set in normal/test runs — function should be a no-op
    ocr._configure_tesseract()

    assert pytesseract.pytesseract.tesseract_cmd == original_cmd
