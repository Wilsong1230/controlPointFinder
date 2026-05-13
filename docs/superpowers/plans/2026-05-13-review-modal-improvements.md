# Review Modal Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add column swap/fill/clear via right-click header menu, auto-advance after actions, keyboard shortcuts, and "Accept All Remaining" button to `ReviewModal`.

**Architecture:** All changes are confined to `review_modal.py`. Pure data-manipulation functions are extracted at module level for testability; GUI methods call these functions and refresh the treeview via a new `_reload_table()` helper.

**Tech Stack:** Python 3.14, tkinter/ttk, pytest

---

## File Map

| File | What changes |
|---|---|
| `review_modal.py` | New module-level constants + 4 pure functions; new methods on `ReviewModal`; bindings wired in `_build_table` and `_build_action_bar` |
| `tests/test_review_modal_helpers.py` | New test file for the four pure functions |

---

## Task 1: Module-level constants and pure data functions

**Files:**
- Modify: `review_modal.py` (top of file, after imports)
- Create: `tests/test_review_modal_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_review_modal_helpers.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from review_modal import swap_column_data, fill_column_data, clear_column_data, next_unreviewed


def _rec(**kwargs):
    base = {"easting": "100.0", "northing": "200.0", "elevation": "10.0", "description": "TEST"}
    base.update(kwargs)
    return base


# --- swap_column_data ---

def test_swap_exchanges_values():
    records = [_rec(easting="1.0", northing="2.0"), _rec(easting="3.0", northing="4.0")]
    result = swap_column_data(records, "easting", "northing")
    assert result[0]["easting"] == "2.0"
    assert result[0]["northing"] == "1.0"
    assert result[1]["easting"] == "4.0"
    assert result[1]["northing"] == "3.0"


def test_swap_does_not_mutate_input():
    records = [_rec(easting="1.0", northing="2.0")]
    swap_column_data(records, "easting", "northing")
    assert records[0]["easting"] == "1.0"


def test_swap_preserves_other_fields():
    records = [_rec(easting="1.0", northing="2.0", elevation="5.0")]
    result = swap_column_data(records, "easting", "northing")
    assert result[0]["elevation"] == "5.0"


def test_swap_handles_missing_field():
    records = [{"easting": "1.0"}]
    result = swap_column_data(records, "easting", "northing")
    assert result[0]["easting"] == ""
    assert result[0]["northing"] == "1.0"


# --- fill_column_data ---

def test_fill_sets_value_on_all_rows():
    records = [_rec(elevation="1.0"), _rec(elevation="2.0")]
    result = fill_column_data(records, "elevation", "99.9")
    assert result[0]["elevation"] == "99.9"
    assert result[1]["elevation"] == "99.9"


def test_fill_does_not_mutate_input():
    records = [_rec(elevation="1.0")]
    fill_column_data(records, "elevation", "99.9")
    assert records[0]["elevation"] == "1.0"


def test_fill_preserves_other_fields():
    records = [_rec(easting="7.0", elevation="1.0")]
    result = fill_column_data(records, "elevation", "99.9")
    assert result[0]["easting"] == "7.0"


# --- clear_column_data ---

def test_clear_sets_empty_string_on_all_rows():
    records = [_rec(description="A"), _rec(description="B")]
    result = clear_column_data(records, "description")
    assert result[0]["description"] == ""
    assert result[1]["description"] == ""


def test_clear_does_not_mutate_input():
    records = [_rec(description="A")]
    clear_column_data(records, "description")
    assert records[0]["description"] == "A"


# --- next_unreviewed ---

def test_next_unreviewed_finds_first_gap():
    assert next_unreviewed(actions={0: "accepted"}, total=3, current=0) == 1


def test_next_unreviewed_skips_reviewed():
    assert next_unreviewed(actions={0: "accepted", 1: "skipped"}, total=4, current=0) == 2


def test_next_unreviewed_returns_none_when_all_done():
    assert next_unreviewed(actions={0: "accepted", 1: "skipped", 2: "accepted"}, total=3, current=0) is None


def test_next_unreviewed_returns_none_at_last_row():
    assert next_unreviewed(actions={}, total=3, current=2) is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_review_modal_helpers.py -v
```
Expected: `ImportError` — `swap_column_data` etc. not yet defined.

- [ ] **Step 3: Add constants and pure functions to `review_modal.py`**

Insert after the existing imports (after `from tkinter import ttk`) and before the `apply_modal_actions` function:

