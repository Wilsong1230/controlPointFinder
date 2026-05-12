# Startup Performance Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate slow app startup by deferring heavy imports in `gui.py` and `review_modal.py`, and switching the Windows build from `--onefile` to `--onedir`.

**Architecture:** Two independent changes — (1) move 7 heavy top-level imports in `gui.py` inside the methods that first use them, move `import fitz` in `review_modal.py` inside `_render_pdf_page`, and (2) update `build-windows.yml` to use `--onedir` with a zip step. No pipeline logic changes.

**Tech Stack:** Python / Tkinter, PyInstaller, GitHub Actions (PowerShell zip step)

---

## File Structure

| File | Change |
|---|---|
| `gui.py` | Remove lines 23–30 (7 heavy imports); add local imports inside `preview_flagged_rows_thread` and `_render_preview_index` |
| `review_modal.py` | Remove line 9 (`import fitz`); add `import fitz` inside `_render_pdf_page` |
| `.github/workflows/build-windows.yml` | `--onefile` → `--onedir`; replace Upload step with Zip + Upload steps |

---

### Task 1: Defer heavy imports in `review_modal.py`

**Files:**
- Modify: `review_modal.py:9` (remove module-level `import fitz`)
- Modify: `review_modal.py:284` (`_render_pdf_page` — add local import)

There are no pure-function tests to write for this task — it's a structural refactor with no behavior change. Verify with a smoke test instead (Step 3).

- [ ] **Step 1: Remove `import fitz` from module top**

Open `review_modal.py`. The current top of the file (lines 1–10) looks like:

```python
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import ttk

import fitz
```

Change it to:

```python
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import ttk
```

- [ ] **Step 2: Add `import fitz` inside `_render_pdf_page`**

Find `_render_pdf_page` (around line 284). The method currently starts:

```python
    def _render_pdf_page(self):
        if self._current_index is None:
            return
        rec = self._records[self._current_index]
```

Change it to:

```python
    def _render_pdf_page(self):
        import fitz  # deferred: only needed when rendering PDF pages
        if self._current_index is None:
            return
        rec = self._records[self._current_index]
```

- [ ] **Step 3: Smoke-test that `review_modal` imports cleanly without fitz being loaded**

Run from the project root (with venv active):

```bash
.venv/bin/python -c "
import sys
from review_modal import ReviewModal, apply_modal_actions
assert 'fitz' not in sys.modules, 'fitz should not be imported at module load time'
print('OK: fitz not loaded at import time')
"
```

Expected output:
```
OK: fitz not loaded at import time
```

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass (same count as before this task).

- [ ] **Step 5: Commit**

```bash
git add review_modal.py
git commit -m "perf: defer fitz import in review_modal to _render_pdf_page"
```

---

### Task 2: Defer heavy imports in `gui.py`

**Files:**
- Modify: `gui.py:23–30` (remove 7 module-level imports)
- Modify: `gui.py:433` (`preview_flagged_rows_thread` — add local imports)
- Modify: `gui.py:510` (`_render_preview_index` — add local imports)

- [ ] **Step 1: Remove the 7 heavy imports from module top**

Open `gui.py`. Lines 23–30 currently read:

```python
import fitz
import pdfplumber

from control_point import extract_project_metadata, scanner, extract_control_points
from confidence import find_best_table
from data_validation import validate_and_normalize_records
from datum_standardization import standardize_records
from output_control import deduplicate_records, flag_uncertain_duplicates
```

Delete all 7 of those lines. The remaining module-level imports (lines 1–21) stay untouched:

```python
import threading
import queue
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import base64

from review_modal import ReviewModal

from batch import (
    run_batch_packaged,
    run_single_packaged,
    run_batch_folder,
    run_single_folder,
    run_multi,
    run_multi_packaged,
)

import os
import subprocess
```

- [ ] **Step 2: Add deferred imports at the top of `preview_flagged_rows_thread`**

Find `preview_flagged_rows_thread` (around line 433). It currently starts:

```python
    def preview_flagged_rows_thread(self, pdf_path: str):
        try:
            log = self.log_threadsafe
            log(f"Preview PDF: {Path(pdf_path).name}")
```

