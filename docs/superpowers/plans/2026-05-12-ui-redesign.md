# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `gui.py`'s UI with a warm neutral color scheme, Extract/Review tab layout, pill-style radio buttons, and drag-and-drop input.

**Architecture:** Pure UI layer change — all extraction logic, threading, queue handling, and batch functions are untouched. `build_ui()` and its widget helpers are replaced with a `ttk.Notebook` (two tabs) and a warm neutral `ttk.Style`. All existing `self.*` widget attributes are preserved by name so every non-UI method (`run_extraction_thread`, `preview_flagged_rows_thread`, `_populate_preview_panel`, etc.) works without modification.

**Tech Stack:** Python / Tkinter, ttk clam theme, tkinterdnd2 (drag-and-drop)

---

## File Structure

| File | Change |
|---|---|
| `gui.py` | Add `COLORS` dict + module-level helpers; add `_setup_style()`, `_pill_row()`, `_on_drop()`, `_on_drag_enter()`, `_on_drag_leave()`, `_preview_zoom_in()`, `_preview_zoom_out()`; replace `build_ui()` with `_build_extract_tab()` + `_build_review_tab()` |
| `.github/workflows/build-windows.yml` | Add `tkinterdnd2` to pip install; add `--hidden-import=tkinterdnd2` |

---

### Task 1: Add tkinterdnd2 dependency

**Files:**
- Modify: `gui.py`
- Modify: `.github/workflows/build-windows.yml`

- [ ] **Step 1: Install tkinterdnd2 in your dev environment**

```bash
.venv/bin/pip install tkinterdnd2
```

Expected: `Successfully installed tkinterdnd2-...`

- [ ] **Step 2: Add import to `gui.py`**

Open `gui.py`. After `import subprocess` (line 21), add:

```python
import subprocess
from tkinterdnd2 import TkinterDnD, DND_FILES
```

- [ ] **Step 3: Update `__main__` block**

At the bottom of `gui.py` (lines 665–668), replace:

```python
if __name__ == "__main__":
    root = tk.Tk()
    app = ControlPointApp(root)
    root.mainloop()
```

With:

```python
if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = ControlPointApp(root)
    root.mainloop()
```

- [ ] **Step 4: Update `.github/workflows/build-windows.yml`**

Find the Install dependencies step and add `tkinterdnd2`:

```yaml
- name: Install dependencies
  run: |
    python -m pip install --upgrade pip
    pip install requests pyproj pymupdf pdfplumber pyinstaller tkinterdnd2
```

Find the Build EXE step and add `--hidden-import=tkinterdnd2`:

```yaml
- name: Build EXE
  run: |
    pyinstaller --onedir --windowed --name ControlPointExtractor gui.py --hidden-import=requests --hidden-import=pyproj --hidden-import=fitz --hidden-import=pdfplumber --hidden-import=tkinterdnd2
```

- [ ] **Step 5: Smoke test**

```bash
.venv/bin/python gui.py
```

Expected: Window opens. No import errors in terminal.

- [ ] **Step 6: Run test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 12 tests pass.

- [ ] **Step 7: Commit**

```bash
git add gui.py .github/workflows/build-windows.yml
git commit -m "feat: add tkinterdnd2 dependency for drag-and-drop input"
```

---

### Task 2: Color constants, helper functions, and theme setup

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add `COLORS` dict and module-level helper functions**

After `from tkinterdnd2 import TkinterDnD, DND_FILES` and before `class ControlPointApp:`, insert:

