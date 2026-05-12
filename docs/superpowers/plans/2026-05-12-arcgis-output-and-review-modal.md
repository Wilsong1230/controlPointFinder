# ArcGIS Output + Review Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-extraction review modal that surfaces low-confidence records for user action before writing any combined output, and produce an `arcgis_points.csv` file formatted for ArcGIS "Display XY Data" import.

**Architecture:** Worker thread runs all extraction as today (individual per-PDF CSVs still written during extraction). When extraction is complete, if any records have `confidence_level == "low"`, the worker posts to a `queue.Queue` and blocks; the main GUI thread receives the message, spawns a `ReviewModal` Toplevel window, waits for the user to finalize, then posts results back to a second queue, unblocking the worker. The worker then merges accepted/rejected records, runs the normal clean/needs-review split, and writes all combined outputs including `arcgis_points.csv`.

**Tech Stack:** Python 3, Tkinter, PyMuPDF (fitz), pdfplumber, queue.Queue, pytest

---

## File Map

| File | Role |
|---|---|
| `output_control.py` | Add `write_arcgis_csv()` |
| `review_modal.py` (new) | `ReviewModal` Tkinter class + `apply_modal_actions()` pure helper |
| `batch.py` | Add `_split_low_confidence()`, thread queues through all public functions, refactor `run_single` to call `_run_pdf_list`, write ArcGIS CSV in combined output pass |
| `gui.py` | Create queues per run, poll `review_request_q`, spawn modal, pass queues into batch functions |
| `tests/test_output_control.py` (new) | Tests for `write_arcgis_csv` |
| `tests/test_review_modal_data.py` (new) | Tests for `apply_modal_actions` |
| `tests/test_batch_split.py` (new) | Tests for `_split_low_confidence` |

---

## Task 1: `write_arcgis_csv` in `output_control.py`

**Files:**
- Modify: `output_control.py`
- Create: `tests/test_output_control.py`

- [ ] **Step 1: Create the tests directory and write the failing test**

Create `tests/__init__.py` (empty) and `tests/test_output_control.py`:

```python
import csv
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from output_control import write_arcgis_csv


def _make_record(**kwargs):
    base = {
        "system_point_id": "CP000001",
        "point": "219",
        "easting": "746147.13",
        "northing": "770035.76",
        "elevation": "20.54",
        "description": "SET IRON PIPE",
        "source_pdf": "test.pdf",
        "confidence_level": "high",
    }
    base.update(kwargs)
    return base


def test_write_arcgis_csv_columns():
    records = [_make_record()]
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv(records, path)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["point_id", "x", "y", "elevation", "description", "source_pdf"]
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["point_id"] == "CP000001"
    assert rows[0]["x"] == "746147.13"
    assert rows[0]["y"] == "770035.76"
    assert rows[0]["elevation"] == "20.54"
    assert rows[0]["description"] == "SET IRON PIPE"
    assert rows[0]["source_pdf"] == "test.pdf"


def test_write_arcgis_csv_uses_system_point_id_over_point():
    records = [_make_record(system_point_id="CP000005", point="5")]
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv(records, path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["point_id"] == "CP000005"


def test_write_arcgis_csv_falls_back_to_point_when_no_system_id():
    records = [_make_record(system_point_id="", point="42")]
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv(records, path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["point_id"] == "42"


def test_write_arcgis_csv_empty_list():
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv([], path)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["point_id", "x", "y", "elevation", "description", "source_pdf"]
        assert list(reader) == []
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder
pytest tests/test_output_control.py -v
```

Expected: `ImportError` or `AttributeError: module 'output_control' has no attribute 'write_arcgis_csv'`

- [ ] **Step 3: Implement `write_arcgis_csv` in `output_control.py`**

Add after the last existing function in `output_control.py`:

