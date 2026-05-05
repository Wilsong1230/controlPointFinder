import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from batch import run_batch


class ControlPointApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Control Point Extractor")
        self.root.geometry("700x500")

        self.input_folder = tk.StringVar()
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

        tk.Label(input_frame, text="PDF Folder:").pack(anchor="w")

        input_row = tk.Frame(input_frame)
        input_row.pack(fill="x")

        tk.Entry(input_row, textvariable=self.input_folder).pack(
            side="left",
            fill="x",
            expand=True
        )

        tk.Button(
            input_row,
            text="Browse",
            command=self.select_input_folder
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

    def select_input_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing PDFs")

        if folder:
            self.input_folder.set(folder)

            # Default output folder inside selected folder
            default_output = Path(folder) / "control_point_outputs"
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
        input_folder = self.input_folder.get()
        output_folder = self.output_folder.get()

        if not input_folder:
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
            args=(input_folder, output_folder)
        )
        thread.start()

    def run_extraction_thread(self, input_folder, output_folder):
        try:
            result = run_batch(input_folder, output_folder)

            self.log("")
            self.log("Extraction complete.")
            self.log(f"PDFs processed: {result['pdf_count']}")
            self.log(f"Total records extracted: {result['total_records']}")
            self.log(f"Combined CSV: {result['combined_csv']}")

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