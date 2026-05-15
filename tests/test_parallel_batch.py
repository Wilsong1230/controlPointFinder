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
    with patch("pathlib.Path.read_bytes", return_value=b"fake pdf bytes"), \
         patch("batch.run_control_point_pipeline", return_value=_FAKE_PIPELINE_RESULT):
        from batch import _process_single_pdf
        result = _process_single_pdf(("fake.pdf", "out.csv", False))
    assert result["ok"] is True
    assert result["pdf_path"] == "fake.pdf"
    assert result["output_csv"] == "out.csv"
    assert result["result"]["valid_count"] == 2


def test_process_single_pdf_handles_exception():
    with patch("pathlib.Path.read_bytes", return_value=b"fake pdf bytes"), \
         patch("batch.run_control_point_pipeline", side_effect=RuntimeError("bad pdf")):
        from batch import _process_single_pdf
        result = _process_single_pdf(("bad.pdf", "out.csv", False))
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


def test_run_batch_accepts_workers_param():
    import inspect
    from batch import run_batch
    sig = inspect.signature(run_batch)
    assert "workers" in sig.parameters


def test_run_multi_accepts_workers_param():
    import inspect
    from batch import run_multi
    sig = inspect.signature(run_multi)
    assert "workers" in sig.parameters


def test_run_single_accepts_workers_param():
    import inspect
    from batch import run_single
    sig = inspect.signature(run_single)
    assert "workers" in sig.parameters


def test_progress_current_is_monotonically_increasing():
    """Progress callback must receive current=1,2,3 even when futures complete in reverse order."""
    from unittest.mock import MagicMock, patch
    from batch import _run_pdf_list
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_paths = [Path(tmpdir) / f"{n}.pdf" for n in range(1, 4)]
        for p in pdf_paths:
            p.write_bytes(b"%PDF-1.4 fake")

        output_folder = Path(tmpdir) / "out"
        output_folder.mkdir()

        progress_calls = []

        fake_worker_result = {
            "ok": True,
            "pdf_path": "x.pdf",
            "output_csv": "x.csv",
            "result": {
                "records": [],
                "extraction_pages": [],
                "reference_pages": [],
                "parsed_count": 0,
                "valid_count": 0,
                "exact_duplicates_removed": 0,
            },
        }

        # Three mock futures — each returns the same fake result
        mock_futures = [MagicMock() for _ in range(3)]
        for f in mock_futures:
            f.result.return_value = fake_worker_result

        submit_count = [0]

        def mock_submit(fn, args):
            idx = submit_count[0]
            submit_count[0] += 1
            return mock_futures[idx]

        mock_pool = MagicMock()
        mock_pool.submit = mock_submit
        mock_pool.__enter__ = lambda s: mock_pool
        mock_pool.__exit__ = MagicMock(return_value=False)

        # Return futures in REVERSE submission order (index 3 first, then 2, then 1)
        # Old code: progress_calls would be [3, 2, 1]
        # Fixed code: progress_calls should be [1, 2, 3]
        def fake_as_completed(future_to_index):
            return sorted(future_to_index.keys(), key=lambda f: future_to_index[f], reverse=True)

        with patch("batch.ThreadPoolExecutor", return_value=mock_pool), \
             patch("batch.as_completed", fake_as_completed), \
             patch("batch.standardize_records", side_effect=lambda r, **kw: r), \
             patch("batch.apply_confidence", side_effect=lambda r: r), \
             patch("batch.deduplicate_records", side_effect=lambda r, **kw: (r, 0)), \
             patch("batch.flag_uncertain_duplicates", side_effect=lambda r, **kw: r), \
             patch("batch.split_clean_vs_review", return_value=([], [])), \
             patch("batch.assign_system_point_ids"), \
             patch("batch.write_csv"), \
             patch("batch.write_arcgis_csv"), \
             patch("batch._write_summary", return_value=""):
            _run_pdf_list(
                pdf_paths,
                output_folder=output_folder,
                progress=lambda p: progress_calls.append(p["current"]),
                workers=3,
            )

    assert progress_calls == [1, 2, 3], f"Expected [1, 2, 3], got {progress_calls}"