```python
ARCGIS_CSV_FIELDS = ["point_id", "x", "y", "elevation", "description", "source_pdf"]


def write_arcgis_csv(records: list[dict], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ARCGIS_CSV_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "point_id": rec.get("system_point_id") or rec.get("point") or "",
                "x": rec.get("easting") or "",
                "y": rec.get("northing") or "",
                "elevation": rec.get("elevation") or "",
                "description": rec.get("description") or "",
                "source_pdf": rec.get("source_pdf") or "",
            })
```

- [ ] **Step 4: Run the tests to verify they pass**

```
pytest tests/test_output_control.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add output_control.py tests/__init__.py tests/test_output_control.py
git commit -m "feat: add write_arcgis_csv to output_control"
```

---

## Task 2: `apply_modal_actions` pure function + tests

This is the data transformation logic at the heart of the modal — it is kept pure (no Tkinter dependency) so it can be unit tested.

**Files:**
- Create: `review_modal.py`
- Create: `tests/test_review_modal_data.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_modal_data.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from review_modal import apply_modal_actions


def _rec(point_id="CP000001", confidence_level="low", **kwargs):
    base = {
        "system_point_id": point_id,
        "point": "1",
        "easting": "100.0",
        "northing": "200.0",
        "elevation": "10.0",
        "description": "TEST",
        "source_pdf": "a.pdf",
        "confidence_level": confidence_level,
    }
    base.update(kwargs)
    return base


def test_all_accepted():
    records = [_rec("CP1"), _rec("CP2")]
    actions = {0: "accepted", 1: "accepted"}
    result = apply_modal_actions(records, actions, edits={})
    assert len(result["accepted"]) == 2
    assert len(result["skipped"]) == 0


def test_all_skipped():
    records = [_rec("CP1"), _rec("CP2")]
    actions = {0: "skipped", 1: "skipped"}
    result = apply_modal_actions(records, actions, edits={})
    assert len(result["accepted"]) == 0
    assert len(result["skipped"]) == 2


def test_mixed_actions():
    records = [_rec("CP1"), _rec("CP2"), _rec("CP3")]
    actions = {0: "accepted", 1: "skipped", 2: "edited"}
    result = apply_modal_actions(records, actions, edits={2: {"elevation": "99.9"}})
    assert len(result["accepted"]) == 2
    assert result["accepted"][1]["system_point_id"] == "CP3"
    assert result["accepted"][1]["elevation"] == "99.9"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["system_point_id"] == "CP2"


def test_edited_fields_applied():
    records = [_rec("CP1")]
    actions = {0: "edited"}
    edits = {0: {"easting": "111.1", "description": "UPDATED"}}
    result = apply_modal_actions(records, actions, edits=edits)
    r = result["accepted"][0]
    assert r["easting"] == "111.1"
    assert r["description"] == "UPDATED"
    assert r["northing"] == "200.0"  # unchanged field preserved


def test_original_records_not_mutated():
    original = _rec("CP1")
    records = [original]
    actions = {0: "edited"}
    edits = {0: {"easting": "999.0"}}
    apply_modal_actions(records, actions, edits=edits)
    assert original["easting"] == "100.0"  # original untouched
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_review_modal_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'review_modal'`

- [ ] **Step 3: Create `review_modal.py` with the pure function**

Create `review_modal.py`:

```python
from __future__ import annotations
from typing import Any


def apply_modal_actions(
    records: list[dict[str, Any]],
    actions: dict[int, str],
    edits: dict[int, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Pure function: applies user review actions to a list of low-confidence records.

    actions: {index: "accepted" | "skipped" | "edited"}
    edits:   {index: {field_name: new_value}}  — only used when action == "edited"

    Returns {"accepted": [...], "skipped": [...]}.
    Accepted includes both "accepted" and "edited" records.
    Does not mutate the input records.
    """
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for i, rec in enumerate(records):
        action = actions.get(i, "accepted")
        r = dict(rec)
        if action == "skipped":
            skipped.append(r)
        else:
            if action == "edited" and i in edits:
                r.update(edits[i])
            accepted.append(r)

    return {"accepted": accepted, "skipped": skipped}
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_review_modal_data.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add review_modal.py tests/test_review_modal_data.py
git commit -m "feat: add apply_modal_actions pure function with tests"
```

