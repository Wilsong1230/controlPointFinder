# Extractor Performance Optimization — Design Spec
_Date: 2026-05-13_

## Problem

Processing 300 PDFs takes 30–60 minutes. Target workload is 4000 PDFs. At the current rate that is 7–13 hours — unacceptable for a batch job. Three independent bottlenecks account for essentially all of the time:

1. PDFs are processed one at a time in a sequential `for` loop
2. NOAA NCAT HTTP calls (datum conversion) are fired one at a time, blocking the loop
3. Each PDF triggers two separate `fitz.open` passes (metadata extraction + page scanning)

---

## Optimization 1 — Parallel PDF Worker Pool

### What changes
`batch.py`

### Design

Add a module-level worker function:

```python
def _process_single_pdf(args: tuple[str, str]) -> dict:
    pdf_path, output_csv_path = args
    from control_point import run_control_point_pipeline
    return run_control_point_pipeline(pdf_path, output_csv_path)
```

This function is picklable (module-level, no closures, no tkinter objects) and safe to run in a subprocess.

`_run_pdf_list` replaces its sequential `for` loop with a `ProcessPoolExecutor`:

```python
with ProcessPoolExecutor(max_workers=workers) as pool:
    futures = {
        pool.submit(_process_single_pdf, (str(p), str(output_csv_path))): (i, p)
        for i, p in enumerate(pdf_paths, start=1)
    }
    for future in as_completed(futures):
        i, pdf_path = futures[future]
        # call progress/log callbacks here in the calling thread
```

Worker count is `min(8, os.cpu_count())` by default, passed as a `workers` keyword argument through the call chain: `_run_pdf_list` → `run_batch` / `run_single` / `run_multi` → `run_batch_folder` / `run_batch_packaged` / `run_single_folder` / `run_single_packaged` / `run_multi_packaged` / `run_multi`. GUI passes the default; callers that don't specify get the default.

### Constraints

- Log and progress callbacks are called from the calling thread (same as today) after each future resolves — GUI remains responsive.
- Per-PDF step-level log lines ("Scanning pages…", "Extracting table…") are suppressed during parallel runs because worker processes cannot call the GUI callback. Only PDF-level completion lines appear in the log. This is acceptable; the progress bar and per-PDF status already provide sufficient feedback.
- The review gate (low-confidence modal) runs after all futures complete, unchanged.
- Worker processes import `control_point` lazily (already deferred), so startup cost per worker is amortized across all PDFs that worker handles.
- `if __name__ == "__main__"` guard is required in `main.py` and `gui.py` entry points to prevent recursive subprocess spawning on Windows.

---

## Optimization 2 — Concurrent NCAT HTTP Calls

### What changes
`datum_standardization.py`

### Design

Replace the global `requests.Session` singleton with `threading.local()` so each thread gets its own session:

```python
_tls = threading.local()

def _ncat_session() -> requests.Session:
    if not hasattr(_tls, "session"):
        _tls.session = requests.Session()
    return _tls.session
```

Replace the sequential loop in `standardize_records` with a `ThreadPoolExecutor` (max 20 workers):

```python
def standardize_records(records, log=None):
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda r: standardize_record(r, log=log), records))
    return results
```

Records that need no conversion (`already_target`, `skipped`) return immediately as before. Thread count of 20 is chosen to saturate NCAT's response capacity without hammering the endpoint.

### Constraints

- `standardize_record` mutates the dict in place and returns it — this is safe under threading because each thread works on a distinct dict object.
- The `log` callback (if provided) may be called from multiple threads; callers that pass a log function must be thread-safe (the GUI's `log_threadsafe` already is).
- The public interface `standardize_records(records, log)` is unchanged.

---

## Optimization 3 — Merged fitz Pass

### What changes
`control_point.py`

### Design

Add a new combined function:

```python
def scan_and_extract_metadata(pdf_path, log=None, verbose=False):
    """Single fitz pass: returns (metadata, extraction_page_indices, reference_page_indices)."""
```

This function opens the document once, iterates pages once, and accumulates both the datum metadata (previously done by `extract_project_metadata`) and the page classification (previously done by `scanner`). It closes the document and returns a 3-tuple.

`run_control_point_pipeline` calls `scan_and_extract_metadata` instead of calling `extract_project_metadata` and `scanner` separately.

`extract_project_metadata` and `scanner` remain as thin public wrappers for backward compatibility:

```python
def extract_project_metadata(pdf_path):
    metadata, _, _ = scan_and_extract_metadata(pdf_path)
    return metadata

def scanner(pdf_path, log=None, verbose=False):
    _, extraction_pages, reference_pages = scan_and_extract_metadata(pdf_path, log=log, verbose=verbose)
    return extraction_pages, reference_pages
```

### Constraints

- No behavior change — the page classification logic and metadata extraction logic are identical, just colocated.
- Public API of `extract_project_metadata` and `scanner` is preserved.

---

## Files Changed

| File | Changes |
|---|---|
| `batch.py` | `_process_single_pdf` worker fn; `_run_pdf_list` uses `ProcessPoolExecutor`; `workers` param threaded through all public runners |
| `datum_standardization.py` | `threading.local` session; `ThreadPoolExecutor` in `standardize_records` |
| `control_point.py` | `scan_and_extract_metadata` combined fn; `run_control_point_pipeline` updated; `extract_project_metadata` and `scanner` become wrappers |
| `gui.py` | Add `if __name__ == "__main__"` guard (already present — verify) |
| `main.py` | Add `if __name__ == "__main__"` guard (already present — verify) |

---

## Expected Outcome

| Scenario | Before | After (estimated) |
|---|---|---|
| 300 PDFs, mixed datums | 30–60 min | 4–8 min |
| 4000 PDFs, mixed datums | ~7–13 hr | ~45–90 min |

Estimates assume 8 CPU cores and NCAT average response ~0.5s with 20 concurrent threads.

---

## Out of Scope

- Caching NCAT results to disk across runs
- GPU-accelerated PDF parsing
- Changes to the GUI worker count (uses default; no UI control added)