```python
COLORS = {
    "bg":              "#fafaf8",
    "card":            "#ffffff",
    "border":          "#e7e5e4",
    "accent":          "#d97706",
    "accent_light":    "#fef3c7",
    "accent_dark":     "#92400e",
    "text":            "#1c1917",
    "text_sec":        "#78716c",
    "text_muted":      "#a8a29e",
    "pill_off_border": "#d4d4d4",
    "progress_trough": "#e7e5e4",
    "log_fg":          "#57534e",
    "dark_surface":    "#44403c",
    "dark_surface2":   "#57534e",
    "dark_text":       "#d6d3d1",
}


def _primary_btn(parent, text, command, **kwargs):
    return tk.Button(
        parent, text=text, command=command,
        bg=COLORS["accent"], fg="white",
        font=("Arial", 11, "bold"),
        relief="flat", bd=0, padx=16, pady=6,
        activebackground="#b45309", activeforeground="white",
        cursor="hand2",
        **kwargs,
    )


def _secondary_btn(parent, text, command, **kwargs):
    return tk.Button(
        parent, text=text, command=command,
        bg=COLORS["card"], fg=COLORS["text_sec"],
        font=("Arial", 10),
        relief="flat", bd=0, padx=10, pady=5,
        highlightbackground=COLORS["pill_off_border"],
        highlightthickness=1,
        activebackground=COLORS["bg"],
        cursor="hand2",
        **kwargs,
    )


def _card(parent, **kwargs):
    return tk.Frame(
        parent,
        bg=COLORS["card"],
        highlightbackground=COLORS["border"],
        highlightthickness=1,
        **kwargs,
    )


def _section_label(parent, text):
    return tk.Label(
        parent,
        text=text,
        font=("Arial", 8, "bold"),
        bg=COLORS["card"],
        fg=COLORS["text_sec"],
    )
```

- [ ] **Step 2: Add `_setup_style()` method to `ControlPointApp`**

Add this as the first method inside `ControlPointApp`, right after `__init__` and before `build_ui`:

```python
def _setup_style(self):
    self.root.configure(bg=COLORS["bg"])
    style = ttk.Style(self.root)
    style.theme_use("clam")
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0, tabmargins=0)
    style.configure(
        "TNotebook.Tab",
        background=COLORS["bg"],
        foreground=COLORS["text_muted"],
        padding=[18, 8],
        font=("Arial", 10),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", COLORS["bg"])],
        foreground=[("selected", COLORS["accent_dark"])],
        font=[("selected", ("Arial", 10, "bold"))],
    )
    style.configure(
        "TProgressbar",
        troughcolor=COLORS["progress_trough"],
        background=COLORS["accent"],
        borderwidth=0,
        thickness=7,
    )
```

- [ ] **Step 3: Add `_pill_row()` method to `ControlPointApp`**

Add after `_setup_style()`:

```python
def _pill_row(self, parent, variable, choices, on_change=None):
    frame = tk.Frame(parent, bg=COLORS["card"])
    self._pill_btns[id(variable)] = {}

    def _update_styles():
        v = variable.get()
        for val, btn in self._pill_btns[id(variable)].items():
            active = val == v
            btn.config(
                bg=COLORS["accent_light"] if active else COLORS["card"],
                fg=COLORS["accent_dark"] if active else COLORS["text_sec"],
                highlightbackground=COLORS["accent"] if active else COLORS["pill_off_border"],
                highlightthickness=1,
            )

    def _select(v):
        variable.set(v)
        if on_change:
            on_change()

    for value, label in choices:
        btn = tk.Button(
            frame, text=label,
            font=("Arial", 9),
            padx=8, pady=3,
            relief="flat", bd=0,
            cursor="hand2",
            command=lambda v=value: _select(v),
        )
        btn.pack(side="left", padx=2)
        self._pill_btns[id(variable)][value] = btn

    _update_styles()
    variable.trace_add("write", lambda *_: _update_styles())
    return frame
```

- [ ] **Step 4: Add `self._pill_btns: dict = {}` and `self._preview_zoom: float = 1.6` to `__init__`**

In `__init__`, after `self._review_polling: bool = False` and before `self.build_ui()`, add:

```python
self._pill_btns: dict = {}
self._preview_zoom: float = 1.6
```

- [ ] **Step 5: Smoke test**

```bash
.venv/bin/python gui.py
```

Expected: Window opens without errors. Visual appearance unchanged (build_ui still builds old layout — theme takes effect in Task 3).

