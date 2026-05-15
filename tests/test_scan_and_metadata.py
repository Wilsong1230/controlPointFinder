import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import patch


def test_scan_and_extract_metadata_returns_four_tuple():
    from control_point import scan_and_extract_metadata
    metadata, extraction_pages, reference_pages, ocr_text_by_page = scan_and_extract_metadata("fake.pdf")
    assert isinstance(metadata, dict)
    assert "horizontal_datum" in metadata
    assert "vertical_datum" in metadata
    assert "coordinate_system" in metadata
    assert isinstance(extraction_pages, list)
    assert isinstance(reference_pages, list)
    assert isinstance(ocr_text_by_page, dict)


def test_extract_project_metadata_wrapper_returns_dict():
    from control_point import extract_project_metadata
    metadata = extract_project_metadata("fake.pdf")
    assert isinstance(metadata, dict)
    assert "horizontal_datum" in metadata


def test_scanner_wrapper_returns_two_lists():
    from control_point import scanner
    extraction_pages, reference_pages = scanner("fake.pdf")
    assert isinstance(extraction_pages, list)
    assert isinstance(reference_pages, list)


def test_single_fitz_open_per_pipeline_call():
    import fitz
    from control_point import scan_and_extract_metadata
    with patch.object(fitz, "open", wraps=fitz.open) as mock_open:
        scan_and_extract_metadata("fake.pdf")
    assert mock_open.call_count == 1


def test_empty_pdf_returns_empty_page_lists():
    from control_point import scan_and_extract_metadata
    metadata, extraction_pages, reference_pages, ocr_text_by_page = scan_and_extract_metadata("fake.pdf")
    assert extraction_pages == []
    assert reference_pages == []


def test_scan_calls_ocr_when_page_text_is_sparse():
    import fitz
    from unittest.mock import MagicMock
    from control_point import scan_and_extract_metadata

    mock_page = MagicMock()
    mock_page.get_text.return_value = "tiny"  # fewer than 50 chars

    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 1
    mock_doc.__getitem__ = lambda self, i: mock_page

    with patch.object(fitz, "open", return_value=mock_doc):
        with patch("control_point.ocr_page", return_value="northing easting elevation control point\n1 100.0 200.0 50.0 BENCH") as mock_ocr:
            _, _, _, ocr_text_by_page = scan_and_extract_metadata("fake.pdf")

    mock_ocr.assert_called_once_with(mock_page)
    assert 0 in ocr_text_by_page
    assert "northing" in ocr_text_by_page[0]


def test_scan_skips_ocr_when_page_has_sufficient_text():
    import fitz
    from unittest.mock import MagicMock
    from control_point import scan_and_extract_metadata

    mock_page = MagicMock()
    mock_page.get_text.return_value = "x" * 100  # more than 50 chars

    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 1
    mock_doc.__getitem__ = lambda self, i: mock_page

    with patch.object(fitz, "open", return_value=mock_doc):
        with patch("control_point.ocr_page") as mock_ocr:
            scan_and_extract_metadata("fake.pdf")

    mock_ocr.assert_not_called()


def test_skip_ocr_prevents_ocr_call_on_sparse_page():
    import fitz
    from unittest.mock import MagicMock, patch
    from control_point import scan_and_extract_metadata

    mock_page = MagicMock()
    mock_page.get_text.return_value = "tiny"  # fewer than 50 chars

    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 1
    mock_doc.__getitem__ = lambda self, i: mock_page

    with patch.object(fitz, "open", return_value=mock_doc):
        with patch("control_point.ocr_page") as mock_ocr:
            scan_and_extract_metadata("fake.pdf", skip_ocr=True)

    mock_ocr.assert_not_called()
