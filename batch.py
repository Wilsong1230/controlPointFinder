from pathlib import Path
import json
import tempfile
import zipfile

from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_records, flag_uncertain_duplicates

INDIVIDUAL_CSV_FOLDER = "individual_csvs"


def make_output_csv_path(pdf_path, input_folder, individual_output_folder):
    relative_path = pdf_path.relative_to(input_folder)
    safe_name = "_".join(relative_path.with_suffix("").parts)
    csv_name = safe_name + "_control_points.csv"
    return individual_output_folder / csv_name


def run_batch(input_folder, output_folder, log=None):
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)
    individual_output_folder = output_folder / INDIVIDUAL_CSV_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(
    path for path in input_folder.rglob("*")
    if path.is_file() and path.suffix.lower() == ".pdf"
)

    if log:
        log(f"Searching for PDFs in: {input_folder}")
        log(f"Found {len(pdf_paths)} PDF(s).")

    results = []
    all_valid_records = []
    exact_duplicates_removed_total = 0

    total = len(pdf_paths)
    for index, pdf_path in enumerate(pdf_paths, start=1):
        if log:
            log("")
            log(f"[{index}/{total}] Processing: {pdf_path.name}")
            log("  Scanning + extracting control point tables…")
        output_csv_path = make_output_csv_path(
            pdf_path,
            input_folder,
            individual_output_folder
        )

        # rest of your loop...
        try:
            result = run_control_point_pipeline(
                str(pdf_path),
                str(output_csv_path),
                log=log
            )

            all_valid_records.extend(result["records"])
            exact_duplicates_removed_total += int(result.get("exact_duplicates_removed") or 0)
            if log:
                log(f"  Done. Found {result['valid_count']} valid record(s).")
                log(f"  Saved per-file CSV: {output_csv_path.name}")

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
            if log:
                log(f"  Failed: {error}")
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
    if log:
        log("")
        log("Combining results into one CSV…")
    # Deduplicate across PDFs before writing combined output.
    all_valid_records, cross_removed = deduplicate_records(
        all_valid_records,
        log=log,
        context="combined",
    )
    all_valid_records = flag_uncertain_duplicates(all_valid_records, log=log, context="combined")
    write_csv(all_valid_records, str(combined_csv_path))
    if log:
        log(
            "Deduplication complete. "
            f"Removed {exact_duplicates_removed_total + cross_removed} exact duplicate point(s)."
        )

    return {
        "pdf_count": len(pdf_paths),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "individual_csv_folder": str(individual_output_folder),
        "total_records": len(all_valid_records),
        "duplicate_points_removed": exact_duplicates_removed_total + cross_removed,
        "found_pdfs": [str(path.relative_to(input_folder)) for path in pdf_paths],
    }


def run_single(pdf_path, output_folder, log=None):
    pdf_path = Path(pdf_path)
    output_folder = Path(output_folder)
    individual_output_folder = output_folder / INDIVIDUAL_CSV_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    output_csv_path = individual_output_folder / f"{pdf_path.stem}_control_points.csv"

    if log:
        log(f"Processing: {pdf_path.name}")
        log("  Scanning + extracting control point tables…")
    result = run_control_point_pipeline(str(pdf_path), str(output_csv_path), log=log)
    if log:
        log(f"  Done. Found {result['valid_count']} valid record(s).")
        log(f"  Saved per-file CSV: {output_csv_path.name}")

    # For single-file runs, the "combined" output is just the one file.
    combined_csv_path = output_folder / "all_control_points.csv"
    if log:
        log("Combining results into one CSV…")
    records, cross_removed = deduplicate_records(
        result["records"],
        log=log,
        context="combined",
    )
    records = flag_uncertain_duplicates(records, log=log, context="combined")
    write_csv(records, str(combined_csv_path))
    if log:
        log(
            "Deduplication complete. "
            f"Removed {int(result.get('exact_duplicates_removed') or 0) + cross_removed} duplicate point(s)."
        )

    return {
        "pdf_count": 1,
        "results": [{
            "pdf": pdf_path.name,
            "output_csv": str(output_csv_path),
            "extraction_pages": result["extraction_pages"],
            "reference_pages": result["reference_pages"],
            "parsed_count": result["parsed_count"],
            "valid_count": result["valid_count"],
            "status": "success",
        }],
        "combined_csv": str(combined_csv_path),
        "individual_csv_folder": str(individual_output_folder),
        "total_records": len(records),
        "duplicate_points_removed": int(result.get("exact_duplicates_removed") or 0) + cross_removed,
        "found_pdfs": [pdf_path.name],
    }