- [ ] **Step 6: Run test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 12 tests pass.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: add COLORS, theme setup, and pill-row helper for UI redesign"
```

---

### Task 3: Replace `build_ui()` with Notebook + complete Extract tab

**Files:**
- Modify: `gui.py`

This task replaces the entire `build_ui()` body with the new tabbed structure and fully implements the Extract tab. A `_build_review_tab()` stub preserves all required widget attributes so existing preview methods keep working.

The following `self.*` attributes **must exist** after this task (referenced by existing non-UI methods — do not rename them):
`self.run_button`, `self.open_output_button`, `self.preview_button`,
`self.progress_var`, `self.progress_bar`, `self.progress_label`, `self.current_file_label`,
`self.log_box`, `self.input_label`, `self.output_label`,
`self.preview_listbox`, `self.preview_table_text`, `self.preview_page_canvas`

- [ ] **Step 1: Replace the entire body of `build_ui()`**

Find `def build_ui(self):` (currently line 48). Replace everything from the `def` line through the last line of the method body (currently ends around line 213, the `self.preview_page_canvas.pack(...)` line) with:

```python
def build_ui(self):
    self._setup_style()

    title_bar = tk.Frame(self.root, bg=COLORS["card"],
                         highlightbackground=COLORS["border"], highlightthickness=1)
    title_bar.pack(fill="x")
    tk.Label(title_bar, text="Control Point PDF Extractor",
             font=("Arial", 14, "bold"),
             bg=COLORS["card"], fg=COLORS["text"],
             padx=16, pady=10).pack(side="left")

    self.notebook = ttk.Notebook(self.root)
    self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

    self.extract_frame = ttk.Frame(self.notebook)
    self.review_frame = ttk.Frame(self.notebook)
    self.notebook.add(self.extract_frame, text="  Extract  ")
    self.notebook.add(self.review_frame, text="  Review  ")

    self._build_extract_tab()
    self._build_review_tab()
