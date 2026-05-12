# Design: Startup Performance Fix

**Date:** 2026-05-12
**Status:** Approved

---

## Problem

App startup is slow on both `python gui.py` (Mac) and the Windows EXE. Two independent causes:

1. `gui.py` imports 8 heavy modules at module level (`fitz`, `pdfplumber`, `pyproj`, `control_point`, `confidence`, `data_validation`, `datum_standardization`, `output_control`, `review_modal`) that are not needed until the user triggers extraction or preview.
2. `build-windows.yml` uses PyInstaller `--onefile`, which bundles all native libraries into a single EXE that extracts itself to a temp directory on every launch. With PyMuPDF (full MuPDF C library) and PROJ (datum grid files), this extraction takes 30–60 seconds on a typical machine.

---

## Fix 1 — Deferred imports in `gui.py`

Move every import that is not needed at window creation time inside the method that first uses it.

### Imports to defer

| Import | Currently at | Move to |
|---|---|---|
| `fitz` | module top | `_render_preview_index` |
| `pdfplumber` | module top | `_render_preview_index` |
| `from control_point import ...` | module top | `preview_flagged_rows_thread` |
| `from confidence import ...` | module top | `preview_flagged_rows_thread` |
| `from data_validation import ...` | module top | `preview_flagged_rows_thread` |
| `from datum_standardization import ...` | module top | `preview_flagged_rows_thread` |
| `from output_control import ...` | module top | `preview_flagged_rows_thread` |

`review_modal.py` imports `fitz` at module level. That import moves inside `ReviewModal._render_pdf_page` where fitz is actually called.

### What stays at module top in `gui.py`

- `threading`, `queue`, `pathlib`, `tkinter.*`, `base64`, `os`, `subprocess` — stdlib, near-zero cost
- `from review_modal import ReviewModal` — the class itself is lightweight once fitz is deferred inside it
- `from batch import ...` — batch.py imports are already fast (no native libs at module level)

### Behavior after the change

The window appears immediately. On the first click of "Run Extraction" or "Preview Flagged Rows," the deferred imports execute once (~0.4s combined) and are cached by Python's module system for the rest of the session. All subsequent runs in the same session have zero import overhead.

---

## Fix 2 — PyInstaller `--onedir` in `build-windows.yml`

### Change

Replace `--onefile` with `--onedir` in the PyInstaller command.

**Before:**
```
pyinstaller --onefile --windowed --name ControlPointExtractor gui.py --hidden-import=requests --hidden-import=pyproj
```

**After:**
```
pyinstaller --onedir --windowed --name ControlPointExtractor gui.py --hidden-import=requests --hidden-import=pyproj
```

### Distribution

`--onedir` produces `dist/ControlPointExtractor/` — a folder containing the `.exe` and all dependency files pre-extracted. Add a zip step after the build so the GitHub Actions artifact is still a single downloadable file:

```yaml
- name: Zip output
  run: Compress-Archive -Path dist/ControlPointExtractor -DestinationPath dist/ControlPointExtractor.zip

- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: ControlPointExtractor-Windows
    path: dist/ControlPointExtractor.zip
```

Users unzip once, then double-click `ControlPointExtractor.exe` inside the folder. No extraction on every launch — startup is near-instant.

---

## Files Affected

| File | Change |
|---|---|
| `gui.py` | Remove 7 top-level imports; add local imports inside `preview_flagged_rows_thread` and `_render_preview_index` |
| `review_modal.py` | Move `import fitz` from module top to inside `_render_pdf_page` |
| `.github/workflows/build-windows.yml` | `--onefile` → `--onedir`; add zip + updated upload step |

---

## Out of Scope

- No changes to extraction logic, confidence scoring, datum conversion, or any pipeline behavior.
- No changes to the GUI layout or user-facing behavior.
- No splash screen or loading indicator.