---

## Task 3: Build the `ReviewModal` Tkinter class

**Files:**
- Modify: `review_modal.py`

The modal has three zones stacked vertically:
1. **Top** — `ttk.Treeview` table of flagged records; selecting a row drives the bottom zones
2. **Middle** — PDF page canvas (fills width, proportional height, zoom controls)
3. **Bottom** — Action buttons (Accept / Skip / Edit) + inline edit fields + Finalize button

- [ ] **Step 1: Add imports and skeleton to `review_modal.py`**

Append to `review_modal.py` after `apply_modal_actions`:

```python
import base64
import tkinter as tk
from tkinter import ttk, scrolledtext
from pathlib import Path

import fitz


class ReviewModal:
    def __init__(
        self,
        parent: tk.Tk,
        low_conf_records: list[dict],
        pdf_path_map: dict[str, str],
    ):
        self.window = tk.Toplevel(parent)
        self.window.title(f"Review Low-Confidence Records ({len(low_conf_records)} rows)")
        self.window.geometry("1150x860")
        self.window.minsize(900, 700)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)
        self.window.grab_set()

        self._records: list[dict] = [dict(r) for r in low_conf_records]
        self._pdf_path_map: dict[str, str] = pdf_path_map
        self._actions: dict[int, str] = {}
        self._edits: dict[int, dict] = {}
        self._zoom: float = 2.0
        self._current_index: int | None = None
        self._photo = None

        self._build_ui()
        if self._records:
            self._select_row(0)

    def get_results(self) -> dict:
        return apply_modal_actions(self._records, self._actions, self._edits)
```

- [ ] **Step 2: Implement `_build_ui` — layout skeleton**

Add to the `ReviewModal` class:

```python
    def _build_ui(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=0)  # table
        self.window.rowconfigure(1, weight=1)  # pdf viewer
        self.window.rowconfigure(2, weight=0)  # action bar

        # --- Top: record table ---
        table_frame = tk.Frame(self.window, bd=1, relief=tk.SUNKEN)
        table_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        self._build_table(table_frame)

        # --- Middle: PDF viewer ---
        viewer_frame = tk.LabelFrame(self.window, text="PDF Source Page")
        viewer_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self._build_pdf_viewer(viewer_frame)

        # --- Bottom: action + finalize ---
        action_frame = tk.Frame(self.window)
        action_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._build_action_bar(action_frame)
```

- [ ] **Step 3: Implement `_build_table`**

Add to the `ReviewModal` class:

```python
    def _build_table(self, parent):
        cols = ("idx", "point_id", "easting", "northing", "elevation", "description", "score", "page", "source", "action")
        self._tree = ttk.Treeview(parent, columns=cols, show="headings", height=8, selectmode="browse")

        col_widths = {
            "idx": 35, "point_id": 80, "easting": 90, "northing": 90,
            "elevation": 75, "description": 200, "score": 50, "page": 45,
            "source": 160, "action": 75,
        }
        headers = {
            "idx": "#", "point_id": "Point ID", "easting": "Easting",
            "northing": "Northing", "elevation": "Elev", "description": "Description",
            "score": "Score", "page": "Page", "source": "Source PDF", "action": "Action",
        }
        for col in cols:
            self._tree.heading(col, text=headers[col])
            self._tree.column(col, width=col_widths[col], minwidth=30, stretch=(col == "description"))

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for i, rec in enumerate(self._records):
            self._tree.insert("", "end", iid=str(i), values=(
                i + 1,
                rec.get("system_point_id") or rec.get("point") or "",
                rec.get("easting") or "",
                rec.get("northing") or "",
                rec.get("elevation") or "",
                (rec.get("description") or "")[:60],
                rec.get("confidence_score") or "",
                rec.get("source_page") or "",
                rec.get("source_pdf") or "",
                "",
            ))

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
```