```

- [ ] **Step 2: Add `_build_extract_tab()` method**

Add this method directly after `build_ui()`:

```python
def _build_extract_tab(self):
    outer = tk.Frame(self.extract_frame, bg=COLORS["bg"])
    outer.pack(fill="both", expand=True, padx=12, pady=12)

    # --- Top row: Input card + Output card ---
    top_row = tk.Frame(outer, bg=COLORS["bg"])
    top_row.pack(fill="x", pady=(0, 10))
    top_row.columnconfigure(0, weight=1)
    top_row.columnconfigure(1, weight=1)

    # Input card
    input_card = _card(top_row)
    input_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    _section_label(input_card, "INPUT").pack(anchor="w", padx=12, pady=(8, 4))

    self._drop_zone = tk.Frame(
        input_card,
        bg=COLORS["accent_light"],
        highlightbackground=COLORS["accent"],
        highlightthickness=2,
        pady=8,
    )
    self._drop_zone.pack(fill="x", padx=12, pady=(0, 8))
    tk.Label(self._drop_zone, text="📂  Drop folder or PDF(s) here",
             font=("Arial", 10, "bold"),
             bg=COLORS["accent_light"], fg=COLORS["accent_dark"]).pack()
    tk.Label(self._drop_zone, text="or use Browse below",
             font=("Arial", 9),
             bg=COLORS["accent_light"], fg=COLORS["text_muted"]).pack()

    self._pill_row(
        input_card, self.input_mode,
        [("folder", "Folder"), ("single", "Single PDF"), ("multiple", "Multiple PDFs")],
        on_change=self.on_mode_change,
    ).pack(anchor="w", padx=12, pady=(0, 6))

    self.input_label = tk.Label(input_card, text="PDF Folder:",
                                font=("Arial", 10), bg=COLORS["card"], fg=COLORS["text"])
    self.input_label.pack(anchor="w", padx=12)

    input_row = tk.Frame(input_card, bg=COLORS["card"])
    input_row.pack(fill="x", padx=12, pady=(2, 10))
    tk.Entry(input_row, textvariable=self.input_path,
             bg=COLORS["bg"], fg=COLORS["text_sec"],
             relief="flat", bd=0,
             highlightbackground=COLORS["border"],
             highlightthickness=1).pack(
        side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
    _secondary_btn(input_row, "Browse", self.select_input).pack(side="left")

    # Output card
    output_card = _card(top_row)
    output_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    _section_label(output_card, "OUTPUT").pack(anchor="w", padx=12, pady=(8, 4))

    self._pill_row(
        output_card, self.output_mode,
        [("zip", "ZIP"), ("folder", "Folder")],
        on_change=self.on_output_mode_change,
    ).pack(anchor="w", padx=12, pady=(0, 6))

    self.output_label = tk.Label(output_card, text="Output Package (.zip):",
                                 font=("Arial", 10), bg=COLORS["card"], fg=COLORS["text"])
    self.output_label.pack(anchor="w", padx=12)

    output_row = tk.Frame(output_card, bg=COLORS["card"])
    output_row.pack(fill="x", padx=12, pady=(2, 10))
    tk.Entry(output_row, textvariable=self.output_package,
             bg=COLORS["bg"], fg=COLORS["text_sec"],
             relief="flat", bd=0,
             highlightbackground=COLORS["border"],
             highlightthickness=1).pack(
        side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
    _secondary_btn(output_row, "Browse", self.select_output_destination).pack(side="left")

    # --- Action row ---
    action_row = tk.Frame(outer, bg=COLORS["bg"])
    action_row.pack(fill="x", pady=(0, 10))

    self.run_button = _primary_btn(action_row, "▶  Run Extraction", self.run_extraction)
    self.run_button.pack(side="left")

    self.open_output_button = _secondary_btn(
        action_row, "Open Output Folder", self.open_output_folder, state="disabled")
    self.open_output_button.pack(side="left", padx=(8, 0))

    # --- Progress card ---
    prog_card = _card(outer)
    prog_card.pack(fill="x", pady=(0, 10))

    prog_header = tk.Frame(prog_card, bg=COLORS["card"])
    prog_header.pack(fill="x", padx=12, pady=(8, 4))
    tk.Label(prog_header, text="Progress", font=("Arial", 10, "bold"),
             bg=COLORS["card"], fg=COLORS["text"]).pack(side="left")
    self.progress_label = tk.Label(prog_header, text="0 / 0 PDFs",
                                   font=("Arial", 10),
                                   bg=COLORS["card"], fg=COLORS["text_sec"])
    self.progress_label.pack(side="right")

    self.progress_var = tk.DoubleVar(value=0.0)
    self.progress_bar = ttk.Progressbar(
        prog_card, variable=self.progress_var, maximum=100.0, mode="determinate")
    self.progress_bar.pack(fill="x", padx=12, pady=(0, 4))

    self.current_file_label = tk.Label(
        prog_card, text="Current PDF: —",
        font=("Arial", 9), bg=COLORS["card"], fg=COLORS["text_muted"])
    self.current_file_label.pack(anchor="w", padx=12, pady=(0, 8))

    # --- Log card ---
    log_card = _card(outer)
    log_card.pack(fill="both", expand=True)
    _section_label(log_card, "LOG").pack(anchor="w", padx=12, pady=(8, 4))
    self.log_box = scrolledtext.ScrolledText(
        log_card, height=12,
        bg=COLORS["bg"], fg=COLORS["log_fg"],
        font=("Courier", 10),
        relief="flat", bd=0,
        insertbackground=COLORS["text"],
    )
    self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
```

- [ ] **Step 3: Add `_build_review_tab()` stub**

Add this method after `_build_extract_tab()`. It creates placeholder widgets for the preview attributes so all existing methods work:

```python
def _build_review_tab(self):
    outer = tk.Frame(self.review_frame, bg=COLORS["bg"])
    outer.pack(fill="both", expand=True, padx=12, pady=12)

    btn_row = tk.Frame(outer, bg=COLORS["bg"])
    btn_row.pack(fill="x", pady=(0, 10))
    self.preview_button = _primary_btn(
        btn_row, "Preview Flagged Rows…", self.preview_flagged_rows)
    self.preview_button.pack(side="left")

    self.preview_listbox = tk.Listbox(outer, height=5)
    self.preview_listbox.pack(fill="x", pady=(0, 8))
    self.preview_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

    panels = tk.Frame(outer, bg=COLORS["bg"])
    panels.pack(fill="both", expand=True)
    panels.columnconfigure(0, weight=1)
    panels.columnconfigure(1, weight=1)

    table_frame = tk.LabelFrame(panels, text="Extracted Table")
    table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    self.preview_table_text = scrolledtext.ScrolledText(table_frame, height=14)
    self.preview_table_text.pack(fill="both", expand=True)

    page_frame = tk.LabelFrame(panels, text="PDF Page Preview")
    page_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    self.preview_page_canvas = tk.Canvas(page_frame, bg="black")
    self.preview_page_canvas.pack(fill="both", expand=True)
```

- [ ] **Step 4: Update `_update_progress_ui()` and `_reset_progress()` label format**

Find `_update_progress_ui` and change:
```python
self.progress_label.config(text=f"Progress: {done}/{total}")
```
to:
```python
self.progress_label.config(text=f"{done} / {total} PDFs")
```

Find `_reset_progress` and change:
```python
self.progress_label.config(text="Progress: 0/0")
```
to:
```python
self.progress_label.config(text="0 / 0 PDFs")
```

- [ ] **Step 5: Smoke test**

```bash
.venv/bin/python gui.py
```

Expected:
- Window opens with warm stone background and amber accent title bar
- Two tabs: Extract and Review
- Extract tab: Input card with drop zone, Output card, amber Run Extraction button, progress card, log area
- Clicking Browse works, Run Extraction with no input shows error dialog
- Review tab: Preview Flagged Rows… button visible, placeholder listbox and panels below

- [ ] **Step 6: Run test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 12 tests pass.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: rebuild gui.py UI with warm neutral theme and Extract/Review tabs"
```

---

### Task 4: Add drag-and-drop to the Input card

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Register the drop target in `_build_extract_tab()`**

At the end of the drop zone setup block (after the two `tk.Label` lines for the drop zone text), add these lines inside `_build_extract_tab()`:

```python
    self._drop_zone.drop_target_register(DND_FILES)
    self._drop_zone.dnd_bind("<<DragEnter>>", self._on_drag_enter)
    self._drop_zone.dnd_bind("<<DragLeave>>", self._on_drag_leave)
    self._drop_zone.dnd_bind("<<Drop>>", self._on_drop)
    for child in self._drop_zone.winfo_children():
        child.drop_target_register(DND_FILES)
        child.dnd_bind("<<DragEnter>>", self._on_drag_enter)
        child.dnd_bind("<<DragLeave>>", self._on_drag_leave)
        child.dnd_bind("<<Drop>>", self._on_drop)
```

- [ ] **Step 2: Add `_on_drag_enter()` method**

Add after `_build_review_tab()`:

```python
def _on_drag_enter(self, event):
    self._drop_zone.configure(bg="#fef9e6", highlightbackground="#b45309")
    for child in self._drop_zone.winfo_children():
        child.configure(bg="#fef9e6")
```

- [ ] **Step 3: Add `_on_drag_leave()` method**

```python
def _on_drag_leave(self, event):
    self._drop_zone.configure(
        bg=COLORS["accent_light"], highlightbackground=COLORS["accent"])
    for child in self._drop_zone.winfo_children():
        child.configure(bg=COLORS["accent_light"])
```

- [ ] **Step 4: Add `_on_drop()` method**

```python
def _on_drop(self, event):
    self._on_drag_leave(event)
    paths = self.root.tk.splitlist(event.data)
    paths = [p for p in paths if p]
    if not paths:
        return

    if len(paths) == 1 and os.path.isdir(paths[0]):
        self.input_mode.set("folder")
        self._selected_pdfs = []
        self.input_path.set(paths[0])
        self.input_label.config(text="PDF Folder:")
        self.output_package.set(self._default_output_destination(paths[0], "folder"))
    elif len(paths) == 1:
        self.input_mode.set("single")
        self._selected_pdfs = []
        self.input_path.set(paths[0])
        self.input_label.config(text="PDF File:")
        self.output_package.set(self._default_output_destination(paths[0], "single"))
    else:
        self.input_mode.set("multiple")
        self._selected_pdfs = list(paths)
        self.input_path.set(f"{len(paths)} PDF(s) selected")
        self.input_label.config(text="PDF Files:")
        base = str(Path(paths[0]).parent)
        self.output_package.set(self._default_output_destination(base, "folder"))
```

- [ ] **Step 5: Smoke test drag-and-drop**

```bash
.venv/bin/python gui.py
```

Expected:
- Drag a folder from Finder onto the drop zone → border darkens on hover; on release, path field fills, "Folder" pill activates
- Drag a single PDF → path fills, "Single PDF" pill activates
- Drag multiple PDFs → "N PDF(s) selected" shown, "Multiple PDFs" pill activates

- [ ] **Step 6: Run test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 12 tests pass.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: add drag-and-drop input via tkinterdnd2"
```

---

### Task 5: Build the Review tab with full styling

**Files:**
- Modify: `gui.py`

Replace the `_build_review_tab()` stub with the full implementation: styled listbox, side-by-side table + dark PDF panel, zoom controls. Add zoom methods and update `_render_preview_index` to use `self._preview_zoom`.

- [ ] **Step 1: Replace `_build_review_tab()` with the full implementation**

Find `def _build_review_tab(self):` and replace the entire method body with:

```python
def _build_review_tab(self):
    outer = tk.Frame(self.review_frame, bg=COLORS["bg"])
    outer.pack(fill="both", expand=True, padx=12, pady=12)

    # Trigger button
    btn_row = tk.Frame(outer, bg=COLORS["bg"])
    btn_row.pack(fill="x", pady=(0, 10))
    self.preview_button = _primary_btn(
        btn_row, "Preview Flagged Rows…", self.preview_flagged_rows)
    self.preview_button.pack(side="left")

    # Flagged records card
    records_card = _card(outer)
    records_card.pack(fill="x", pady=(0, 10))
    self._records_header = _section_label(records_card, "FLAGGED RECORDS")
    self._records_header.pack(anchor="w", padx=12, pady=(8, 6))

    listbox_frame = tk.Frame(records_card, bg=COLORS["card"])
    listbox_frame.pack(fill="x", padx=12, pady=(0, 8))
    self.preview_listbox = tk.Listbox(
        listbox_frame,
        height=5,
        bg=COLORS["card"],
        fg=COLORS["text"],
        selectbackground=COLORS["accent_light"],
        selectforeground=COLORS["accent_dark"],
        font=("Arial", 10),
        relief="flat", bd=0,
        activestyle="none",
        highlightthickness=0,
    )
    lb_scroll = ttk.Scrollbar(listbox_frame, orient="vertical",
                               command=self.preview_listbox.yview)
    self.preview_listbox.configure(yscrollcommand=lb_scroll.set)
    self.preview_listbox.pack(side="left", fill="both", expand=True)
    lb_scroll.pack(side="right", fill="y")
    self.preview_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

    # Side-by-side panels
    panels = tk.Frame(outer, bg=COLORS["bg"])
    panels.pack(fill="both", expand=True)
    panels.columnconfigure(0, weight=1)
    panels.columnconfigure(1, weight=1)
    panels.rowconfigure(0, weight=1)

    # Left: Extracted table card
    table_card = _card(panels)
    table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    table_card.rowconfigure(1, weight=1)
    table_card.columnconfigure(0, weight=1)
    _section_label(table_card, "EXTRACTED TABLE").grid(
        row=0, column=0, sticky="w", padx=12, pady=(8, 4))
    self.preview_table_text = scrolledtext.ScrolledText(
        table_card,
        height=14,
        bg=COLORS["bg"], fg=COLORS["log_fg"],
        font=("Courier", 9),
        relief="flat", bd=0,
        highlightthickness=0,
    )
    self.preview_table_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

    # Right: PDF page card (dark)
    page_card = tk.Frame(
        panels,
        bg=COLORS["dark_surface"],
        highlightbackground=COLORS["border"],
        highlightthickness=1,
    )
    page_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
    page_card.rowconfigure(1, weight=1)
    page_card.columnconfigure(0, weight=1)
    tk.Label(page_card, text="PDF PAGE",
             font=("Arial", 8, "bold"),
             bg=COLORS["dark_surface"], fg=COLORS["dark_text"]).grid(
        row=0, column=0, sticky="w", padx=12, pady=(8, 4))
    self.preview_page_canvas = tk.Canvas(
        page_card,
        bg=COLORS["dark_surface"],
        highlightthickness=0,
    )
    self.preview_page_canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))

    # Zoom controls
    zoom_row = tk.Frame(page_card, bg=COLORS["dark_surface"])
    zoom_row.grid(row=2, column=0, pady=(0, 8))
    tk.Button(zoom_row, text="–", width=3,
              bg=COLORS["dark_surface2"], fg=COLORS["dark_text"],
              relief="flat", bd=0, cursor="hand2",
              activebackground=COLORS["dark_surface"],
              command=self._preview_zoom_out).pack(side="left", padx=4)
    self._preview_zoom_label = tk.Label(
        zoom_row, text="160%", width=5,
        bg=COLORS["dark_surface"], fg=COLORS["dark_text"])
    self._preview_zoom_label.pack(side="left")
    tk.Button(zoom_row, text="+", width=3,
              bg=COLORS["dark_surface2"], fg=COLORS["dark_text"],
              relief="flat", bd=0, cursor="hand2",
              activebackground=COLORS["dark_surface"],
              command=self._preview_zoom_in).pack(side="left", padx=4)
