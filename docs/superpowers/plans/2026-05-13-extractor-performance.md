# Extractor Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce 4000-PDF batch runtime from ~13 hours to ~90 minutes by parallelizing PDF processing, concurrently firing NCAT datum-conversion HTTP calls, and eliminating a redundant fitz document open per PDF.

**Architecture:** Three independent optimizations in three files. `control_point.py` merges two sequential fitz passes into one. `datum_standardization.py` replaces a sequential HTTP loop with a `ThreadPoolExecutor` and thread-local sessions. `batch.py` adds a picklable worker function and replaces the sequential PDF loop with `ProcessPoolExecutor`.

**Tech Stack:** Python 3.14, `concurrent.futures.ProcessPoolExecutor`, `concurrent.futures.ThreadPoolExecutor`, `threading.local`, PyMuPDF (fitz), pdfplumber, requests

---

## File Map

| File | Change |
|---|---|
| `control_point.py` | New `scan_and_extract_metadata`; `extract_project_metadata` and `scanner` become wrappers; `run_control_point_pipeline` calls the combined fn |
| `datum_standardization.py` | Replace global session with `threading.local`; wrap `standardize_records` loop in `ThreadPoolExecutor` |
| `batch.py` | Add module-level `_process_single_pdf` worker; rewrite `_run_pdf_list` loop to use `ProcessPoolExecutor`; thread `workers` param through all public runners |
| `tests/test_scan_and_metadata.py` | New — tests for merged fitz pass |
| `tests/test_standardize_concurrent.py` | New — tests for thread-local session and concurrent execution |
| `tests/test_parallel_batch.py` | New — tests for worker function and parallel runner |

---

## Task 1: Merged fitz pass in control_point.py

**Files:**
- Modify: `control_point.py`
- Create: `tests/test_scan_and_metadata.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scan_and_metadata.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import patch


def test_scan_and_extract_metadata_returns_three_tuple():
    from control_point import scan_and_extract_metadata
    metadata, extraction_pages, reference_pages = scan_and_extract_metadata("fake.pdf")
    assert isinstance(metadata, dict)
    assert "horizontal_datum" in metadata
    assert "vertical_datum" in metadata
    assert "coordinate_system" in metadata
    assert isinstance(extraction_pages, list)
    assert isinstance(reference_pages, list)


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
    """run_control_point_pipeline must open fitz exactly once (not twice)."""
    import fitz
    from control_point import scan_and_extract_metadata
    with patch.object(fitz, "open", wraps=fitz.open) as mock_open:
        scan_and_extract_metadata("fake.pdf")
    assert mock_open.call_count == 1


def test_empty_pdf_returns_empty_page_lists():
    from control_point import scan_and_extract_metadata
    # The conftest stub returns an empty doc (0 pages).
    metadata, extraction_pages, reference_pages = scan_and_extract_metadata("fake.pdf")
    assert extraction_pages == []
    assert reference_pages == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/test_scan_and_metadata.py -v
```
Expected: `ImportError: cannot import name 'scan_and_extract_metadata'`

- [ ] **Step 3: Add `scan_and_extract_metadata` to control_point.py**

Read `control_point.py` first. Insert the following new function **between** the `analyze_page` function and the `parse_blob_records` function (around line 122):

