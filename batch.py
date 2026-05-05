from pathlib import Path

from control_point import run_control_point_pipeline, write_csv


def make_output_csv_path(pdf_path, output_folder):
    csv_name = pdf_path.stem + "_control_points.csv"
    return output_folder / csv_name


def run_batch(input_folder, output_folder):
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)

    output_folder.mkdir(exist_ok=True)

    pdf_paths = sorted(input_folder.glob("*.pdf"))

    results = []
    all_valid_records = []

    for pdf_path in pdf_paths:
        output_csv_path = make_output_csv_path(pdf_path, output_folder)

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

    return {
        "pdf_count": len(pdf_paths),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "total_records": len(all_valid_records),
    }