from pathlib import Path
import json
import tempfile
import zipfile

from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_records, flag_uncertain_duplicates

INDIVIDUAL_CSV_FOLDER = "individual_csvs"
CLEAN_CSV_NAME = "control_points_clean.csv"
REVIEW_CSV_NAME = "needs_review.csv"


def _split_flags(value) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def _review_reasons(record: dict) -> list[str]:
    reasons: list[str] = []

    vstatus = str(record.get("validation_status") or "").strip().lower()
    if vstatus and vstatus != "ok":
        reasons.append(f"validation_status:{vstatus}")

    vflags = _split_flags(record.get("validation_flags"))
    if vflags:
        reasons.extend(vflags)

    cstatus = str(record.get("conversion_status") or "").strip().lower()
    if cstatus.startswith("failed"):
        reasons.append("datum_conversion_failed")
    elif cstatus.startswith("skipped"):
        reasons.append("datum_conversion_skipped")

    dstatus = str(record.get("dedupe_status") or "").strip().lower()
    if dstatus == "uncertain":
        reasons.append("uncertain_duplicate")

    dflags = _split_flags(record.get("dedupe_flags"))
    if dflags:
        reasons.extend(dflags)

    # If confidence is very low, route to review (still exportable if user wants).
    try:
        cs = int(record.get("confidence_score") or 0)
    except (TypeError, ValueError):
        cs = 0
    if cs and cs < 40:
        reasons.append("low_confidence_score")

    # De-dupe while preserving order
    seen = set()
    ordered = []
    for r in reasons:
        if r in seen:
            continue
        seen.add(r)
        ordered.append(r)
    return ordered