```python
_COLS = (
    "idx", "point_id", "easting", "northing", "elevation",
    "description", "score", "page", "source", "action",
)
_EDITABLE_FIELDS = ("easting", "northing", "elevation", "description")
_FIELD_LABELS = {
    "easting": "Easting",
    "northing": "Northing",
    "elevation": "Elevation",
    "description": "Description",
}


def swap_column_data(records: list[dict], field_a: str, field_b: str) -> list[dict]:
    result = []
    for rec in records:
        r = dict(rec)
        r[field_a] = rec.get(field_b, "")
        r[field_b] = rec.get(field_a, "")
        result.append(r)
    return result


def fill_column_data(records: list[dict], field: str, value: str) -> list[dict]:
    return [{**rec, field: value} for rec in records]


def clear_column_data(records: list[dict], field: str) -> list[dict]:
    return [{**rec, field: ""} for rec in records]


def next_unreviewed(actions: dict, total: int, current: int) -> int | None:
    for i in range(current + 1, total):
        if i not in actions:
            return i
    return None
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/test_review_modal_helpers.py -v
```
Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add review_modal.py tests/test_review_modal_helpers.py
git commit -m "feat: add pure column-data helper functions with tests"
```

---

## Task 2: `_reload_table()` method

**Files:**
- Modify: `review_modal.py` — add `_reload_table` method to `ReviewModal`

- [ ] **Step 1: Add `_reload_table` to `ReviewModal`**

Add after the `_build_table` method (around line 130):

```python
def _reload_table(self):
    for iid in self._tree.get_children():
        self._tree.delete(iid)
    action_labels = {"accepted": "✓ Accept", "skipped": "✗ Skip", "edited": "✎ Edited"}
    for i, rec in enumerate(self._records):
        action = self._actions.get(i, "")
        label = action_labels.get(action, "")
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
            label,
        ))
        if action == "skipped":
            self._tree.item(str(i), tags=("skipped",))
            self._tree.tag_configure("skipped", foreground="gray")
        elif action in ("accepted", "edited"):
            self._tree.item(str(i), tags=("accepted",))
            self._tree.tag_configure("accepted", foreground="#2e7d32")
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```
pytest tests/ -v
```
Expected: all existing tests still PASS.

- [ ] **Step 3: Commit**

```bash
git add review_modal.py
git commit -m "feat: add _reload_table helper to ReviewModal"
```

---

## Task 3: Auto-advance after action + keyboard shortcuts

**Files:**
- Modify: `review_modal.py` — add `_advance_to_next_unreviewed` and `_on_nav_key`, wire into existing action methods and `_build_table`

- [ ] **Step 1: Add `_advance_to_next_unreviewed` method**

Add after `_reload_table`:

```python
def _advance_to_next_unreviewed(self):
    if self._current_index is None:
        return
    idx = next_unreviewed(self._actions, len(self._records), self._current_index)
    if idx is not None:
        self._select_row(idx)
```

- [ ] **Step 2: Wire auto-advance into `_mark_accept`, `_mark_skip`, and `_confirm_edit`**

In `_mark_accept`, add one line at the end:

```python
def _mark_accept(self):
    if self._current_index is None:
        return
    self._actions[self._current_index] = "accepted"
    self._edit_frame.pack_forget()
    self._refresh_row(self._current_index)
    self._update_status()
    self._advance_to_next_unreviewed()
```

In `_mark_skip`, add one line at the end:

```python
def _mark_skip(self):
    if self._current_index is None:
        return
    self._actions[self._current_index] = "skipped"
    self._edit_frame.pack_forget()
    self._refresh_row(self._current_index)
    self._update_status()
    self._advance_to_next_unreviewed()
```

In `_confirm_edit`, add one line at the end:

```python
def _confirm_edit(self):
    if self._current_index is None:
        return
    edits = {field: var.get().strip() for field, var in self._edit_vars.items() if var.get().strip()}
    if edits:
        self._edits[self._current_index] = edits
        self._actions[self._current_index] = "edited"
    else:
        self._actions[self._current_index] = "accepted"
    self._edit_frame.pack_forget()
    self._refresh_row(self._current_index)
    self._update_status()
    self._advance_to_next_unreviewed()
```

- [ ] **Step 3: Add `_on_nav_key` method and keyboard bindings in `_build_table`**

Add the method after `_advance_to_next_unreviewed`:

```python
def _on_nav_key(self, event):
    if self._current_index is None:
        return "break"
    if event.keysym == "Down":
        target = min(self._current_index + 1, len(self._records) - 1)
    else:
        target = max(self._current_index - 1, 0)
    self._select_row(target)
    return "break"
```