```python
def scan_and_extract_metadata(pdf_path, log=None, verbose=False):
    """Single fitz pass: returns (metadata, extraction_page_indices, reference_page_indices)."""
    import fitz
    metadata = {
        "horizontal_datum": "",
        "vertical_datum": "",
        "coordinate_system": "",
        "metadata_pages": [],
        "evidence": [],
    }
    extraction_pages = []
    reference_pages = []

    doc = fitz.open(pdf_path)
    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text("text") or ""
        lower_text = text.lower()
        page_number = page_index + 1

        classification = analyze_page(text)
        if verbose and classification != "OTHER" and log:
            log(f"  - Page {page_number}: {classification}")
        if classification == "PROJECT_CONTROL_TABLE":
            extraction_pages.append(page_index)
        elif classification != "OTHER":
            reference_pages.append(page_index)

        if not any(kw in lower_text for kw in ("datum", "ngvd", "navd", "nad", "state plane")):
            continue

        metadata["metadata_pages"].append(page_number)
        for line in text.splitlines():
            lower_line = line.lower()
            if not any(kw in lower_line for kw in ("datum", "ngvd", "navd", "nad", "state plane")):
                continue
            metadata["evidence"].append({"page": page_number, "line": line.strip()})
            if "ngvd 1929" in lower_line or "ngvd1929" in lower_line:
                metadata["vertical_datum"] = "NGVD 1929"
            if "navd 1988" in lower_line or "navd88" in lower_line or "navd 88" in lower_line:
                metadata["vertical_datum"] = "NAVD 1988"
            if "nad 83" in lower_line or "nad83" in lower_line:
                metadata["horizontal_datum"] = "NAD 83"
            if "nad 27" in lower_line or "nad27" in lower_line:
                metadata["horizontal_datum"] = "NAD 27"
            if "florida state plane" in lower_line and "west zone" in lower_line:
                metadata["coordinate_system"] = "Florida State Plane, West Zone"
            elif "state plane" in lower_line and not metadata["coordinate_system"]:
                metadata["coordinate_system"] = "State Plane"

    doc.close()
    return metadata, extraction_pages, reference_pages
```

- [ ] **Step 4: Replace `extract_project_metadata` and `scanner` with wrappers**

Replace the existing `extract_project_metadata` function body (keep its signature) so it reads:

```python
def extract_project_metadata(pdf_path):
    metadata, _, _ = scan_and_extract_metadata(pdf_path)
    return metadata
```

Replace the existing `scanner` function body (keep its signature) so it reads:

```python
def scanner(pdf_path, log=None, verbose=False):
    _, extraction_pages, reference_pages = scan_and_extract_metadata(
        pdf_path, log=log, verbose=verbose
    )
    return extraction_pages, reference_pages
```

- [ ] **Step 5: Update `run_control_point_pipeline` to use the combined call**

In `run_control_point_pipeline`, replace these two lines:

```python
    metadata = extract_project_metadata(pdf_path)
    ...
    extraction_page_indices, reference_page_indices = scanner(pdf_path, log=log, verbose=False)
```

With this single call (keeping all the log lines between them intact but removing the separate calls):

```python
    metadata, extraction_page_indices, reference_page_indices = scan_and_extract_metadata(
        pdf_path, log=log, verbose=False
    )
```

Remove the now-redundant separate `extract_project_metadata` and `scanner` call sites. The log lines "Reading project metadata…" and "Scanning pages to find control point tables…" can remain; just emit them before the combined call.

- [ ] **Step 6: Run all tests**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/ -v
```
Expected: all tests PASS including the 5 new ones.

- [ ] **Step 7: Commit**

```bash
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && git add control_point.py tests/test_scan_and_metadata.py && git commit -m "perf: merge two fitz passes into one in control_point pipeline"
```

---

## Task 2: Thread-local NCAT session + concurrent standardize_records

**Files:**
- Modify: `datum_standardization.py`
- Create: `tests/test_standardize_concurrent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_standardize_concurrent.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import threading


def test_standardize_records_empty_list():
    from datum_standardization import standardize_records
    result = standardize_records([], log=None)
    assert result == []


def test_standardize_records_returns_all_records():
    from datum_standardization import standardize_records
    records = [
        {
            "easting": "1.0", "northing": "2.0", "elevation": "3.0",
            "horizontal_datum": "NAD 83", "vertical_datum": "NAVD 1988",
            "coordinate_system": "",
        },
        {
            "easting": "4.0", "northing": "5.0", "elevation": "6.0",
            "horizontal_datum": "NAD 83", "vertical_datum": "NAVD 1988",
            "coordinate_system": "",
        },
    ]
    result = standardize_records(records, log=None)
    assert len(result) == 2


