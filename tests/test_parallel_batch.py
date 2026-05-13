import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import patch


_FAKE_PIPELINE_RESULT = {
    "records": [],
    "extraction_pages": [1],
    "reference_pages": [],
    "parsed_count": 2,
    "valid_count": 2,
    "exact_duplicates_removed": 0,
    "metadata": {},
    "output_path": "out.csv",
}


def test_process_single_pdf_success():
    with patch("control_point.run_control_point_pipeline", return_value=_FAKE_PIPELINE_RESULT):
        from batch import _process_single_pdf
        result = _process_single_pdf(("fake.pdf", "out.csv"))
    assert result["ok"] is True
    assert result["pdf_path"] == "fake.pdf"
    assert result["output_csv"] == "out.csv"
    assert result["result"]["valid_count"] == 2


def test_process_single_pdf_handles_exception():
    with patch("control_point.run_control_point_pipeline", side_effect=RuntimeError("bad pdf")):
        from batch import _process_single_pdf
        result = _process_single_pdf(("bad.pdf", "out.csv"))
    assert result["ok"] is False
    assert "bad pdf" in result["error"]
    assert result["pdf_path"] == "bad.pdf"


def test_process_single_pdf_is_module_level():
    """Worker must be a module-level function to be picklable by ProcessPoolExecutor."""
    import batch
    import pickle
    fn = batch._process_single_pdf
    # If this doesn't raise, the function is picklable
    pickle.dumps(fn)
