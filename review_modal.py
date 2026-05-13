from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import ttk


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
        self._edit_frame = None

        self._build_ui()
        if self._records:
            self._select_row(0)

    def get_results(self) -> dict:
        return apply_modal_actions(self._records, self._actions, self._edits)

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

    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx != self._current_index and self._edit_frame is not None:
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
        else:
            self._actions[self._current_index] = "accepted"
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

    def _render_pdf_page(self):
        import fitz  # deferred: only needed when rendering PDF pages
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

        try:
            page_num = int(rec.get("source_page") or 1)
        except (ValueError, TypeError):
            page_num = 1
        page_index = max(0, page_num - 1)

        try:
            doc = fitz.open(pdf_path)
            try:
                page = doc.load_page(page_index)
                mat = fitz.Matrix(self._zoom, self._zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                png_bytes = pix.tobytes("png")
            finally:
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
