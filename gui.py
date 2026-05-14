import threading
import queue
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import base64

from review_modal import ReviewModal

import os
import subprocess

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except Exception:
    _DND_AVAILABLE = False
    DND_FILES = None

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
        bg=COLORS["accent"], fg="#1c0a00",
        font=("Arial", 11, "bold"),
        relief="solid", bd=2,
        highlightbackground="#b45309", highlightthickness=0,
        padx=16, pady=7,
        activebackground="#b45309", activeforeground="white",
        cursor="hand2",
        **kwargs,
    )


def _secondary_btn(parent, text, command, **kwargs):
    return tk.Button(
        parent, text=text, command=command,
        bg="#ede9e8", fg=COLORS["text"],
        font=("Arial", 10),
        relief="solid", bd=1,
        highlightthickness=0,
        padx=10, pady=6,
        activebackground="#e0dbd9",
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


class ControlPointApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Control Point Extractor")
        self.root.geometry("1200x700")

        self.input_mode = tk.StringVar(value="folder")  # "folder" | "single" | "multiple"
        self.output_mode = tk.StringVar(value="zip")  # "zip" | "folder"
        self.input_path = tk.StringVar()
        self.output_package = tk.StringVar()

        self._selected_pdfs: list[str] = []
        self._last_delivery_path: str | None = None

        self._preview_pdf_path: str | None = None
        self._preview_flagged_records: list[dict] = []
        self._preview_image_photo = None
        self._progress_total = 0

        self._review_request_q: queue.Queue = queue.Queue()
        self._review_result_q: queue.Queue = queue.Queue()
        self._review_polling: bool = False

        self._pill_btns: dict = {}
        self._preview_zoom: float = 1.6

        self.build_ui()

    def _setup_style(self):
        self.root.configure(bg=COLORS["bg"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("TNotebook", background=COLORS["border"], borderwidth=0, tabmargins=0)
        style.configure(
            "TNotebook.Tab",
            background=COLORS["border"],
            foreground=COLORS["text_sec"],
            padding=[18, 8],
            font=("Arial", 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["card"]), ("active", "#f0eeec")],
            foreground=[("selected", COLORS["accent_dark"]), ("active", COLORS["text"])],
            font=[("selected", ("Arial", 10, "bold"))],
        )
        style.configure(
            "TProgressbar",
            troughcolor=COLORS["progress_trough"],
            background=COLORS["accent"],
            borderwidth=0,
            thickness=7,
        )

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
        if _DND_AVAILABLE:
            tk.Label(self._drop_zone, text="📂  Drop folder or PDF(s) here",
                     font=("Arial", 10, "bold"),
                     bg=COLORS["accent_light"], fg=COLORS["accent_dark"]).pack()
            tk.Label(self._drop_zone, text="or use Browse below",
                     font=("Arial", 9),
                     bg=COLORS["accent_light"], fg=COLORS["text_muted"]).pack()
        else:
            tk.Label(self._drop_zone, text="📂  Use Browse to select files",
                     font=("Arial", 10, "bold"),
                     bg=COLORS["accent_light"], fg=COLORS["accent_dark"]).pack()
            tk.Label(self._drop_zone, text="(drag-and-drop not available on this system)",
                     font=("Arial", 9),
                     bg=COLORS["accent_light"], fg=COLORS["text_muted"]).pack()

        if _DND_AVAILABLE:
            self._drop_zone.drop_target_register(DND_FILES)
            self._drop_zone.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self._drop_zone.dnd_bind("<<DragLeave>>", self._on_drag_leave)
            self._drop_zone.dnd_bind("<<Drop>>", self._on_drop)
            for child in self._drop_zone.winfo_children():
                child.drop_target_register(DND_FILES)
                child.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                child.dnd_bind("<<DragLeave>>", self._on_drag_leave)
                child.dnd_bind("<<Drop>>", self._on_drop)

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

    def _on_drag_enter(self, event):
        self._drop_zone.configure(bg="#fef9e6", highlightbackground="#b45309")
        for child in self._drop_zone.winfo_children():
            child.configure(bg="#fef9e6")

    def _on_drag_leave(self, event):
        self._drop_zone.configure(
            bg=COLORS["accent_light"], highlightbackground=COLORS["accent"])
        for child in self._drop_zone.winfo_children():
            child.configure(bg=COLORS["accent_light"])

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

    def select_input(self):
        mode = self.input_mode.get()

        if mode == "single":
            chosen = filedialog.askopenfilename(
                title="Select a PDF",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
        elif mode == "multiple":
            chosen = filedialog.askopenfilenames(
                title="Select PDF files",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
            chosen = list(chosen or [])
        else:
            chosen = filedialog.askdirectory(title="Select folder containing PDFs")

        if chosen:
            if mode == "multiple":
                self._selected_pdfs = chosen
                self.input_path.set(f"{len(self._selected_pdfs)} PDF(s) selected")
                base_for_default = str(Path(self._selected_pdfs[0]).parent) if self._selected_pdfs else ""
                self.output_package.set(self._default_output_destination(base_for_default, "folder"))
            else:
                self._selected_pdfs = []
                self.input_path.set(chosen)
                self.output_package.set(self._default_output_destination(chosen, mode))

    def on_mode_change(self):
        mode = self.input_mode.get()
        self.input_path.set("")
        self._selected_pdfs = []

        if mode == "single":
            self.input_label.config(text="PDF File:")
        elif mode == "multiple":
            self.input_label.config(text="PDF Files:")
        else:
            self.input_label.config(text="PDF Folder:")

        # Reset output suggestion since it depends on input location/name.
        self.output_package.set("")

    def on_output_mode_change(self):
        self.output_package.set("")
        if self.output_mode.get() == "folder":
            self.output_label.config(text="Output Folder:")
        else:
            self.output_label.config(text="Output Package (.zip):")

        chosen = self.input_path.get()
        if chosen:
            self.output_package.set(self._default_output_destination(chosen, self.input_mode.get()))

    def _default_output_destination(self, chosen, input_mode):
        if not chosen:
            chosen = str(Path.cwd())
        base = Path(chosen).parent if input_mode == "single" else Path(chosen)
        name = Path(chosen).stem if input_mode == "single" else base.name

        if self.output_mode.get() == "folder":
            return str(base / f"{name}_control_point_outputs")

        return str(base / f"{name}_control_point_outputs.zip")

    def select_output_destination(self):
        input_mode = self.input_mode.get()
        chosen_input = self.input_path.get()

        if self.output_mode.get() == "folder":
            folder = filedialog.askdirectory(title="Select output folder")
            if folder:
                self.output_package.set(folder)
            return

        initialfile = ""
        initialdir = None
        if chosen_input:
            initialdir = str((Path(chosen_input).parent if input_mode == "single" else Path(chosen_input)).resolve())
            initialfile = Path(self._default_output_destination(chosen_input, input_mode)).name

        path = filedialog.asksaveasfilename(
            title="Save output package",
            defaultextension=".zip",
            filetypes=[("ZIP archive", "*.zip")],
            initialdir=initialdir,
            initialfile=initialfile,
        )

        if path:
            self.output_package.set(path)

    def log(self, message):
        self.log_box.insert(tk.END, message + "\n")
        self.log_box.see(tk.END)
        self.root.update_idletasks()

    def log_threadsafe(self, message):
        self.root.after(0, lambda: self.log(message))

    def _reset_progress(self):
        self._progress_total = 0
        self.progress_var.set(0.0)
        self.progress_label.config(text="0 / 0 PDFs")
        self.current_file_label.config(text="Current PDF: —")
        self._last_delivery_path = None
        self.open_output_button.config(state="disabled")

    def _update_progress_ui(self, payload: dict):
        phase = payload.get("phase")
        current = int(payload.get("current") or 0)
        total = int(payload.get("total") or 0)
        pdf = str(payload.get("pdf") or "")

        self._progress_total = total
        shown_name = Path(pdf).name if pdf else "—"
        self.current_file_label.config(text=f"Current PDF: {shown_name}")

        done = current if phase == "done" else max(0, current - 1)
        if total <= 0:
            pct = 0.0
        else:
            pct = max(0.0, min(100.0, (done / total) * 100.0))

        self.progress_var.set(pct)
        self.progress_label.config(text=f"{done} / {total} PDFs")

    def run_extraction(self):
        input_value = self.input_path.get()
        output_destination = self.output_package.get()

        if self.input_mode.get() == "multiple":
            if not self._selected_pdfs:
                messagebox.showerror("Missing PDFs", "Please select one or more PDF files.")
                return
        elif not input_value:
            if self.input_mode.get() == "single":
                messagebox.showerror("Missing PDF", "Please select a PDF file.")
            else:
                messagebox.showerror("Missing Folder", "Please select a PDF folder.")
            return

        if not output_destination:
            if self.output_mode.get() == "folder":
                messagebox.showerror("Missing Output", "Please choose an output folder.")
            else:
                messagebox.showerror("Missing Output", "Please choose where to save the .zip output package.")
            return

        self.run_button.config(state="disabled")
        self.log_box.delete("1.0", tk.END)
        self.log("Starting extraction...")
        self._reset_progress()

        self._review_request_q = queue.Queue()
        self._review_result_q = queue.Queue()
        self._start_review_polling()

        thread = threading.Thread(
            target=self.run_extraction_thread,
            args=(input_value, output_destination)
        )
        thread.start()

    def _select_preview_pdf(self) -> str | None:
        input_value = self.input_path.get()
        if self.input_mode.get() == "multiple":
            if not self._selected_pdfs:
                return None
            chosen = filedialog.askopenfilename(
                title="Select a PDF to preview",
                initialdir=str(Path(self._selected_pdfs[0]).parent.resolve()),
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
            return chosen or None

        if not input_value:
            return None

        if self.input_mode.get() == "single":
            return input_value

        folder = Path(input_value)
        if not folder.exists():
            return None

        chosen = filedialog.askopenfilename(
            title="Select a PDF to preview",
            initialdir=str(folder.resolve()),
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        return chosen or None

    def preview_flagged_rows(self):
        pdf_path = self._select_preview_pdf()
        if not pdf_path:
            if self.input_mode.get() == "single":
                messagebox.showerror("Missing PDF", "Please select a PDF file.")
            else:
                messagebox.showerror("Missing Folder", "Please select a PDF folder (then choose a PDF to preview).")
            return

        self.preview_button.config(state="disabled")
        self.log("Preview: extracting + validating (no export)…")

        thread = threading.Thread(target=self.preview_flagged_rows_thread, args=(pdf_path,))
        thread.start()

    def preview_flagged_rows_thread(self, pdf_path: str):
        from control_point import extract_project_metadata, scanner, extract_control_points
        from data_validation import validate_and_normalize_records
        from datum_standardization import standardize_records
        from output_control import deduplicate_records, flag_uncertain_duplicates
        try:
            log = self.log_threadsafe
            log(f"Preview PDF: {Path(pdf_path).name}")

            metadata = extract_project_metadata(pdf_path)
            extraction_page_indices, _ = scanner(pdf_path, log=None, verbose=False)
            records = extract_control_points(pdf_path, extraction_page_indices, log=None)

            for record in records:
                record["horizontal_datum"] = metadata["horizontal_datum"]
                record["vertical_datum"] = metadata["vertical_datum"]
                record["coordinate_system"] = metadata["coordinate_system"]
                record["source_pdf"] = Path(pdf_path).name

            records = validate_and_normalize_records(records, log=None)
            records = standardize_records(records, log=None)
            records, _ = deduplicate_records(records, log=None, context="preview")
            records = flag_uncertain_duplicates(records, log=None, context="preview")

            flagged = []
            for record in records:
                if (record.get("validation_status") or "") != "ok":
                    flagged.append(record)
                    continue
                if (record.get("validation_flags") or ""):
                    flagged.append(record)
                    continue
                if (record.get("dedupe_status") or "") == "uncertain":
                    flagged.append(record)
                    continue
                if (record.get("dedupe_flags") or ""):
                    flagged.append(record)
                    continue

            self.root.after(0, lambda: self._populate_preview_panel(pdf_path, flagged))

        except Exception as error:
            self.log_threadsafe(f"ERROR (preview): {error}")
            self.root.after(0, lambda: messagebox.showerror("Preview Error", str(error)))
        finally:
            self.root.after(0, lambda: self.preview_button.config(state="normal"))

    def _populate_preview_panel(self, pdf_path: str, flagged_records: list[dict]):
        self._preview_pdf_path = pdf_path
        self._records_header.config(
            text=f"FLAGGED RECORDS — {Path(pdf_path).name}")
        self._preview_flagged_records = list(flagged_records or [])

        self.preview_listbox.delete(0, tk.END)
        self.preview_table_text.delete("1.0", tk.END)
        self.preview_page_canvas.delete("all")

        if not self._preview_flagged_records:
            self.preview_table_text.insert(
                tk.END,
                "No suspicious/invalid rows were detected for this PDF.\n"
                "Nothing to preview here.\n",
            )
            self.preview_page_canvas.create_text(
                20, 20, anchor="nw", fill="white", text="No flagged rows."
            )
            return

        for rec in self._preview_flagged_records:
            pt = rec.get("system_point_id") or rec.get("point_normalized") or rec.get("source_point_id") or rec.get("point") or "?"
            pg = rec.get("source_page") or "?"
            flags = rec.get("validation_flags") or rec.get("validation_status") or ""
            self.preview_listbox.insert(tk.END, f"Pt {pt} | p{pg} | {flags}")

        self.preview_listbox.selection_set(0)
        self._render_preview_index(0)

    def _on_preview_select(self, event):
        sel = self.preview_listbox.curselection()
        if not sel:
            return
        self._render_preview_index(sel[0])

    def _render_preview_index(self, index: int):
        import fitz
        import pdfplumber
        from confidence import find_best_table
        if not self._preview_pdf_path or not self._preview_flagged_records:
            return

        rec = self._preview_flagged_records[index]
        page_num = int(rec.get("source_page") or 1)
        page_index = max(0, page_num - 1)

        # Table grid
        self.preview_table_text.delete("1.0", tk.END)
        try:
            with pdfplumber.open(self._preview_pdf_path) as pdf:
                page = pdf.pages[page_index]
                table, score = find_best_table(page)
                self.preview_table_text.insert(tk.END, f"Page {page_num} | confidence score {score}\n")
                self.preview_table_text.insert(tk.END, f"Flags: {rec.get('validation_flags') or rec.get('validation_status')}\n\n")
                if not table:
                    self.preview_table_text.insert(tk.END, "No table detected on this page.\n")
                else:
                    for row in table:
                        safe = [(cell or "").replace("\n", " ").strip() for cell in row]
                        self.preview_table_text.insert(tk.END, "\t".join(safe) + "\n")
        except Exception as exc:
            self.preview_table_text.insert(tk.END, f"Failed to extract table: {exc}\n")

        # Page image (whole page preview)
        self.preview_page_canvas.delete("all")
        try:
            doc = fitz.open(self._preview_pdf_path)
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(self._preview_zoom, self._preview_zoom), alpha=False)
            png_bytes = pix.tobytes("png")
            doc.close()

            b64 = base64.b64encode(png_bytes).decode("ascii")
            photo = tk.PhotoImage(data=b64)
            self._preview_image_photo = photo  # keep alive
            self.preview_page_canvas.create_image(0, 0, anchor="nw", image=photo)
            self.preview_page_canvas.config(scrollregion=(0, 0, photo.width(), photo.height()))
        except Exception as exc:
            self.preview_page_canvas.create_text(
                20,
                20,
                anchor="nw",
                fill="white",
                text=f"Failed to render page preview: {exc}",
            )

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
        try:
            modal = ReviewModal(self.root, msg["low_conf"], msg["pdf_path_map"])
            self.root.wait_window(modal.window)
            result = modal.get_results()
        except Exception as exc:
            self.log_threadsafe(f"Review modal error: {exc}")
            result = {"accepted": msg["low_conf"], "skipped": []}
        self._review_result_q.put(result)
        self.root.after(100, self._poll_review_queue)

    def run_extraction_thread(self, input_value, output_destination):
        try:
            from batch import (
                run_batch_packaged,
                run_single_packaged,
                run_batch_folder,
                run_single_folder,
                run_multi,
                run_multi_packaged,
            )
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

            log("")
            log("Finishing up…")
            log("Extraction complete.")
            log(f"PDFs processed: {result['pdf_count']}")
            log(f"Total records extracted: {result['total_records']}")
            if "clean_records" in result and "review_records" in result:
                log(f"Clean export rows: {result.get('clean_records')}")
                log(f"Needs review rows: {result.get('review_records')}")
            log(f"Output saved to: {result['delivery_path']}")
            self._last_delivery_path = result.get("delivery_path")
            self.root.after(0, lambda: self.open_output_button.config(state="normal"))

            log("")
            log("Per-file results:")

            for item in result["results"]:
                log(
                    f"{item['pdf']} | "
                    f"{item['status']} | "
                    f"{item['valid_count']} records | "
                    f"pages {item['extraction_pages']}"
                )

            messagebox.showinfo(
                "Done",
                "Extraction complete.\n\n"
                f"Total records: {result['total_records']}\n"
                f"Clean export: {result.get('clean_records', '—')}\n"
                f"Needs review: {result.get('review_records', '—')}\n"
                "ArcGIS CSV: arcgis_points.csv"
            )

        except Exception as error:
            self.log(f"ERROR: {error}")
            messagebox.showerror("Error", str(error))

        finally:
            self.root.after(0, self._stop_review_polling)
            self.run_button.config(state="normal")

    def open_output_folder(self):
        path = self._last_delivery_path
        if not path:
            messagebox.showerror("No Output", "No output folder is available yet.")
            return
        p = Path(path)
        if p.suffix.lower() == ".zip":
            p = p.parent
        try:
            if os.name == "nt":
                os.startfile(str(p))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(p)], check=False)
            else:
                subprocess.run(["xdg-open", str(p)], check=False)
        except Exception as exc:
            messagebox.showerror("Open Folder Failed", str(exc))


def _set_window_icon(root):
    try:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base, "PDF_PARSER.png")
        if os.path.exists(icon_path):
            img = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, img)
    except Exception:
        pass


if __name__ == "__main__":
    root = TkinterDnD.Tk() if _DND_AVAILABLE else tk.Tk()
    _set_window_icon(root)
    app = ControlPointApp(root)
    root.mainloop()
