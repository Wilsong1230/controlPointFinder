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

import fitz
import pdfplumber

from control_point import extract_project_metadata, scanner, extract_control_points
from confidence import find_best_table
from data_validation import validate_and_normalize_records
from datum_standardization import standardize_records
from output_control import deduplicate_records, flag_uncertain_duplicates


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

        self.build_ui()

    def build_ui(self):
        title = tk.Label(self.root, text="Control Point PDF Extractor", font=("Arial", 18, "bold"))
        title.pack(pady=10)

        main = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = tk.Frame(main)
        right = tk.Frame(main)
        main.add(left, minsize=650)
        main.add(right, minsize=450)

        input_frame = tk.Frame(left)
        input_frame.pack(fill="x", padx=10, pady=5)

        mode_row = tk.Frame(input_frame)
        mode_row.pack(fill="x")

        tk.Label(mode_row, text="Input Type:").pack(side="left")
        tk.Radiobutton(
            mode_row,
            text="Folder",
            variable=self.input_mode,
            value="folder",
            command=self.on_mode_change,
        ).pack(side="left", padx=10)
        tk.Radiobutton(
            mode_row,
            text="Single PDF",
            variable=self.input_mode,
            value="single",
            command=self.on_mode_change,
        ).pack(side="left")
        tk.Radiobutton(
            mode_row,
            text="Multiple PDFs",
            variable=self.input_mode,
            value="multiple",
            command=self.on_mode_change,
        ).pack(side="left", padx=10)

        self.input_label = tk.Label(input_frame, text="PDF Folder:")
        self.input_label.pack(anchor="w")

        input_row = tk.Frame(input_frame)
        input_row.pack(fill="x")

        tk.Entry(input_row, textvariable=self.input_path).pack(
            side="left",
            fill="x",
            expand=True
        )

        tk.Button(
            input_row,
            text="Browse",
            command=self.select_input
        ).pack(side="left", padx=5)

        output_frame = tk.Frame(left)
        output_frame.pack(fill="x", padx=10, pady=5)

        output_mode_row = tk.Frame(output_frame)
        output_mode_row.pack(fill="x")

        tk.Label(output_mode_row, text="Output Type:").pack(side="left")
        tk.Radiobutton(
            output_mode_row,
            text="ZIP",
            variable=self.output_mode,
            value="zip",
            command=self.on_output_mode_change,
        ).pack(side="left", padx=10)
        tk.Radiobutton(
            output_mode_row,
            text="Folder",
            variable=self.output_mode,
            value="folder",
            command=self.on_output_mode_change,
        ).pack(side="left")

        self.output_label = tk.Label(output_frame, text="Output Package (.zip):")
        self.output_label.pack(anchor="w")

        output_row = tk.Frame(output_frame)
        output_row.pack(fill="x")

        tk.Entry(output_row, textvariable=self.output_package).pack(
            side="left",
            fill="x",
            expand=True
        )

        tk.Button(
            output_row,
            text="Browse",
            command=self.select_output_destination
        ).pack(side="left", padx=5)

        action_row = tk.Frame(left)
        action_row.pack(fill="x", padx=10, pady=10)

        self.run_button = tk.Button(action_row, text="Run Extraction", command=self.run_extraction, height=2)
        self.run_button.pack(side="left")

        self.open_output_button = tk.Button(
            action_row,
            text="Open Output Folder",
            command=self.open_output_folder,
            height=2,
            state="disabled",
        )
        self.open_output_button.pack(side="left", padx=10)

        self.preview_button = tk.Button(
            action_row,
            text="Preview Flagged Rows",
            command=self.preview_flagged_rows,
            height=2,
        )
        self.preview_button.pack(side="left", padx=10)

        # --- Progress ---
        progress_frame = tk.Frame(left)
        progress_frame.pack(fill="x", padx=10, pady=(0, 6))

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.pack(fill="x")

        self.progress_label = tk.Label(progress_frame, text="Progress: 0/0")
        self.progress_label.pack(anchor="w", pady=(4, 0))

        self.current_file_label = tk.Label(progress_frame, text="Current PDF: —")
        self.current_file_label.pack(anchor="w")

        self.log_box = scrolledtext.ScrolledText(left, height=18)
        self.log_box.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Preview panel (right side) ---
        preview_title = tk.Label(right, text="Preview (flagged rows)", font=("Arial", 12, "bold"))
        preview_title.pack(anchor="w", padx=10, pady=(0, 6))

        self.preview_listbox = tk.Listbox(right, height=7)
        self.preview_listbox.pack(fill="x", padx=10, pady=(0, 8))
        self.preview_listbox.bind("<<ListboxSelect>>", self._on_preview_select)

        self.preview_panes = tk.PanedWindow(right, orient=tk.VERTICAL, sashrelief=tk.RAISED)
        self.preview_panes.pack(fill="both", expand=True, padx=10, pady=10)

        table_frame = tk.LabelFrame(self.preview_panes, text="Extracted Table (best guess)")
        page_frame = tk.LabelFrame(self.preview_panes, text="PDF Page Preview")

        self.preview_panes.add(table_frame, minsize=220)
        self.preview_panes.add(page_frame, minsize=220)

        self.preview_table_text = scrolledtext.ScrolledText(table_frame, height=14)
        self.preview_table_text.pack(fill="both", expand=True)

        self.preview_page_canvas = tk.Canvas(page_frame, bg="black")
        self.preview_page_canvas.pack(fill="both", expand=True)

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
        self.progress_label.config(text="Progress: 0/0")
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
        self.progress_label.config(text=f"Progress: {done}/{total}")

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
            pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
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
        modal = ReviewModal(self.root, msg["low_conf"], msg["pdf_path_map"])
        self.root.wait_window(modal.window)
        result = modal.get_results()
        self._review_result_q.put(result)
        self.root.after(100, self._poll_review_queue)

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
            if os.name == "posix":
                subprocess.run(["open", str(p)], check=False)
            else:
                subprocess.run(["xdg-open", str(p)], check=False)
        except Exception as exc:
            messagebox.showerror("Open Folder Failed", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = ControlPointApp(root)
    root.mainloop()
