from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_records, flag_uncertain_duplicates
from pathlib import Path
import csv

INPUT_FOLDER = Path("input_pdfs")
OUTPUT_FOLDER = Path("outputs")
INDIVIDUAL_CSV_FOLDER = "individual_csvs"

def make_output_csv_path(pdf_path, individual_output_folder):
    relative_path = pdf_path.relative_to(INPUT_FOLDER)

    safe_name = "_".join(relative_path.with_suffix("").parts)
    csv_name = safe_name + "_control_points.csv"

    return individual_output_folder / csv_name

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
    individual_output_folder = OUTPUT_FOLDER / INDIVIDUAL_CSV_FOLDER

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(INPUT_FOLDER.rglob("*.pdf"))

    if not pdf_paths:
        print(f"No PDFs found in {INPUT_FOLDER}")
        return

    print(f"Found {len(pdf_paths)} PDF(s).")
    print("-" * 40)

    results = []
    all_valid_records = []
    exact_duplicates_removed_total = 0

    for pdf_path in pdf_paths:
        print()
        print(f"Processing: {pdf_path.name}")

        output_csv_path = make_output_csv_path(pdf_path, individual_output_folder)

        try:
            result = run_control_point_pipeline(
                str(pdf_path),
                str(output_csv_path)
            )

            all_valid_records.extend(result["records"])
            exact_duplicates_removed_total += int(result.get("exact_duplicates_removed") or 0)

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
    all_valid_records, cross_removed = deduplicate_records(all_valid_records, log=None, context="combined")
    all_valid_records = flag_uncertain_duplicates(all_valid_records, log=None, context="combined")
    write_csv(all_valid_records, str(combined_csv_path))
    removed_total = exact_duplicates_removed_total + cross_removed
    print(f"Wrote combined CSV: {combined_csv_path}")
    print(f"Wrote individual CSVs to: {individual_output_folder}")
    print(
        "Removed "
        f"{removed_total} duplicate point(s). "
        f"Final total: {len(all_valid_records)}"
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
