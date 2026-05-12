# Design: UI Redesign

**Date:** 2026-05-12
**Status:** Approved

---

## Problem

The current UI uses raw default Tkinter styling — plain gray background, no visual hierarchy between buttons, and a two-pane layout that wastes the right pane whenever the preview feature is not in use. The result feels unpolished and makes the workflow harder to read at a glance.

Two primary issues:
1. **Visual rawness** — default gray Tkinter, no color scheme, no spacing rhythm
2. **Flat button hierarchy** — Run Extraction, Browse, Open Output Folder, and Preview Flagged Rows all look the same weight

---

## Design Decisions

### Color Scheme — Warm Neutral

| Role | Color | Usage |
|---|---|---|
| Page background | `#fafaf8` | Window and tab content background |
| Card surface | `#ffffff` | Input, Output, Progress, Log cards |
| Card border | `#e7e5e4` | Card outlines |
| Accent (primary) | `#d97706` | Run Extraction button, active tab underline, progress bar, drop zone border, active pill |
| Accent light | `#fef3c7` | Active pill background, active flagged row highlight |
| Accent dark text | `#92400e` | Text on accent-light backgrounds |
| Body text | `#1c1917` | Primary labels |
| Secondary text | `#78716c` | Section labels, secondary info |
| Muted text | `#a8a29e` | Placeholder text, disabled state |
| Sidebar/dark surface | `#44403c` | PDF page preview background in Review tab |

**Implementation:** Use `ttk.Style` with the `clam` theme as the base (cross-platform, most styleable). Override colors via `style.configure(...)` and `style.map(...)`. Standard `tk` widgets use `bg=`/`fg=` kwargs.

---

## Layout — Tabbed (Extract / Review)

Replace the current fixed two-pane `PanedWindow` with a `ttk.Notebook` containing two tabs. The window size stays `1200x700`.

### Tab bar

- Two tabs: **Extract** and **Review**
- Active tab: amber bottom border (`#d97706`), bold amber text (`#92400e`)
- Inactive tab: muted text (`#a8a29e`)

---

## Tab 1 — Extract

### Input card

A white card (`bg=#ffffff`, `highlightbackground=#e7e5e4`, `highlightthickness=1`) implemented as a `tk.Frame` with explicit border color. Tkinter does not support border-radius natively; corners will be square. Contains:

1. **Drag-and-drop zone** — dashed amber border (`#d97706`), `#fffbeb` background, centered icon + label "Drop folder or PDF(s) here" with "or use Browse below" subtext. On drop, auto-detect mode:
   - Dropped item is a directory → set mode to `folder`
   - Dropped item is a single `.pdf` → set mode to `single`
   - Dropped multiple `.pdf` files → set mode to `multiple`
   Populate the path entry and update mode pill selection.
   **Implementation:** Use `tkinterdnd2` library for drag-and-drop support on both Mac and Windows.

2. **Mode pills** (Folder / Single PDF / Multiple PDFs) — pill-style radio buttons. Active pill: `#fef3c7` background, `#d97706` border, `#92400e` bold text. Inactive: white background, `#d4d4d4` border, `#78716c` text. Implemented as styled `tk.Radiobutton` widgets.

3. **Path entry + Browse button** — entry fills available width, Browse is an outlined secondary button.

### Output card

Same card style. Contains:
- Mode pills: ZIP / Folder
- Path entry + Browse button

### Action row

- **Run Extraction** (primary): `#d97706` background, white bold text, `height=2`, subtle shadow effect via relief. Full amber when enabled; muted when disabled.
- **Open Output Folder** (secondary): white background, `#d4d4d4` border, `#78716c` text, disabled until extraction completes.

### Progress card

White card containing:
- Label row: "Progress" (bold) left, "X / Y PDFs" right
- `ttk.Progressbar` styled amber (`#d97706` trough color)
- Current PDF label below bar (`#a8a29e` muted text)

### Log card

White card with "LOG" section label. `scrolledtext.ScrolledText` inside with `bg=#fafaf8`, `fg=#57534e`, monospace font (`Courier` or `Consolas`).

---

## Tab 2 — Review

### Tab header action

"Preview Flagged Rows…" amber button sits in the tab bar row on the right side (always visible when Review tab is active).

### Flagged records list

White card with "FLAGGED RECORDS — {filename}" label. Records rendered as styled rows:
- **Active row**: `#fef3c7` background, amber border, bold amber point ID
- **Inactive row**: `#f5f5f4` background, stone border
- Each row shows: Point ID | Page number | Flag text (inline, same row)
- Click a row to update the table and PDF views below

### Side-by-side panel

Two equal-width panels below the records list (replacing the current vertical `PanedWindow`):

**Left — Extracted Table**: White card. Monospace font, column headers in muted gray, active record row highlighted amber. Shows page number and confidence score in the card header.

**Right — PDF Page Preview**: Dark card (`#44403c` background). PDF page rendered via `fitz`. Zoom controls (–, %, +) centered below the canvas.

---

## Button Hierarchy Summary

| Button | Style |
|---|---|
| Run Extraction | Primary — amber fill, white bold text |
| Preview Flagged Rows… | Primary — amber fill, white bold text |
| Browse (×2) | Secondary — white fill, stone border, warm text |
| Open Output Folder | Secondary — disabled until output exists |

---

## Dependencies

- `tkinterdnd2` — drag-and-drop support (add to `pip install` in workflow and requirements)
- All other dependencies already present

---

## Files Affected

| File | Change |
|---|---|
| `gui.py` | Full UI rebuild: ttk theme setup, Notebook tabs, restyled widgets, drag-and-drop zone |
| `.github/workflows/build-windows.yml` | Add `tkinterdnd2` to pip install step |

---

## Out of Scope

- No changes to extraction logic, batch processing, confidence scoring, or output formats
- No changes to `review_modal.py` (the full-screen review modal is separate from this panel)
- No splash screen or loading animation
- No dark mode toggle