def _make_run_pdf_list_mocks(n_pdfs, tmpdir):
    """Shared mock setup for _run_pdf_list chunking tests."""
    from unittest.mock import MagicMock
    from pathlib import Path

    pdf_paths = [Path(tmpdir) / f"{n}.pdf" for n in range(1, n_pdfs + 1)]
    for p in pdf_paths:
        p.write_bytes(b"%PDF-1.4 fake")

    output_folder = Path(tmpdir) / "out"
    output_folder.mkdir()

    fake_worker_result = {
        "ok": True,
        "pdf_path": "x.pdf",
        "output_csv": "x.csv",
        "result": {
            "records": [],
            "extraction_pages": [],
            "reference_pages": [],
            "parsed_count": 0,
            "valid_count": 0,
            "exact_duplicates_removed": 0,
        },
    }
    return pdf_paths, output_folder, fake_worker_result


def test_chunked_batch_processes_all_pdfs():
    """With _CHUNK_SIZE=2 and 5 PDFs, all 5 complete and progress reaches 5."""
    from unittest.mock import MagicMock, patch
    from batch import _run_pdf_list
    import batch
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_paths, output_folder, fake_worker_result = _make_run_pdf_list_mocks(5, tmpdir)

        progress_calls = []
        submit_count = [0]
        mock_futures = [MagicMock() for _ in range(5)]
        for f in mock_futures:
            f.result.return_value = fake_worker_result

        def mock_submit(fn, args):
            idx = submit_count[0]
            submit_count[0] += 1
            return mock_futures[idx]

        mock_pool = MagicMock()
        mock_pool.submit = mock_submit
        mock_pool.__enter__ = lambda s: mock_pool
        mock_pool.__exit__ = MagicMock(return_value=False)

        with patch.object(batch, "_CHUNK_SIZE", 2), \
             patch("batch.ThreadPoolExecutor", return_value=mock_pool), \
             patch("batch.as_completed", lambda ftoi: list(ftoi.keys())), \
             patch("batch.standardize_records", side_effect=lambda r, **kw: r), \
             patch("batch.apply_confidence", side_effect=lambda r: r), \
             patch("batch.deduplicate_records", side_effect=lambda r, **kw: (r, 0)), \
             patch("batch.flag_uncertain_duplicates", side_effect=lambda r, **kw: r), \
             patch("batch.split_clean_vs_review", return_value=([], [])), \
             patch("batch.assign_system_point_ids"), \
             patch("batch.write_csv"), \
             patch("batch.write_arcgis_csv"), \
             patch("batch._write_summary", return_value=""):
            _run_pdf_list(
                pdf_paths,
                output_folder=output_folder,
                progress=lambda p: progress_calls.append(p["current"]),
                workers=2,
            )

    assert progress_calls == [1, 2, 3, 4, 5], f"Expected [1,2,3,4,5], got {progress_calls}"


def test_chunked_batch_uses_multiple_executor_instances():
    """With _CHUNK_SIZE=2 and 5 PDFs, ThreadPoolExecutor is instantiated 3 times (ceil(5/2)=3 chunks)."""
    from unittest.mock import MagicMock, patch
    from batch import _run_pdf_list
    import batch
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_paths, output_folder, fake_worker_result = _make_run_pdf_list_mocks(5, tmpdir)

        submit_count = [0]
        mock_futures = [MagicMock() for _ in range(5)]
        for f in mock_futures:
            f.result.return_value = fake_worker_result

        def mock_submit(fn, args):
            idx = submit_count[0]
            submit_count[0] += 1
            return mock_futures[idx]

        pool_instances = []

        def make_pool(*args, **kwargs):
            pool = MagicMock()
            pool.submit = mock_submit
            pool.__enter__ = lambda s: pool
            pool.__exit__ = MagicMock(return_value=False)
            pool_instances.append(pool)
            return pool

        with patch.object(batch, "_CHUNK_SIZE", 2), \
             patch("batch.ThreadPoolExecutor", side_effect=make_pool), \
             patch("batch.as_completed", lambda ftoi: list(ftoi.keys())), \
             patch("batch.standardize_records", side_effect=lambda r, **kw: r), \
             patch("batch.apply_confidence", side_effect=lambda r: r), \
             patch("batch.deduplicate_records", side_effect=lambda r, **kw: (r, 0)), \
             patch("batch.flag_uncertain_duplicates", side_effect=lambda r, **kw: r), \
             patch("batch.split_clean_vs_review", return_value=([], [])), \
             patch("batch.assign_system_point_ids"), \
             patch("batch.write_csv"), \
             patch("batch.write_arcgis_csv"), \
             patch("batch._write_summary", return_value=""):
            _run_pdf_list(
                pdf_paths,
                output_folder=output_folder,
                workers=2,
            )

    assert len(pool_instances) == 3, f"Expected 3 executor instances (chunks), got {len(pool_instances)}"