```

- [ ] **Step 2: Add `_preview_zoom_in()` and `_preview_zoom_out()` methods**

Add after `_build_review_tab()`:

```python
def _preview_zoom_in(self):
    self._preview_zoom = min(self._preview_zoom + 0.2, 4.0)
    self._preview_zoom_label.config(text=f"{int(self._preview_zoom * 100)}%")
    sel = self.preview_listbox.curselection()
    if sel:
        self._render_preview_index(sel[0])

def _preview_zoom_out(self):
    self._preview_zoom = max(self._preview_zoom - 0.2, 0.5)
    self._preview_zoom_label.config(text=f"{int(self._preview_zoom * 100)}%")
    sel = self.preview_listbox.curselection()
    if sel:
        self._render_preview_index(sel[0])
```

- [ ] **Step 3: Update `_render_preview_index()` to use `self._preview_zoom`**

Find `_render_preview_index` and locate this line:

```python
pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
```

Replace with:

```python
pix = page.get_pixmap(matrix=fitz.Matrix(self._preview_zoom, self._preview_zoom), alpha=False)
```

- [ ] **Step 4: Update `_populate_preview_panel()` to show filename in records header**

Find `_populate_preview_panel` and add this line right after `self._preview_pdf_path = pdf_path`:

```python
        self._records_header.config(
            text=f"FLAGGED RECORDS — {Path(pdf_path).name}")
```

- [ ] **Step 5: Smoke test**

```bash
.venv/bin/python gui.py
```

Expected:
- Review tab shows styled flagged records card, side-by-side panels (table left, dark PDF right with zoom controls)
- Select a valid PDF and click "Preview Flagged Rows…" → records populate in styled listbox, clicking one shows table data and PDF page
- Zoom in/out buttons adjust the PDF rendering

- [ ] **Step 6: Run test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 12 tests pass.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: build full Review tab with styled listbox, side-by-side panels, and zoom"
```
