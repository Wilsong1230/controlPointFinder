from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_output_csv
from pathlib import Path
import csv

INPUT_FOLDER = Path("input_pdfs")
OUTPUT_FOLDER = Path("outputs")

def make_output_csv_path(pdf_path):
    relative_path = pdf_path.relative_to(INPUT_FOLDER)

    safe_name = "_".join(relative_path.with_suffix("").parts)
    csv_name = safe_name + "_control_points.csv"

    return OUTPUT_FOLDER / csv_name

def write_batch_report(results, output_folder):
    report_path = output_folder / "batch_report.csv"

    fieldnames = [
        "pdf",
        "status",
        "valid_count",
        "parsed_count",
        "extraction_pages",
        "reference_pages",
        "output_csv",
    ]

    with open(report_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow({
                "pdf": result["pdf"],
                "status": result["status"],
                "valid_count": result["valid_count"],
                "parsed_count": result["parsed_count"],
                "extraction_pages": result["extraction_pages"],
                "reference_pages": result["reference_pages"],
                "output_csv": result["output_csv"],
            })

    print(f"Wrote batch report: {report_path}")

def main():
    OUTPUT_FOLDER.mkdir(exist_ok=True)

    pdf_paths = sorted(INPUT_FOLDER.rglob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {INPUT_FOLDER}")
        return

    print(f"Found {len(pdf_paths)} PDF(s).")
    print("-" * 40)

    results = []
    all_valid_records = []

    for pdf_path in pdf_paths:
        print()
        print(f"Processing: {pdf_path.name}")

        output_csv_path = make_output_csv_path(pdf_path)

        try:
            result = run_control_point_pipeline(
                str(pdf_path),
                str(output_csv_path)
            )

            all_valid_records.extend(result["records"])

            results.append({
                "pdf": pdf_path.name,
                "output_csv": str(output_csv_path),
                "extraction_pages": result["extraction_pages"],
                "reference_pages": result["reference_pages"],
                "parsed_count": result["parsed_count"],
                "valid_count": result["valid_count"],
                "status": "success",
            })

            print(f"Finished: {pdf_path.name}")
            print(f"Valid records: {result['valid_count']}")
            print(f"Wrote: {output_csv_path}")

        except Exception as error:
            results.append({
                "pdf": pdf_path.name,
                "output_csv": "",
                "extraction_pages": [],
                "reference_pages": [],
                "parsed_count": 0,
                "valid_count": 0,
                "status": f"failed: {error}",
            })

            print(f"Failed: {pdf_path.name}")
            print(error)

    combined_csv_path = OUTPUT_FOLDER / "all_control_points.csv"
    write_csv(all_valid_records, str(combined_csv_path))
    deduplication_result = deduplicate_output_csv(combined_csv_path)
    print(f"Wrote combined CSV: {combined_csv_path}")
    print(
        "Removed "
        f"{deduplication_result['duplicates_removed']} duplicate point(s). "
        f"Final total: {deduplication_result['unique_count']}"
    )

    print()
    print("Batch Summary")
    print("-" * 40)

    for result in results:
        print(
            f"{result['pdf']} | "
            f"{result['status']} | "
            f"{result['valid_count']} records | "
            f"pages {result['extraction_pages']}"
        )
    write_batch_report(results, OUTPUT_FOLDER)


if __name__ == "__main__":
    main()