def _zip_directory(source_dir, zip_path):
    source_dir = Path(source_dir)
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(source_dir)
            zf.write(path, arcname)


def _unique_path(path):
    path = Path(path)
    if not path.exists():
        return path

    if path.suffix:
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        for i in range(1, 10_000):
            candidate = parent / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"Could not find unique path for {path}")

    parent = path.parent
    name = path.name
    for i in range(1, 10_000):
        candidate = parent / f"{name}_{i}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find unique path for {path}")


def _write_manifest(output_dir, manifest):
    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_batch_folder(input_folder, output_folder, log=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    result = run_batch(input_folder, output_folder, log=log)

    _write_manifest(
        output_folder,
        {
            "mode": "folder",
            "input_folder": str(Path(input_folder).resolve()),
            "summary": {
                "pdf_count": result["pdf_count"],
                "total_records": result["total_records"],
                "duplicate_points_removed": result["duplicate_points_removed"],
            },
            "files": {
                "combined_csv": Path(result["combined_csv"]).name,
                "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
            },
            "found_pdfs": result["found_pdfs"],
            "results": result["results"],
        },
    )

    return {
        **result,
        "delivery_path": str(output_folder),
    }


def run_single_folder(pdf_path, output_folder, log=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    result = run_single(pdf_path, output_folder, log=log)

    _write_manifest(
        output_folder,
        {
            "mode": "single",
            "input_pdf": str(Path(pdf_path).resolve()),
            "summary": {
                "pdf_count": result["pdf_count"],
                "total_records": result["total_records"],
                "duplicate_points_removed": result["duplicate_points_removed"],
            },
            "files": {
                "combined_csv": Path(result["combined_csv"]).name,
                "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
            },
            "found_pdfs": result["found_pdfs"],
            "results": result["results"],
        },
    )

    return {
        **result,
        "delivery_path": str(output_folder),
    }


def run_batch_packaged(input_folder, package_path, log=None):
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_batch(input_folder, tmp_output, log=log)

        _write_manifest(
            tmp_output,
            {
                "mode": "folder",
                "input_folder": str(Path(input_folder).resolve()),
                "summary": {
                    "pdf_count": result["pdf_count"],
                    "total_records": result["total_records"],
                    "duplicate_points_removed": result["duplicate_points_removed"],
                },
                "files": {
                    "combined_csv": Path(result["combined_csv"]).name,
                    "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
                },
                "found_pdfs": result["found_pdfs"],
                "results": result["results"],
            },
        )

        package_path = _unique_path(package_path)
        _zip_directory(tmp_output, package_path)

    return {
        **result,
        "delivery_path": str(package_path),
    }


def run_single_packaged(pdf_path, package_path, log=None):
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_single(pdf_path, tmp_output, log=log)

        _write_manifest(
            tmp_output,
            {
                "mode": "single",
                "input_pdf": str(Path(pdf_path).resolve()),
                "summary": {
                    "pdf_count": result["pdf_count"],
                    "total_records": result["total_records"],
                    "duplicate_points_removed": result["duplicate_points_removed"],
                },
                "files": {
                    "combined_csv": Path(result["combined_csv"]).name,
                    "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
                },
                "found_pdfs": result["found_pdfs"],
                "results": result["results"],
            },
        )

        package_path = _unique_path(package_path)
        _zip_directory(tmp_output, package_path)

    return {
        **result,
        "delivery_path": str(package_path),
    }
