import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from batch import run_batch, run_single


class ControlPointApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Control Point Extractor")
        self.root.geometry("700x500")

        self.input_mode = tk.StringVar(value="folder")  # "folder" | "single"
        self.input_path = tk.StringVar()
        self.output_folder = tk.StringVar()

        self.build_ui()

    def build_ui(self):
        title = tk.Label(
            self.root,
            text="Control Point PDF Extractor",
            font=("Arial", 18, "bold")
        )
        title.pack(pady=10)

        input_frame = tk.Frame(self.root)
        input_frame.pack(fill="x", padx=20, pady=5)

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

        output_frame = tk.Frame(self.root)
        output_frame.pack(fill="x", padx=20, pady=5)

        tk.Label(output_frame, text="Output Folder:").pack(anchor="w")

        output_row = tk.Frame(output_frame)
        output_row.pack(fill="x")

        tk.Entry(output_row, textvariable=self.output_folder).pack(
            side="left",
            fill="x",
            expand=True
        )

        tk.Button(
            output_row,
            text="Browse",
            command=self.select_output_folder
        ).pack(side="left", padx=5)

        self.run_button = tk.Button(
            self.root,
            text="Run Extraction",
            command=self.run_extraction,
            height=2
        )
        self.run_button.pack(pady=15)

        self.log_box = scrolledtext.ScrolledText(self.root, height=15)
        self.log_box.pack(fill="both", expand=True, padx=20, pady=10)

    def on_mode_change(self):
        mode = self.input_mode.get()
        self.input_path.set("")

        if mode == "single":
            self.input_label.config(text="PDF File:")
        else:
            self.input_label.config(text="PDF Folder:")

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

            # Default output folder inside selected folder
            base = Path(chosen).parent if mode == "single" else Path(chosen)
            default_output = base / "control_point_outputs"
            self.output_folder.set(str(default_output))

    def select_output_folder(self):
        folder = filedialog.askdirectory(title="Select output folder")

        if folder:
            self.output_folder.set(folder)

    def log(self, message):
        self.log_box.insert(tk.END, message + "\n")
        self.log_box.see(tk.END)
        self.root.update_idletasks()

    def run_extraction(self):
        input_value = self.input_path.get()
        output_folder = self.output_folder.get()

        if not input_value:
            if self.input_mode.get() == "single":
                messagebox.showerror("Missing PDF", "Please select a PDF file.")
            else:
                messagebox.showerror("Missing Folder", "Please select a PDF folder.")
            return

        if not output_folder:
            messagebox.showerror("Missing Output", "Please select an output folder.")
            return

        self.run_button.config(state="disabled")
        self.log_box.delete("1.0", tk.END)
        self.log("Starting extraction...")

        thread = threading.Thread(
            target=self.run_extraction_thread,
            args=(input_value, output_folder)
        )
        thread.start()

    def run_extraction_thread(self, input_value, output_folder):
        try:
            if self.input_mode.get() == "single":
                result = run_single(input_value, output_folder)
            else:
                result = run_batch(input_value, output_folder)

            self.log("PDFs found:")
            for pdf in result["found_pdfs"]:
                self.log(f" - {pdf}")

            self.log("")
            self.log("Extraction complete.")
            self.log(f"PDFs processed: {result['pdf_count']}")
            self.log(f"Total records extracted: {result['total_records']}")
            self.log(f"Combined CSV: {result['combined_csv']}")
            self.log(f"Individual CSV folder: {result['individual_csv_folder']}")

            self.log("")
            self.log("Per-file results:")

            for item in result["results"]:
                self.log(
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