At the end of `_build_table` (after the `self._tree.bind("<<TreeviewSelect>>", ...)` line), add:

```python
self._tree.bind("<KeyPress-a>", lambda e: self._mark_accept())
self._tree.bind("<KeyPress-A>", lambda e: self._mark_accept())
self._tree.bind("<KeyPress-s>", lambda e: self._mark_skip())
self._tree.bind("<KeyPress-S>", lambda e: self._mark_skip())
self._tree.bind("<KeyPress-e>", lambda e: self._start_edit())
self._tree.bind("<KeyPress-E>", lambda e: self._start_edit())
self._tree.bind("<Down>", self._on_nav_key)
self._tree.bind("<Up>", self._on_nav_key)
```

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```
pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add review_modal.py
git commit -m "feat: auto-advance after action and keyboard shortcuts in ReviewModal"
```

---

## Task 4: "Accept All Remaining" button

**Files:**
- Modify: `review_modal.py` — add `_accept_all_remaining` method and button in `_build_action_bar`

- [ ] **Step 1: Add `_accept_all_remaining` method**

Add after `_confirm_edit`:

```python
def _accept_all_remaining(self):
    for i in range(len(self._records)):
        if i not in self._actions:
            self._actions[i] = "accepted"
            self._refresh_row(i)
    self._update_status()
```

- [ ] **Step 2: Add button to `_build_action_bar`**

In `_build_action_bar`, after the existing `self._btn_edit.pack(...)` line, add:

```python
tk.Button(
    left, text="Accept All Remaining", width=20,
    command=self._accept_all_remaining,
).pack(side="left", padx=(16, 4))
```

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```
pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add review_modal.py
git commit -m "feat: add Accept All Remaining button to ReviewModal"
```

---

## Task 5: Column right-click header menu (swap / fill / clear)

**Files:**
- Modify: `review_modal.py` — add `_on_header_rightclick`, `_swap_columns`, `_fill_column`, `_clear_column` methods; wire right-click binding in `_build_table`

- [ ] **Step 1: Add column-action methods to `ReviewModal`**

Add after `_reload_table`:

```python
def _swap_columns(self, field_a: str, field_b: str):
    self._records = swap_column_data(self._records, field_a, field_b)
    self._reload_table()

def _fill_column(self, field: str):
    from tkinter import simpledialog
    value = simpledialog.askstring(
        "Fill Column",
        f"New value for all rows in '{_FIELD_LABELS[field]}':",
        parent=self.window,
    )
    if not value:
        return
    self._records = fill_column_data(self._records, field, value)
    self._reload_table()

def _clear_column(self, field: str):
    self._records = clear_column_data(self._records, field)
    self._reload_table()
```

- [ ] **Step 2: Add `_on_header_rightclick` method**

Add after `_clear_column`:

```python
def _on_header_rightclick(self, event):
    region = self._tree.identify_region(event.x, event.y)
    if region != "heading":
        return
    col_id = self._tree.identify_column(event.x)
    try:
        col_index = int(col_id.lstrip("#")) - 1
        col_name = _COLS[col_index]
    except (ValueError, IndexError):
        return

    menu = tk.Menu(self.window, tearoff=0)
    if col_name in _EDITABLE_FIELDS:
        swap_menu = tk.Menu(menu, tearoff=0)
        for other in _EDITABLE_FIELDS:
            if other != col_name:
                swap_menu.add_command(
                    label=_FIELD_LABELS[other],
                    command=lambda a=col_name, b=other: self._swap_columns(a, b),
                )
        menu.add_cascade(label="Swap with…", menu=swap_menu)
        menu.add_command(label="Fill all rows…", command=lambda: self._fill_column(col_name))
        menu.add_command(label="Clear all", command=lambda: self._clear_column(col_name))
    else:
        menu.add_command(label="Not editable", state="disabled")
    menu.tk_popup(event.x_root, event.y_root)
```

- [ ] **Step 3: Wire right-click binding in `_build_table`**

At the end of `_build_table` (after the keyboard bindings added in Task 3), add:

```python
self._tree.bind("<Button-2>", self._on_header_rightclick)
self._tree.bind("<Button-3>", self._on_header_rightclick)
```

- [ ] **Step 4: Run all tests**

```
pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add review_modal.py
git commit -m "feat: column right-click menu for swap, fill, and clear in ReviewModal"
```