- [ ] **Step 4: Implement `_build_pdf_viewer`**

Add to the `ReviewModal` class:

```python
    def _build_pdf_viewer(self, parent):
        zoom_bar = tk.Frame(parent)
        zoom_bar.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(zoom_bar, text="Zoom:").pack(side="left")
        tk.Button(zoom_bar, text="–", width=3, command=self._zoom_out).pack(side="left", padx=2)
        self._zoom_label = tk.Label(zoom_bar, text="200%", width=5)
        self._zoom_label.pack(side="left")
        tk.Button(zoom_bar, text="+", width=3, command=self._zoom_in).pack(side="left", padx=2)

        canvas_frame = tk.Frame(parent)
        canvas_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._canvas = tk.Canvas(canvas_frame, bg="#222")
        h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self._canvas.xview)
        v_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        h_scroll.pack(side="bottom", fill="x")
        v_scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

    def _zoom_in(self):
        self._zoom = min(self._zoom + 0.25, 5.0)
        self._zoom_label.config(text=f"{int(self._zoom * 100)}%")
        self._render_pdf_page()

    def _zoom_out(self):
        self._zoom = max(self._zoom - 0.25, 0.5)
        self._zoom_label.config(text=f"{int(self._zoom * 100)}%")
        self._render_pdf_page()
```

- [ ] **Step 5: Implement `_build_action_bar`**

Add to the `ReviewModal` class:

```python
    def _build_action_bar(self, parent):
        left = tk.Frame(parent)
        left.pack(side="left", fill="x", expand=True)

        tk.Label(left, text="Selected row action:", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 8))

        self._btn_accept = tk.Button(left, text="Accept", width=10, command=self._mark_accept)
        self._btn_accept.pack(side="left", padx=4)
        self._btn_skip = tk.Button(left, text="Skip", width=10, command=self._mark_skip)
        self._btn_skip.pack(side="left", padx=4)
        self._btn_edit = tk.Button(left, text="Edit Fields", width=10, command=self._start_edit)
        self._btn_edit.pack(side="left", padx=4)

        # Inline edit panel (hidden until edit mode)
        self._edit_frame = tk.Frame(parent, bd=1, relief=tk.GROOVE, padx=6, pady=4)
        tk.Label(self._edit_frame, text="Edit fields (press Enter to confirm):").pack(anchor="w")

        fields_row = tk.Frame(self._edit_frame)
        fields_row.pack(fill="x")

        self._edit_vars: dict[str, tk.StringVar] = {}
        for label, field in [("Easting", "easting"), ("Northing", "northing"), ("Elevation", "elevation"), ("Description", "description")]:
            tk.Label(fields_row, text=label + ":").pack(side="left", padx=(8, 2))
            var = tk.StringVar()
            self._edit_vars[field] = var
            entry = tk.Entry(fields_row, textvariable=var, width=18 if field == "description" else 12)
            entry.pack(side="left")
            entry.bind("<Return>", lambda e: self._confirm_edit())

        tk.Button(self._edit_frame, text="Confirm Edit", command=self._confirm_edit).pack(anchor="e", pady=(4, 0))

        # Finalize button (right side)
        self._finalize_btn = tk.Button(
            parent, text="Finalize & Export", width=18, height=2,
            bg="#2e7d32", fg="white", font=("Arial", 11, "bold"),
            state="disabled", command=self._finalize,
        )
        self._finalize_btn.pack(side="right", padx=8)

        self._status_label = tk.Label(parent, text="0 / 0 reviewed", fg="gray")
        self._status_label.pack(side="right", padx=8)
```

- [ ] **Step 6: Implement row selection, action marking, and edit confirmation**

Add to the `ReviewModal` class:

