# Review Modal Improvements — Design Spec
_Date: 2026-05-13_

## Scope

Improvements to `ReviewModal` in `review_modal.py` only. The Preview tab in the main GUI remains read-only; no reviewing or editing happens there.

---

## Feature 1 — Column Header Right-Click Menu

### Trigger
Right-clicking any column header in the treeview opens a `tk.Menu` anchored at the cursor position.

### Menu items

| Column type | Items shown |
|---|---|
| Editable field (point_id, easting, northing, elevation, description) | Swap with…, Fill all rows…, Clear all |
| Read-only column (score, page, source, action, idx) | _(disabled label)_ "Not editable" |

### Swap with…
- Opens a cascaded submenu listing all other editable fields.
- Selecting a target field swaps the values of the two fields across **all** records in `self._records`.
- Operates on data (values move between fields), not display labels — the export CSV reflects the corrected mapping.
- After swap: full table refresh via `_reload_table()`.

### Fill all rows…
- Calls `tk.simpledialog.askstring` with a prompt labelled with the column name.
- Writes the entered string into that field on every record in `self._records`.
- Empty string submission is treated as a no-op (user cancelled or typed nothing).
- After fill: full table refresh.

### Clear all
- Sets the target field to `""` on every record.
- After clear: full table refresh.

### Table refresh helper
A new `_reload_table()` method clears all treeview rows and re-inserts from `self._records`, preserving existing `self._actions` labels (✓/✗/✎) in the action column.

### Binding
`self._tree.heading(col, command=...)` cannot coexist with a right-click binding on headings. Instead, bind `<Button-2>` (macOS) and `<Button-3>` (Windows/Linux) on the `ttk.Treeview` widget itself, then use `self._tree.identify_region(event.x, event.y)` to confirm the click landed on `"heading"` and `self._tree.identify_column(event.x)` to get the column id before showing the menu.

---

## Feature 2 — Auto-Advance After Action

After any of accept, skip, or confirm-edit:
1. Find the next row index after the current one that has no entry in `self._actions`.
2. If found, call `_select_row(next_idx)`.
3. If none found (all reviewed), stay on the current row.

Implemented as a small `_advance_to_next_unreviewed()` helper called at the end of `_mark_accept`, `_mark_skip`, and `_confirm_edit`.

---

## Feature 3 — Keyboard Shortcuts

Bound on `self.window` (the `Toplevel`) so they fire when the modal has focus.

| Key | Action |
|---|---|
| `a` / `A` | Accept current row |
| `s` / `S` | Skip current row |
| `e` / `E` | Open edit panel for current row |
| `↓` | Move selection to next row |
| `↑` | Move selection to previous row |
| `Enter` | Confirm edit (already exists) |

Bindings are suppressed when a `tk.Entry` widget has focus, so typing inside the edit fields doesn't trigger row actions. Achieved by checking `isinstance(self.window.focus_get(), tk.Entry)` at the top of each handler.

---

## Feature 4 — "Accept All Remaining" Button

Added to the action bar (left side, after the existing Skip button).

- Label: `"Accept All Remaining"`
- On click: iterates all indices not present in `self._actions`, sets each to `"accepted"`, calls `_refresh_row(idx)` for each, then calls `_update_status()`.
- After: `_finalize_btn` becomes enabled (all rows reviewed), no auto-advance needed.

---

## Files Changed

| File | Changes |
|---|---|
| `review_modal.py` | All changes. No other files touched. |

---

## Out of Scope

- Preview tab changes (read-only, no review actions)
- Undo/redo
- Sorting or filtering the review table
- Persisting column swaps across sessions