def split_clean_vs_review(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Returns (clean, needs_review) and annotates:
      - review_status: "" or "needs_review"
      - review_reason: semicolon-separated reasons
    """
    clean: list[dict] = []
    review: list[dict] = []

    for rec in records:
        reasons = _review_reasons(rec)
        if reasons:
            rec["review_status"] = "needs_review"
            rec["review_reason"] = ";".join(reasons)
            review.append(rec)
        else:
            rec["review_status"] = ""
            rec["review_reason"] = ""
            clean.append(rec)

    return clean, review


def make_output_csv_path(pdf_path, input_folder, individual_output_folder):
    relative_path = pdf_path.relative_to(input_folder)
    safe_name = "_".join(relative_path.with_suffix("").parts)
    csv_name = safe_name + "_control_points.csv"
    return individual_output_folder / csv_name


def run_batch(input_folder, output_folder, log=None, progress=None):
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
        if progress:
            progress({"phase": "start", "current": index, "total": total, "pdf": str(pdf_path)})
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
        finally:
            if progress:
                progress({"phase": "done", "current": index, "total": total, "pdf": str(pdf_path)})

    combined_csv_path = output_folder / "all_control_points.csv"
    clean_csv_path = output_folder / CLEAN_CSV_NAME
    review_csv_path = output_folder / REVIEW_CSV_NAME
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

    clean_records, review_records = split_clean_vs_review(all_valid_records)
    write_csv(clean_records, str(clean_csv_path))
    write_csv(review_records, str(review_csv_path))
    if log:
        log(
            "Deduplication complete. "
            f"Removed {exact_duplicates_removed_total + cross_removed} exact duplicate point(s)."
        )
        log(f"Wrote clean export: {clean_csv_path.name} ({len(clean_records)} row(s))")
        log(f"Wrote needs review: {review_csv_path.name} ({len(review_records)} row(s))")

    return {
        "pdf_count": len(pdf_paths),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "clean_csv": str(clean_csv_path),
        "review_csv": str(review_csv_path),
        "individual_csv_folder": str(individual_output_folder),
        "total_records": len(all_valid_records),
        "clean_records": len(clean_records),
        "review_records": len(review_records),
        "duplicate_points_removed": exact_duplicates_removed_total + cross_removed,
        "found_pdfs": [str(path.relative_to(input_folder)) for path in pdf_paths],
    }


def run_single(pdf_path, output_folder, log=None, progress=None):
    pdf_path = Path(pdf_path)
    output_folder = Path(output_folder)
    individual_output_folder = output_folder / INDIVIDUAL_CSV_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    output_csv_path = individual_output_folder / f"{pdf_path.stem}_control_points.csv"

    if log:
        log(f"Processing: {pdf_path.name}")
        log("  Scanning + extracting control point tables…")
    if progress:
        progress({"phase": "start", "current": 1, "total": 1, "pdf": str(pdf_path)})
    result = run_control_point_pipeline(str(pdf_path), str(output_csv_path), log=log)
    if log:
        log(f"  Done. Found {result['valid_count']} valid record(s).")
        log(f"  Saved per-file CSV: {output_csv_path.name}")
    if progress:
        progress({"phase": "done", "current": 1, "total": 1, "pdf": str(pdf_path)})

    # For single-file runs, the "combined" output is just the one file.
    combined_csv_path = output_folder / "all_control_points.csv"
    clean_csv_path = output_folder / CLEAN_CSV_NAME
    review_csv_path = output_folder / REVIEW_CSV_NAME
    if log:
        log("Combining results into one CSV…")
    records, cross_removed = deduplicate_records(
        result["records"],
        log=log,
        context="combined",
    )
    records = flag_uncertain_duplicates(records, log=log, context="combined")
    write_csv(records, str(combined_csv_path))

    clean_records, review_records = split_clean_vs_review(records)
    write_csv(clean_records, str(clean_csv_path))
    write_csv(review_records, str(review_csv_path))
    if log:
        log(
            "Deduplication complete. "
            f"Removed {int(result.get('exact_duplicates_removed') or 0) + cross_removed} duplicate point(s)."
        )
        log(f"Wrote clean export: {clean_csv_path.name} ({len(clean_records)} row(s))")
        log(f"Wrote needs review: {review_csv_path.name} ({len(review_records)} row(s))")

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
        "clean_csv": str(clean_csv_path),
        "review_csv": str(review_csv_path),
        "individual_csv_folder": str(individual_output_folder),
        "total_records": len(records),
        "clean_records": len(clean_records),
        "review_records": len(review_records),
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


def run_batch_folder(input_folder, output_folder, log=None, progress=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    result = run_batch(input_folder, output_folder, log=log, progress=progress)

    _write_manifest(
        output_folder,
        {
            "mode": "folder",
            "input_folder": str(Path(input_folder).resolve()),
            "summary": {
                "pdf_count": result["pdf_count"],
                "total_records": result["total_records"],
                "clean_records": result.get("clean_records"),
                "review_records": result.get("review_records"),
                "duplicate_points_removed": result["duplicate_points_removed"],
            },
            "files": {
                "combined_csv": Path(result["combined_csv"]).name,
                "clean_csv": Path(result["clean_csv"]).name,
                "needs_review_csv": Path(result["review_csv"]).name,
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


def run_single_folder(pdf_path, output_folder, log=None, progress=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    result = run_single(pdf_path, output_folder, log=log, progress=progress)

    _write_manifest(
        output_folder,
        {
            "mode": "single",
            "input_pdf": str(Path(pdf_path).resolve()),
            "summary": {
                "pdf_count": result["pdf_count"],
                "total_records": result["total_records"],
                "clean_records": result.get("clean_records"),
                "review_records": result.get("review_records"),
                "duplicate_points_removed": result["duplicate_points_removed"],
            },
            "files": {
                "combined_csv": Path(result["combined_csv"]).name,
                "clean_csv": Path(result["clean_csv"]).name,
                "needs_review_csv": Path(result["review_csv"]).name,
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


def run_batch_packaged(input_folder, package_path, log=None, progress=None):
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_batch(input_folder, tmp_output, log=log, progress=progress)

        _write_manifest(
            tmp_output,
            {
                "mode": "folder",
                "input_folder": str(Path(input_folder).resolve()),
                "summary": {
                    "pdf_count": result["pdf_count"],
                    "total_records": result["total_records"],
                    "clean_records": result.get("clean_records"),
                    "review_records": result.get("review_records"),
                    "duplicate_points_removed": result["duplicate_points_removed"],
                },
                "files": {
                    "combined_csv": Path(result["combined_csv"]).name,
                    "clean_csv": Path(result["clean_csv"]).name,
                    "needs_review_csv": Path(result["review_csv"]).name,
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


def run_single_packaged(pdf_path, package_path, log=None, progress=None):
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_single(pdf_path, tmp_output, log=log, progress=progress)

        _write_manifest(
            tmp_output,
            {
                "mode": "single",
                "input_pdf": str(Path(pdf_path).resolve()),
                "summary": {
                    "pdf_count": result["pdf_count"],
                    "total_records": result["total_records"],
                    "clean_records": result.get("clean_records"),
                    "review_records": result.get("review_records"),
                    "duplicate_points_removed": result["duplicate_points_removed"],
                },
                "files": {
                    "combined_csv": Path(result["combined_csv"]).name,
                    "clean_csv": Path(result["clean_csv"]).name,
                    "needs_review_csv": Path(result["review_csv"]).name,
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