```python
    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx != self._current_index:
            self._edit_frame.pack_forget()
        self._current_index = idx
        self._render_pdf_page()

    def _select_row(self, idx: int):
        self._tree.selection_set(str(idx))
        self._tree.focus(str(idx))
        self._tree.see(str(idx))
        self._current_index = idx
        self._render_pdf_page()

    def _mark_accept(self):
        if self._current_index is None:
            return
        self._actions[self._current_index] = "accepted"
        self._edit_frame.pack_forget()
        self._refresh_row(self._current_index)
        self._update_status()

    def _mark_skip(self):
        if self._current_index is None:
            return
        self._actions[self._current_index] = "skipped"
        self._edit_frame.pack_forget()
        self._refresh_row(self._current_index)
        self._update_status()

    def _start_edit(self):
        if self._current_index is None:
            return
        rec = self._records[self._current_index]
        for field, var in self._edit_vars.items():
            existing = (self._edits.get(self._current_index) or {}).get(field) or rec.get(field) or ""
            var.set(existing)
        self._edit_frame.pack(fill="x", pady=(4, 0))

    def _confirm_edit(self):
        if self._current_index is None:
            return
        edits = {field: var.get().strip() for field, var in self._edit_vars.items() if var.get().strip()}
        if edits:
            self._edits[self._current_index] = edits
        self._actions[self._current_index] = "edited"
        self._edit_frame.pack_forget()
        self._refresh_row(self._current_index)
        self._update_status()

    def _refresh_row(self, idx: int):
        action = self._actions.get(idx, "")
        label = {"accepted": "✓ Accept", "skipped": "✗ Skip", "edited": "✎ Edited"}.get(action, "")
        current_values = list(self._tree.item(str(idx), "values"))
        current_values[-1] = label
        self._tree.item(str(idx), values=current_values)
        if action == "skipped":
            self._tree.item(str(idx), tags=("skipped",))
            self._tree.tag_configure("skipped", foreground="gray")
        elif action in ("accepted", "edited"):
            self._tree.item(str(idx), tags=("accepted",))
            self._tree.tag_configure("accepted", foreground="#2e7d32")

    def _update_status(self):
        reviewed = len(self._actions)
        total = len(self._records)
        self._status_label.config(text=f"{reviewed} / {total} reviewed")
        if reviewed == total:
            self._finalize_btn.config(state="normal")

    def _finalize(self):
        self.window.destroy()
```

- [ ] **Step 7: Implement `_render_pdf_page`**

Add to the `ReviewModal` class:

```python
    def _render_pdf_page(self):
        if self._current_index is None:
            return
        rec = self._records[self._current_index]
        source_pdf = rec.get("source_pdf") or ""
        pdf_path = self._pdf_path_map.get(source_pdf)
        if not pdf_path or not Path(pdf_path).exists():
            self._canvas.delete("all")
            self._canvas.create_text(20, 20, anchor="nw", fill="white",
                                     text=f"PDF not found: {source_pdf}")
            return

        page_num = int(rec.get("source_page") or 1)
        page_index = max(0, page_num - 1)

        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(page_index)
            mat = fitz.Matrix(self._zoom, self._zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            doc.close()

            b64 = base64.b64encode(png_bytes).decode("ascii")
            photo = tk.PhotoImage(data=b64)
            self._photo = photo
            self._canvas.delete("all")
            self._canvas.create_image(0, 0, anchor="nw", image=photo)
            self._canvas.configure(scrollregion=(0, 0, photo.width(), photo.height()))
        except Exception as exc:
            self._canvas.delete("all")
            self._canvas.create_text(20, 20, anchor="nw", fill="white",
                                     text=f"Failed to render page {page_num}: {exc}")
```

- [ ] **Step 8: Manual smoke test**

Run a quick manual check that the modal imports without error:

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder
python -c "import review_modal; print('OK')"
```

Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add review_modal.py
git commit -m "feat: add ReviewModal Tkinter class"
```

---

