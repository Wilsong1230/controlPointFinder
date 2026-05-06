from pathlib import Path

from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_output_csv

INDIVIDUAL_CSV_FOLDER = "individual_csvs"


def make_output_csv_path(pdf_path, input_folder, individual_output_folder):
    relative_path = pdf_path.relative_to(input_folder)
    safe_name = "_".join(relative_path.with_suffix("").parts)
    csv_name = safe_name + "_control_points.csv"
    return individual_output_folder / csv_name


def run_batch(input_folder, output_folder):
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)
    individual_output_folder = output_folder / INDIVIDUAL_CSV_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(
    path for path in input_folder.rglob("*")
    if path.is_file() and path.suffix.lower() == ".pdf"
)

    print(f"Searching recursively in: {input_folder}")
    print(f"Found {len(pdf_paths)} PDFs:")

    for pdf_path in pdf_paths:
        print(f" - {pdf_path}")

    results = []
    all_valid_records = []

    for pdf_path in pdf_paths:
        output_csv_path = make_output_csv_path(
            pdf_path,
            input_folder,
            individual_output_folder
        )

        # rest of your loop...
        try:
            result = run_control_point_pipeline(
                str(pdf_path),
                str(output_csv_path)
            )

            all_valid_records.extend(result["records"])

            results.append({
                "pdf": str(pdf_path.relative_to(input_folder)),
                "output_csv": str(output_csv_path),
                "extraction_pages": result["extraction_pages"],
                "reference_pages": result["reference_pages"],
                "parsed_count": result["parsed_count"],
                "valid_count": result["valid_count"],
                "status": "success",
            })

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

    combined_csv_path = output_folder / "all_control_points.csv"
    write_csv(all_valid_records, str(combined_csv_path))
    deduplication_result = deduplicate_output_csv(combined_csv_path)

    return {
        "pdf_count": len(pdf_paths),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "individual_csv_folder": str(individual_output_folder),
        "total_records": deduplication_result["unique_count"],
        "duplicate_points_removed": deduplication_result["duplicates_removed"],
        "found_pdfs": [str(path.relative_to(input_folder)) for path in pdf_paths],
    }