def test_ncat_session_is_thread_local():
    from datum_standardization import _ncat_session
    session_ids = []

    def collect():
        session_ids.append(id(_ncat_session()))

    threads = [threading.Thread(target=collect) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Each thread creates its own session — all IDs should be distinct
    assert len(set(session_ids)) == 4


def test_ncat_session_reused_within_same_thread():
    from datum_standardization import _ncat_session
    id1 = id(_ncat_session())
    id2 = id(_ncat_session())
    assert id1 == id2
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/test_standardize_concurrent.py -v
```
Expected: `test_ncat_session_is_thread_local` FAILS because the current implementation uses a global (shared) session.

- [ ] **Step 3: Replace global session with threading.local in datum_standardization.py**

Read `datum_standardization.py`. At the top of the file, add `import threading` alongside the existing imports.

Replace these two lines near the top of the file:

```python
_NCAT_SESSION: Optional[requests.Session] = None


def _ncat_session() -> requests.Session:
    global _NCAT_SESSION
    if _NCAT_SESSION is None:
        _NCAT_SESSION = requests.Session()
    return _NCAT_SESSION
```

With:

```python
_tls = threading.local()


def _ncat_session() -> requests.Session:
    if not hasattr(_tls, "session"):
        _tls.session = requests.Session()
    return _tls.session
```

- [ ] **Step 4: Replace sequential loop with ThreadPoolExecutor in standardize_records**

At the top of `datum_standardization.py`, add to the imports:

```python
from concurrent.futures import ThreadPoolExecutor
```

Replace the `standardize_records` function body:

```python
def standardize_records(records: list[dict[str, Any]], log: LogFn = None) -> list[dict[str, Any]]:
    if not records:
        return records
    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda r: standardize_record(r, log=log), records))
    return records
```

- [ ] **Step 5: Run all tests**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && git add datum_standardization.py tests/test_standardize_concurrent.py && git commit -m "perf: concurrent NCAT calls with thread-local sessions in standardize_records"
```

---

## Task 3: `_process_single_pdf` worker function

**Files:**
- Modify: `batch.py`
- Create: `tests/test_parallel_batch.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_parallel_batch.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/test_parallel_batch.py -v
```
Expected: `ImportError: cannot import name '_process_single_pdf'`

- [ ] **Step 3: Add `_process_single_pdf` to batch.py**

Read `batch.py`. Add the following function **before** `run_batch` (i.e., right after the `_write_manifest` function):

```python
def _process_single_pdf(args: tuple) -> dict:
    """Picklable worker for ProcessPoolExecutor. No callbacks — returns result dict."""
    pdf_path_str, output_csv_path_str = args
    from control_point import run_control_point_pipeline
    try:
        result = run_control_point_pipeline(pdf_path_str, output_csv_path_str, log=None)
        return {"ok": True, "result": result, "pdf_path": pdf_path_str, "output_csv": output_csv_path_str}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "pdf_path": pdf_path_str, "output_csv": output_csv_path_str}
```