## Task 4: `_split_low_confidence` + `batch.py` review queue + ArcGIS output

**Files:**
- Modify: `batch.py`
- Create: `tests/test_batch_split.py`

- [ ] **Step 1: Write failing test for `_split_low_confidence`**

Create `tests/test_batch_split.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from batch import _split_low_confidence


def test_splits_correctly():
    records = [
        {"system_point_id": "CP1", "confidence_level": "low"},
        {"system_point_id": "CP2", "confidence_level": "high"},
        {"system_point_id": "CP3", "confidence_level": "medium"},
        {"system_point_id": "CP4", "confidence_level": "low"},
    ]
    low, other = _split_low_confidence(records)
    assert [r["system_point_id"] for r in low] == ["CP1", "CP4"]
    assert [r["system_point_id"] for r in other] == ["CP2", "CP3"]


def test_all_high_returns_empty_low():
    records = [{"confidence_level": "high"}, {"confidence_level": "medium"}]
    low, other = _split_low_confidence(records)
    assert low == []
    assert len(other) == 2


def test_missing_confidence_level_goes_to_other():
    records = [{"confidence_level": ""}, {"confidence_level": None}]
    low, other = _split_low_confidence(records)
    assert low == []
    assert len(other) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_batch_split.py -v
```

Expected: `ImportError` — `_split_low_confidence` does not exist yet.

- [ ] **Step 3: Add `_split_low_confidence` to `batch.py`**

Add after the `_split_flags` helper near the top of `batch.py`:

```python
def _split_low_confidence(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (low_conf, other). Does not mutate records."""
    low_conf = [r for r in records if r.get("confidence_level") == "low"]
    other = [r for r in records if r.get("confidence_level") != "low"]
    return low_conf, other
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_batch_split.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Add `ARCGIS_CSV_NAME` constant and import `write_arcgis_csv`**

At the top of `batch.py`, add to the existing constants block:

```python
ARCGIS_CSV_NAME = "arcgis_points.csv"
```

Change the import line that currently reads:
```python
from control_point import run_control_point_pipeline, write_csv
```
to:
```python
from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_records, flag_uncertain_duplicates, write_arcgis_csv
```

The existing `from output_control import deduplicate_records, flag_uncertain_duplicates` line should be merged with the new import.

- [ ] **Step 6: Refactor `_run_pdf_list` to add review queue support and write ArcGIS CSV**

The function signature changes to:

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
):
```

Replace the combined-output block that currently starts with:
```python
combined_csv_path = output_folder / "all_control_points.csv"
clean_csv_path = output_folder / CLEAN_CSV_NAME
review_csv_path = output_folder / REVIEW_CSV_NAME
if tee_log:
    tee_log("")
    tee_log("Combining results into one CSV…")
# Deduplicate across PDFs before writing combined output.
all_valid_records, cross_removed = deduplicate_records(...)
all_valid_records = flag_uncertain_duplicates(...)
write_csv(all_valid_records, str(combined_csv_path))

clean_records, review_records = split_clean_vs_review(all_valid_records)
write_csv(clean_records, str(clean_csv_path))
write_csv(review_records, str(review_csv_path))
```

with this new block:

```python
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

    # --- Review gate ---
    low_conf, other_records = _split_low_confidence(all_valid_records)

    if low_conf and review_request_q is not None and review_result_q is not None:
        if tee_log:
            tee_log(f"  Found {len(low_conf)} low-confidence record(s) — sending to review modal…")
        pdf_path_map = {p.name: str(p) for p in pdf_paths}
        review_request_q.put({"low_conf": low_conf, "pdf_path_map": pdf_path_map})
        modal_result = review_result_q.get()
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
```

Update the `return` dict at the end of `_run_pdf_list` to add:

```python
        "arcgis_csv": str(arcgis_csv_path),
```

- [ ] **Step 7: Refactor `run_single` to call `_run_pdf_list`**

Replace the entire `run_single` function body with:

