import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock


def test_extract_uses_blob_regex_for_ocr_pages():
    from control_point import extract_control_points

    ocr_text = "1  5000000.00  400000.00  100.00  BENCHMARK A"
    ocr_text_by_page = {2: ocr_text}

    with patch("control_point.parse_blob_records", return_value=[{
        "point": "1",
        "northing": "5000000.00",
        "easting": "400000.00",
        "elevation": "100.00",
        "description": "BENCHMARK A",
        "parse_method": "blob_regex",
    }]) as mock_blob:
        records = extract_control_points(
            "fake.pdf",
            page_indices=[2],
            ocr_text_by_page=ocr_text_by_page,
        )

    mock_blob.assert_called_once_with(ocr_text)
    assert len(records) == 1
    assert records[0]["source_page"] == 3
    assert records[0]["table_score"] == 0


def test_extract_skips_pdfplumber_for_ocr_pages():
    import pdfplumber
    from control_point import extract_control_points

    ocr_text_by_page = {0: "1  5000000.00  400000.00  100.00  BENCH"}

    with patch.object(pdfplumber, "open") as mock_plumber:
        with patch("control_point.parse_blob_records", return_value=[]):
            extract_control_points(
                "fake.pdf",
                page_indices=[0],
                ocr_text_by_page=ocr_text_by_page,
            )

    mock_plumber.assert_not_called()