- [ ] **Step 4: Run all tests**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && git add batch.py tests/test_parallel_batch.py && git commit -m "feat: add picklable _process_single_pdf worker function"
```

---

## Task 4: Parallel `_run_pdf_list` and thread `workers` through all runners

**Files:**
- Modify: `batch.py`

- [ ] **Step 1: Add imports to batch.py**

At the top of `batch.py`, add:

```python
import os as _os
from concurrent.futures import ProcessPoolExecutor, as_completed
```

- [ ] **Step 2: Rewrite `_run_pdf_list` to use ProcessPoolExecutor**

Replace the entire `_run_pdf_list` function with the following. The setup code (tee_logger, mkdir, manifest) and the post-loop code (deduplication, review gate, CSV writes, summary) are unchanged — only the PDF processing loop is replaced.

```python
def _run_pdf_list(
    pdf_paths: list[Path],
    *,
    output_folder: Path,
    log=None,
    progress=None,
    context_label: str = "",
    review_request_q=None,
    review_result_q=None,
    workers: int | None = None,
):
    if workers is None:
        workers = min(8, _os.cpu_count() or 1)

    output_folder = Path(output_folder)
    individual_output_folder = output_folder / INDIVIDUAL_CSV_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    tee_log, get_log_lines, log_path = _tee_logger(output_folder, log=log)
    started_at = _utc_iso_now()

    if tee_log:
        if context_label:
            tee_log(context_label)
        tee_log(f"Found {len(pdf_paths)} PDF(s). Processing with {workers} worker(s).")

    results = []
    all_valid_records = []
    exact_duplicates_removed_total = 0
    total = len(pdf_paths)

    # Build args upfront: (pdf_path_str, output_csv_path_str)
    pdf_list = list(pdf_paths)
    args_by_index = {
        i: (str(p), str(individual_output_folder / f"{p.stem}_control_points.csv"))
        for i, p in enumerate(pdf_list, start=1)
    }

    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_index = {
            pool.submit(_process_single_pdf, args_by_index[i]): i
            for i in range(1, total + 1)
        }

        for future in as_completed(future_to_index):
            i = future_to_index[future]
            pdf_path = pdf_list[i - 1]
            output_csv_path = args_by_index[i][1]
            worker_result = future.result()

            if worker_result["ok"]:
                result = worker_result["result"]
                all_valid_records.extend(result["records"])
                exact_duplicates_removed_total += int(result.get("exact_duplicates_removed") or 0)
                if tee_log:
                    tee_log(f"[{i}/{total}] Done: {pdf_path.name} — {result['valid_count']} record(s)")
                results.append({
                    "pdf": str(pdf_path),
                    "output_csv": output_csv_path,
                    "extraction_pages": result["extraction_pages"],
                    "reference_pages": result["reference_pages"],
                    "parsed_count": result["parsed_count"],
                    "valid_count": result["valid_count"],
                    "status": "success",
                })
            else:
                error = worker_result["error"]
                if tee_log:
                    tee_log(f"[{i}/{total}] Failed: {pdf_path.name} — {error}")
                results.append({
                    "pdf": pdf_path.name,
                    "output_csv": "",
                    "extraction_pages": [],
                    "reference_pages": [],
                    "parsed_count": 0,
                    "valid_count": 0,
                    "status": f"failed: {error}",
                })

            if progress:
                progress({"phase": "done", "current": i, "total": total, "pdf": str(pdf_path)})

    # ---- Everything below this line is UNCHANGED from the original ----
    combined_csv_path = output_folder / "all_control_points.csv"
    clean_csv_path = output_folder / CLEAN_CSV_NAME
    review_csv_path = output_folder / REVIEW_CSV_NAME
    arcgis_csv_path = output_folder / ARCGIS_CSV_NAME

    if tee_log:
        tee_log("")
        tee_log("Combining results into one CSV…")

    all_valid_records, cross_removed = deduplicate_records(
        all_valid_records, log=tee_log, context="combined",
    )
    all_valid_records = flag_uncertain_duplicates(all_valid_records, log=tee_log, context="combined")

    low_conf, other_records = _split_low_confidence(all_valid_records)

    if low_conf and review_request_q is not None and review_result_q is not None:
        if tee_log:
            tee_log(f"  Found {len(low_conf)} low-confidence record(s) — sending to review modal…")
        pdf_path_map = {p.name: str(p) for p in pdf_list}
        review_request_q.put({"low_conf": low_conf, "pdf_path_map": pdf_path_map})
        modal_result = review_result_q.get(timeout=600)
        accepted_from_modal = modal_result["accepted"]
        skipped_from_modal = modal_result["skipped"]
        for rec in skipped_from_modal:
            rec["review_status"] = "needs_review"
            rec["review_reason"] = "skipped_in_modal_review"
        if tee_log:
            tee_log(
                f"  Modal review done: {len(accepted_from_modal)} accepted, "
                f"{len(skipped_from_modal)} skipped."
            )
    else:
        accepted_from_modal = low_conf
        skipped_from_modal = []

    merged = other_records + accepted_from_modal
    clean_records, auto_review_records = split_clean_vs_review(merged)
    review_records = auto_review_records + skipped_from_modal

    write_csv(clean_records + review_records, str(combined_csv_path))
    write_csv(clean_records, str(clean_csv_path))
    write_csv(review_records, str(review_csv_path))
    write_arcgis_csv(clean_records, str(arcgis_csv_path))

    if tee_log:
        tee_log(
            "Deduplication complete. "
            f"Removed {exact_duplicates_removed_total + cross_removed} exact duplicate point(s)."
        )
        tee_log(f"Wrote clean export: {clean_csv_path.name} ({len(clean_records)} row(s))")
        tee_log(f"Wrote needs review: {review_csv_path.name} ({len(review_records)} row(s))")
        tee_log(f"Wrote ArcGIS CSV:   {arcgis_csv_path.name} ({len(clean_records)} row(s))")

    ended_at = _utc_iso_now()
    summary_path = _write_summary(output_folder, {
        "pdf_count": len(pdf_list),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "clean_csv": str(clean_csv_path),
        "review_csv": str(review_csv_path),
        "arcgis_csv": str(arcgis_csv_path),
        "total_records": len(clean_records) + len(review_records),
        "clean_records": len(clean_records),
        "review_records": len(review_records),
        "duplicate_points_removed": exact_duplicates_removed_total + cross_removed,
    }, started_at=started_at, ended_at=ended_at)

    return {
        "pdf_count": len(pdf_list),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "clean_csv": str(clean_csv_path),
        "review_csv": str(review_csv_path),
        "arcgis_csv": str(arcgis_csv_path),
        "log_txt": log_path,
        "summary_txt": summary_path,
        "individual_csv_folder": str(individual_output_folder),
        "total_records": len(clean_records) + len(review_records),
        "clean_records": len(clean_records),
        "review_records": len(review_records),
        "duplicate_points_removed": exact_duplicates_removed_total + cross_removed,
        "found_pdfs": [str(p) for p in pdf_list],
    }