def test_process_single_pdf_passes_skip_ocr_to_pipeline():
    with patch("pathlib.Path.read_bytes", return_value=b"fake pdf bytes"), \
         patch("batch.run_control_point_pipeline", return_value=_FAKE_PIPELINE_RESULT) as mock_pipeline:
        from batch import _process_single_pdf
        _process_single_pdf(("fake.pdf", "out.csv", True))

    _, kwargs = mock_pipeline.call_args
    assert kwargs.get("skip_ocr") is True


def test_stop_event_set_before_loop_returns_stopped_true():
    """When stop_event is already set, _run_pdf_list breaks immediately and returns stopped=True."""
    from unittest.mock import MagicMock, patch
    from batch import _run_pdf_list
    import batch
    import threading
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_paths, output_folder, fake_worker_result = _make_run_pdf_list_mocks(3, tmpdir)

        stop_event = threading.Event()
        stop_event.set()  # Already stopped before we begin

        submit_count = [0]
        mock_futures = [MagicMock() for _ in range(3)]
        for f in mock_futures:
            f.result.return_value = fake_worker_result

        def mock_submit(fn, args):
            idx = submit_count[0]
            submit_count[0] += 1
            return mock_futures[idx]

        mock_pool = MagicMock()
        mock_pool.submit = mock_submit
        mock_pool.__enter__ = lambda s: mock_pool
        mock_pool.__exit__ = MagicMock(return_value=False)

        with patch("batch.ThreadPoolExecutor", return_value=mock_pool), \
             patch("batch.as_completed", lambda ftoi: list(ftoi.keys())), \
             patch("batch.standardize_records", side_effect=lambda r, **kw: r), \
             patch("batch.apply_confidence", side_effect=lambda r: r), \
             patch("batch.deduplicate_records", side_effect=lambda r, **kw: (r, 0)), \
             patch("batch.flag_uncertain_duplicates", side_effect=lambda r, **kw: r), \
             patch("batch.split_clean_vs_review", return_value=([], [])), \
             patch("batch.assign_system_point_ids"), \
             patch("batch.write_csv"), \
             patch("batch.write_arcgis_csv"), \
             patch("batch._write_summary", return_value=""):
            result = _run_pdf_list(
                pdf_paths,
                output_folder=output_folder,
                workers=2,
                stop_event=stop_event,
            )

    assert result["stopped"] is True


def test_stop_event_mid_run_returns_partial_results():
    """When stop_event is set after 1 future, _run_pdf_list returns with stopped=True and 1 result."""
    from unittest.mock import MagicMock, patch
    from batch import _run_pdf_list
    import batch
    import threading
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_paths, output_folder, fake_worker_result = _make_run_pdf_list_mocks(4, tmpdir)

        stop_event = threading.Event()

        submit_count = [0]
        mock_futures = [MagicMock() for _ in range(4)]
        for f in mock_futures:
            f.result.return_value = fake_worker_result

        futures_yielded = [0]

        def mock_submit(fn, args):
            idx = submit_count[0]
            submit_count[0] += 1
            return mock_futures[idx]

        mock_pool = MagicMock()
        mock_pool.submit = mock_submit
        mock_pool.__enter__ = lambda s: mock_pool
        mock_pool.__exit__ = MagicMock(return_value=False)

        # Yield first future, then set stop_event, then yield remaining
        def fake_as_completed(ftoi):
            keys = list(ftoi.keys())
            for k in keys:
                if futures_yielded[0] == 1:
                    stop_event.set()
                futures_yielded[0] += 1
                yield k

        with patch("batch.ThreadPoolExecutor", return_value=mock_pool), \
             patch("batch.as_completed", fake_as_completed), \
             patch("batch.standardize_records", side_effect=lambda r, **kw: r), \
             patch("batch.apply_confidence", side_effect=lambda r: r), \
             patch("batch.deduplicate_records", side_effect=lambda r, **kw: (r, 0)), \
             patch("batch.flag_uncertain_duplicates", side_effect=lambda r, **kw: r), \
             patch("batch.split_clean_vs_review", return_value=([], [])), \
             patch("batch.assign_system_point_ids"), \
             patch("batch.write_csv"), \
             patch("batch.write_arcgis_csv"), \
             patch("batch._write_summary", return_value=""):
            result = _run_pdf_list(
                pdf_paths,
                output_folder=output_folder,
                workers=2,
                stop_event=stop_event,
            )

    assert result["stopped"] is True
    assert len(result["results"]) == 1
