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
