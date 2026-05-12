# Design: ArcGIS Output + Interactive Review Modal

**Date:** 2026-05-12
**Status:** Approved

---

## Overview

Two additions to the controlPointFinder pipeline:

1. A final `arcgis_points.csv` output formatted for direct import into ArcGIS.
2. A modal review interface that surfaces low-confidence records after extraction, before any files are written to disk.

---

## Feature 1 — ArcGIS CSV Output

### What it does

At the end of every run, the pipeline writes `arcgis_points.csv` to the same output folder as the other CSVs. This file is formatted for ArcGIS's "Display XY Data" and "XY Table to Point" tools.

### Columns

| Column | Source field |
|---|---|
| `point_id` | `system_point_id` |
| `x` | `easting` |
| `y` | `northing` |
| `elevation` | `elevation` |
| `description` | `description` |
| `source_pdf` | `source_pdf` |

### Inclusion rules

- Only records that have been accepted or edited in the review modal are written to this file.
- Skipped records and records that remain in `needs_review.csv` are excluded.
- Written in the same single output-writing pass as all other files (no separate step).

### No GUI toggle needed

The file is always produced when the run completes. No checkbox or setting required.

---

## Feature 2 — Post-Extraction Review Modal

### Trigger

After all PDFs are processed and records are held in memory, the pipeline checks for any record where `confidence_level == 'low'`. If none exist, output writing proceeds immediately as today. If any exist, the review modal opens before writing.

### Modal structure

A `tk.Toplevel` window that blocks the main window (main window disabled while modal is open). The window close button is inert — the user cannot dismiss the modal without clicking "Finalize."

**Top zone — flagged record table**

A scrollable grid with one row per low-confidence record. Columns:

- Point ID
- Easting
- Northing
- Elevation
- Description
- Confidence score
- Source PDF
- Source page
- Action (Accept / Edit / Skip — one must be selected per row before Finalize is enabled)

Clicking a row updates the PDF viewer and makes that row's fields editable if "Edit" is selected.

**Middle zone — PDF page viewer**

- Renders the source PDF page for the currently selected row using PyMuPDF (already a dependency).
- Scaled to fill the full available modal width, proportional height — large enough to read table text.
- Zoom in / zoom out buttons allow the user to increase or decrease render scale for dense tables.

**Bottom zone — action bar**

- "Accept" — includes the record as-is in final output.
- "Edit" — unlocks the row's fields in the table for inline editing; the edited values replace the originals in the final output.
- "Skip" — moves the record to `needs_review.csv` and excludes it from `arcgis_points.csv`.
- "Finalize" button — disabled until every flagged row has an action assigned. Clicking it closes the modal and triggers output writing.

---

## Data Flow

### Current flow (unchanged concept, timing changed)

Today the pipeline writes files as it goes. Under this design, **nothing is written to disk until after the review modal closes.**

### New flow

1. Extraction runs on a **worker thread**, producing `all_records` in memory with confidence levels attached.
2. Worker separates records into `clean_records` (non-low-confidence) and `low_confidence_records`.
3. Worker posts a message to a `queue.Queue` shared with the main (GUI) thread.
4. Main thread receives the message and, if `low_confidence_records` is non-empty, spawns the review modal.
5. User reviews all flagged records and clicks "Finalize."
6. Modal returns a resolved list: each record tagged `accepted`, `edited` (with updated field values), or `skipped`.
7. Main thread merges `clean_records` + accepted/edited records, runs deduplication, then writes combined outputs:
   - `all_control_points.csv`
   - `needs_review.csv` (skipped records land here)
   - `arcgis_points.csv` (clean + accepted/edited only)
   - `batch_report.csv`
   - `extraction_summary.txt`
   - `extraction_log.txt`

> Individual per-PDF CSVs are written during extraction (step 1), before the review gate, since they reflect raw per-file results and are not affected by the low-confidence review.

### Thread safety

Extraction runs on a worker thread. The GUI (including the modal) runs on the main thread. The worker communicates back via `queue.Queue` — it does not touch Tkinter directly. The main thread polls the queue in its event loop and launches the modal when a review-needed message arrives.

---

## Files Affected

| File | Change |
|---|---|
| `control_point.py` | Pipeline returns records in memory; no file writes inside the pipeline function |
| `batch.py` | Accepts a review callback hook; posts to queue when low-confidence records exist |
| `gui.py` | Adds queue polling, launches review modal, drives final output writing |
| `output_control.py` | Adds `write_arcgis_csv()` function |
| New: `review_modal.py` | Self-contained `ReviewModal` Tkinter class |

---

## Out of Scope

- Medium-confidence records are not queued for review (low only).
- No ArcGIS Pro `.aprx` project generation or geodatabase output.
- No changes to datum conversion, confidence scoring, or deduplication logic.