Change it to:

```python
    def preview_flagged_rows_thread(self, pdf_path: str):
        from control_point import extract_project_metadata, scanner, extract_control_points
        from confidence import find_best_table
        from data_validation import validate_and_normalize_records
        from datum_standardization import standardize_records
        from output_control import deduplicate_records, flag_uncertain_duplicates
        try:
            log = self.log_threadsafe
            log(f"Preview PDF: {Path(pdf_path).name}")
```

- [ ] **Step 3: Add deferred imports at the top of `_render_preview_index`**

Find `_render_preview_index` (around line 510). It currently starts:

```python
    def _render_preview_index(self, index: int):
        if not self._preview_pdf_path or not self._preview_flagged_records:
            return
```

Change it to:

```python
    def _render_preview_index(self, index: int):
        import fitz
        import pdfplumber
        from confidence import find_best_table
        if not self._preview_pdf_path or not self._preview_flagged_records:
            return
```

- [ ] **Step 4: Smoke-test that `gui` module imports without loading heavy libraries**

```bash
.venv/bin/python -c "
import sys
# Prevent tkinter from opening a display (import only, no Tk())
import tkinter
import gui
heavy = ['fitz', 'pdfplumber', 'control_point', 'confidence',
         'data_validation', 'datum_standardization']
loaded = [m for m in heavy if m in sys.modules]
if loaded:
    print('FAIL: loaded at import time:', loaded)
else:
    print('OK: none of the heavy modules loaded at import time')
"
```

Expected output:
```
OK: none of the heavy modules loaded at import time
```

> Note: if the above raises a display error on a headless machine, that is expected and unrelated — the assertion about `sys.modules` is what matters. Run on your local Mac where a display is available.

- [ ] **Step 5: Time startup improvement**

```bash
.venv/bin/python -c "
import time
t0 = time.time()
import threading, queue, os, subprocess, base64
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from review_modal import ReviewModal
from batch import run_batch_packaged, run_single_packaged, run_batch_folder, run_single_folder, run_multi, run_multi_packaged
print(f'All gui.py module-level imports: {time.time()-t0:.3f}s')
"
```

Expected: under 0.3s (down from ~0.6s before this change).

- [ ] **Step 6: Run the full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "perf: defer heavy imports in gui.py to first use"
```

---

### Task 3: Switch PyInstaller build to `--onedir`

**Files:**
- Modify: `.github/workflows/build-windows.yml`

No tests for this task — verify by reading the diff and confirming the YAML is valid.

- [ ] **Step 1: Update the workflow file**

Open `.github/workflows/build-windows.yml`. The current content is:

```yaml
name: Build Windows EXE

on:
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests pyproj pymupdf pdfplumber pyinstaller

      - name: Build EXE
        run: |
          pyinstaller --onefile --windowed --name ControlPointExtractor gui.py --hidden-import=requests --hidden-import=pyproj

      - name: Upload EXE
        uses: actions/upload-artifact@v4
        with:
          name: ControlPointExtractor-Windows
          path: dist/ControlPointExtractor.exe
```

Replace the entire file with:

```yaml
name: Build Windows EXE

on:
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests pyproj pymupdf pdfplumber pyinstaller

      - name: Build EXE
        run: |
          pyinstaller --onedir --windowed --name ControlPointExtractor gui.py --hidden-import=requests --hidden-import=pyproj

      - name: Zip output folder
        run: Compress-Archive -Path dist/ControlPointExtractor -DestinationPath dist/ControlPointExtractor.zip

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ControlPointExtractor-Windows
          path: dist/ControlPointExtractor.zip
```

- [ ] **Step 2: Verify the diff**

```bash
git diff .github/workflows/build-windows.yml
```

Confirm exactly three changes:
1. `--onefile` → `--onedir` in the Build EXE step
2. New "Zip output folder" step added after Build EXE
3. Upload path changed from `dist/ControlPointExtractor.exe` to `dist/ControlPointExtractor.zip`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/build-windows.yml
git commit -m "perf: switch pyinstaller to --onedir and zip artifact for fast startup"
```