```python
def run_single(pdf_path, output_folder, log=None, progress=None,
               review_request_q=None, review_result_q=None):
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
    )
```

- [ ] **Step 8: Add `review_request_q` / `review_result_q` params to all public functions**

Update these signatures (add `review_request_q=None, review_result_q=None` and thread them through):

`run_batch`:
```python
def run_batch(input_folder, output_folder, log=None, progress=None,
              review_request_q=None, review_result_q=None):
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
    )
```

`run_multi`:
```python
def run_multi(pdf_paths: list[str | Path], output_folder, log=None, progress=None,
              review_request_q=None, review_result_q=None):
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
    )
```

`run_batch_folder` — add params and thread them into `run_batch`:
```python
def run_batch_folder(input_folder, output_folder, log=None, progress=None,
                     review_request_q=None, review_result_q=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    result = run_batch(input_folder, output_folder, log=log, progress=progress,
                       review_request_q=review_request_q, review_result_q=review_result_q)
    _write_manifest(output_folder, {
        # ... same dict as before, plus:
        "files": {
            "combined_csv": Path(result["combined_csv"]).name,
            "clean_csv": Path(result["clean_csv"]).name,
            "needs_review_csv": Path(result["review_csv"]).name,
            "arcgis_csv": ARCGIS_CSV_NAME,
            "log_txt": Path(result.get("log_txt") or LOG_TXT_NAME).name,
            "summary_txt": Path(result.get("summary_txt") or SUMMARY_TXT_NAME).name,
            "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
        },
        # all other keys unchanged
    })
    return {**result, "delivery_path": str(output_folder)}
```

`run_single_folder` — same change: add `review_request_q=None, review_result_q=None` to the signature, pass them into `run_single(...)`, and add `"arcgis_csv": ARCGIS_CSV_NAME` to the manifest `"files"` dict.

`run_batch_packaged` — same change: add params to signature, pass them into `run_batch(...)`, add `"arcgis_csv": ARCGIS_CSV_NAME` to the manifest `"files"` dict.

`run_single_packaged` — same change: add params to signature, pass them into `run_single(...)`, add `"arcgis_csv": ARCGIS_CSV_NAME` to the manifest `"files"` dict.

`run_multi_packaged` — same change: add params to signature, pass them into `run_multi(...)`, add `"arcgis_csv": ARCGIS_CSV_NAME` to the manifest `"files"` dict.

- [ ] **Step 9: Update `_write_summary` to include ArcGIS CSV**

In `_write_summary`, find the "Outputs:" lines and add:

```python
f"- {ARCGIS_CSV_NAME}",
```

after the combined CSV line.

- [ ] **Step 10: Update `_write_manifest` calls to include ArcGIS CSV**

In each of the four `_write_manifest(...)` calls (inside `run_batch_folder`, `run_single_folder`, `run_batch_packaged`, `run_single_packaged`, `run_multi_packaged`), add to the `"files"` dict:

```python
"arcgis_csv": ARCGIS_CSV_NAME,
```

- [ ] **Step 11: Run the existing tests to verify nothing broke**

```
pytest tests/ -v
```

Expected: all existing tests PASSED, plus the new ones.

- [ ] **Step 12: Commit**

```bash
git add batch.py
git commit -m "feat: add review queue gate and arcgis_points.csv to batch pipeline"
```

---

## Task 5: Wire `gui.py` for review modal

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add `queue` import and queue state to `__init__`**

At the top of `gui.py`, add after the existing imports:

```python
import queue
from review_modal import ReviewModal
```

In `ControlPointApp.__init__`, add after `self._progress_total = 0`:

```python
        self._review_request_q: queue.Queue = queue.Queue()
        self._review_result_q: queue.Queue = queue.Queue()
        self._review_polling: bool = False
```

- [ ] **Step 2: Add `_start_review_polling`, `_stop_review_polling`, `_poll_review_queue`, `_show_review_modal`**

