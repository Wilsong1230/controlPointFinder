import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import base64

from batch import (
    run_batch_packaged,
    run_single_packaged,
    run_batch_folder,
    run_single_folder,
)

import fitz
import pdfplumber

from control_point import extract_project_metadata, scanner, extract_control_points, find_best_table
from data_validation import validate_and_normalize_records
from datum_standardization import standardize_records
from output_control import deduplicate_records, flag_uncertain_duplicates


class ControlPointApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Control Point Extractor")
        self.root.geometry("1200x700")

        self.input_mode = tk.StringVar(value="folder")  # "folder" | "single"
        self.output_mode = tk.StringVar(value="zip")  # "zip" | "folder"
        self.input_path = tk.StringVar()
        self.output_package = tk.StringVar()

        self._preview_pdf_path: str | None = None
        self._preview_flagged_records: list[dict] = []
        self._preview_image_photo = None

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

        self.preview_button = tk.Button(
            action_row,
            text="Preview Flagged Rows",
            command=self.preview_flagged_rows,
            height=2,
        )
        self.preview_button.pack(side="left", padx=10)

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
        else:
            chosen = filedialog.askdirectory(title="Select folder containing PDFs")

        if chosen:
            self.input_path.set(chosen)
            self.output_package.set(self._default_output_destination(chosen, mode))

    def on_mode_change(self):
        mode = self.input_mode.get()
        self.input_path.set("")

        if mode == "single":
            self.input_label.config(text="PDF File:")
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

    def run_extraction(self):
        input_value = self.input_path.get()
        output_destination = self.output_package.get()

        if not input_value:
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

        thread = threading.Thread(
            target=self.run_extraction_thread,
            args=(input_value, output_destination)
        )
        thread.start()

    def _select_preview_pdf(self) -> str | None:
        input_value = self.input_path.get()
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

    def run_extraction_thread(self, input_value, output_destination):
        try:
            log = self.log_threadsafe

            if self.output_mode.get() == "folder":
                if self.input_mode.get() == "single":
                    result = run_single_folder(input_value, output_destination, log=log)
                else:
                    result = run_batch_folder(input_value, output_destination, log=log)
            else:
                if self.input_mode.get() == "single":
                    result = run_single_packaged(input_value, output_destination, log=log)
                else:
                    result = run_batch_packaged(input_value, output_destination, log=log)

            log("")
            log("Finishing up…")

            log("Extraction complete.")
            log(f"PDFs processed: {result['pdf_count']}")
            log(f"Total records extracted: {result['total_records']}")
            log(f"Output saved to: {result['delivery_path']}")

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
                f"Extraction complete.\n\nTotal records: {result['total_records']}"
            )

        except Exception as error:
            self.log(f"ERROR: {error}")
            messagebox.showerror("Error", str(error))

        finally:
            self.run_button.config(state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    app = ControlPointApp(root)
    root.mainloop()