```

- [ ] **Step 3: Thread `workers` param through all public runner functions**

Add `workers: int | None = None` to each of the following function signatures and pass it through to the next call in the chain. Show the complete updated signature + first call for each:

**`run_batch`:**
```python
def run_batch(input_folder, output_folder, log=None, progress=None,
              review_request_q=None, review_result_q=None, workers=None):
    input_folder = Path(input_folder)
    pdf_paths = sorted(
        path for path in input_folder.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )
    return _run_pdf_list(
        pdf_paths,
        output_folder=Path(output_folder),
        log=log,
        progress=progress,
        context_label=f"Searching for PDFs in: {input_folder}",
        review_request_q=review_request_q,
        review_result_q=review_result_q,
        workers=workers,
    )
```

**`run_multi`:**
```python
def run_multi(pdf_paths: list[str | Path], output_folder, log=None, progress=None,
              review_request_q=None, review_result_q=None, workers=None):
    paths = [Path(p) for p in (pdf_paths or [])]
    paths = [p for p in paths if p.is_file() and p.suffix.lower() == ".pdf"]
    paths = sorted(paths)
    return _run_pdf_list(
        paths,
        output_folder=Path(output_folder),
        log=log,
        progress=progress,
        context_label="Processing selected PDFs…",
        review_request_q=review_request_q,
        review_result_q=review_result_q,
        workers=workers,
    )
```

**`run_single`:**
```python
def run_single(pdf_path, output_folder, log=None, progress=None,
               review_request_q=None, review_result_q=None, workers=None):
    pdf_path = Path(pdf_path)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    return _run_pdf_list(
        [pdf_path],
        output_folder=output_folder,
        log=log,
        progress=progress,
        context_label=f"Processing: {pdf_path.name}",
        review_request_q=review_request_q,
        review_result_q=review_result_q,
        workers=workers,
    )
```

**`run_batch_folder`**, **`run_batch_packaged`**, **`run_single_folder`**, **`run_single_packaged`**, **`run_multi_packaged`**: add `workers=None` to each signature and pass `workers=workers` to their internal `run_batch` / `run_single` / `run_multi` calls.

- [ ] **Step 4: Add test for workers param and parallel count**

Add to `tests/test_parallel_batch.py`:

```python
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
```

- [ ] **Step 5: Verify `if __name__ == "__main__"` guards exist**

On Windows, `ProcessPoolExecutor` uses the "spawn" start method. Without this guard, every spawned worker re-runs the top-level script and causes recursive process creation.

Check both entry points:

```bash
grep -n '__name__' /Users/wilsongomez/Documents/Real_Projects/controlPointFinder/main.py
grep -n '__name__' /Users/wilsongomez/Documents/Real_Projects/controlPointFinder/gui.py
```

Expected output — both files must contain `if __name__ == "__main__":`. If either is missing, add:

```python
if __name__ == "__main__":
    main()   # or: root = ...; app = ...; root.mainloop()
```

Both files already have this guard as of the current codebase — this step is a safety check only.

- [ ] **Step 6: Run all tests**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && python -m pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder && git add batch.py tests/test_parallel_batch.py && git commit -m "perf: parallel PDF processing with ProcessPoolExecutor in _run_pdf_list"
```