Add these methods to `ControlPointApp`:

```python
    def _start_review_polling(self):
        self._review_polling = True
        self._poll_review_queue()

    def _stop_review_polling(self):
        self._review_polling = False

    def _poll_review_queue(self):
        if not self._review_polling:
            return
        try:
            msg = self._review_request_q.get_nowait()
            self._show_review_modal(msg)
        except queue.Empty:
            self.root.after(100, self._poll_review_queue)

    def _show_review_modal(self, msg: dict):
        modal = ReviewModal(self.root, msg["low_conf"], msg["pdf_path_map"])
        self.root.wait_window(modal.window)
        result = modal.get_results()
        self._review_result_q.put(result)
        self.root.after(100, self._poll_review_queue)
```

- [ ] **Step 3: Reset queues and start polling in `run_extraction`**

In `run_extraction`, after `self._reset_progress()` and before `thread = threading.Thread(...)`, add:

```python
        self._review_request_q = queue.Queue()
        self._review_result_q = queue.Queue()
        self._start_review_polling()
```

- [ ] **Step 4: Stop polling in the `finally` block of `run_extraction_thread`**

In `run_extraction_thread`, the `finally` block currently reads:

```python
        finally:
            self.run_button.config(state="normal")
```

Change it to:

```python
        finally:
            self.root.after(0, self._stop_review_polling)
            self.run_button.config(state="normal")
```

- [ ] **Step 5: Pass queues into all batch runner calls in `run_extraction_thread`**

In `run_extraction_thread`, define a shared kwargs dict and use it for all six runner calls:

```python
    def run_extraction_thread(self, input_value, output_destination):
        try:
            log = self.log_threadsafe
            progress = lambda payload: self.root.after(0, lambda: self._update_progress_ui(payload))
            rkw = {
                "log": log,
                "progress": progress,
                "review_request_q": self._review_request_q,
                "review_result_q": self._review_result_q,
            }

            if self.output_mode.get() == "folder":
                if self.input_mode.get() == "single":
                    result = run_single_folder(input_value, output_destination, **rkw)
                elif self.input_mode.get() == "multiple":
                    result = run_multi(self._selected_pdfs, output_destination, **rkw)
                else:
                    result = run_batch_folder(input_value, output_destination, **rkw)
            else:
                if self.input_mode.get() == "single":
                    result = run_single_packaged(input_value, output_destination, **rkw)
                elif self.input_mode.get() == "multiple":
                    result = run_multi_packaged(self._selected_pdfs, output_destination, **rkw)
                else:
                    result = run_batch_packaged(input_value, output_destination, **rkw)

            # ... rest of logging and messagebox unchanged ...
```

- [ ] **Step 6: Update the completion `messagebox` to mention ArcGIS CSV**

In `run_extraction_thread`, find the `messagebox.showinfo(...)` call and update the message:

```python
            messagebox.showinfo(
                "Done",
                "Extraction complete.\n\n"
                f"Total records: {result['total_records']}\n"
                f"Clean export: {result.get('clean_records', '—')}\n"
                f"Needs review: {result.get('review_records', '—')}\n"
                f"ArcGIS CSV: arcgis_points.csv"
            )
```

- [ ] **Step 7: Run all tests**

```
pytest tests/ -v
```

Expected: all tests PASSED

- [ ] **Step 8: Smoke test the GUI**

```
cd /Users/wilsongomez/Documents/Real_Projects/controlPointFinder
python gui.py
```

- Load a PDF that has control points.
- Click "Run Extraction."
- If low-confidence records exist: confirm the review modal appears, test Accept / Skip / Edit on at least one row, and click Finalize.
- Confirm output folder contains `arcgis_points.csv`.
- Open `arcgis_points.csv` and verify it has columns: `point_id, x, y, elevation, description, source_pdf`.

- [ ] **Step 9: Commit**

```bash
git add gui.py
git commit -m "feat: wire review modal into GUI extraction flow"
```
