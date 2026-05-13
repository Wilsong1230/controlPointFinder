from pathlib import Path
from datetime import datetime, timezone
import json
import tempfile
import zipfile

from control_point import run_control_point_pipeline, write_csv
from output_control import deduplicate_records, flag_uncertain_duplicates, write_arcgis_csv

INDIVIDUAL_CSV_FOLDER = "individual_csvs"
CLEAN_CSV_NAME = "control_points_navd88.csv"
REVIEW_CSV_NAME = "needs_review.csv"
LOG_TXT_NAME = "extraction_log.txt"
SUMMARY_TXT_NAME = "extraction_summary.txt"
ARCGIS_CSV_NAME = "arcgis_points.csv"


def _split_flags(value) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def _split_low_confidence(records: list[dict]) -> tuple[list[dict], list[dict]]:
    low_conf = [r for r in records if r.get("confidence_level") == "low"]
    other = [r for r in records if r.get("confidence_level") != "low"]
    return low_conf, other


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


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tee_logger(output_folder: Path, log=None):
    """
    Returns (tee_log_fn, get_lines, log_path).
    tee_log_fn writes to output_folder/extraction_log.txt and forwards to `log`.
    """
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    log_path = output_folder / LOG_TXT_NAME
    lines: list[str] = []

    def tee(message: str):
        msg = str(message)
        lines.append(msg)
        log_path.open("a", encoding="utf-8").write(msg + "\n")
        if log:
            log(msg)

    # Start fresh for each run folder.
    log_path.write_text("", encoding="utf-8")
    return tee, (lambda: list(lines)), str(log_path)


def _write_summary(output_folder: Path, result: dict, started_at: str, ended_at: str) -> str:
    output_folder = Path(output_folder)
    summary_path = output_folder / SUMMARY_TXT_NAME
    failed = sum(1 for r in (result.get("results") or []) if str(r.get("status") or "").startswith("failed"))
    text = "\n".join(
        [
            "Control Point Extraction Summary",
            "--------------------------------",
            f"Started (UTC): {started_at}",
            f"Ended (UTC):   {ended_at}",
            f"PDFs processed: {result.get('pdf_count')}",
            f"Total rows (combined): {result.get('total_records')}",
            f"Clean export rows: {result.get('clean_records')}",
            f"Needs review rows: {result.get('review_records')}",
            f"Duplicate points removed: {result.get('duplicate_points_removed')}",
            f"Failed PDFs: {failed}",
            "",
            "Outputs:",
            f"- {Path(result.get('clean_csv') or CLEAN_CSV_NAME).name}",
            f"- {Path(result.get('review_csv') or REVIEW_CSV_NAME).name}",
            f"- {Path(result.get('combined_csv') or 'all_control_points.csv').name}",
            f"- {ARCGIS_CSV_NAME}",
            f"- {LOG_TXT_NAME}",
            "",
        ]
    )
    summary_path.write_text(text, encoding="utf-8")
    return str(summary_path)


def _run_pdf_list(
    pdf_paths: list[Path],
    *,
    output_folder: Path,
    log=None,
    progress=None,
    context_label: str = "",
    review_request_q=None,
    review_result_q=None,
):
    """
    Shared runner for folder mode and multi-select mode.
    """
    output_folder = Path(output_folder)
    individual_output_folder = output_folder / INDIVIDUAL_CSV_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    individual_output_folder.mkdir(parents=True, exist_ok=True)

    tee_log, get_log_lines, log_path = _tee_logger(output_folder, log=log)
    started_at = _utc_iso_now()

    if tee_log:
        if context_label:
            tee_log(context_label)
        tee_log(f"Found {len(pdf_paths)} PDF(s).")

    results = []
    all_valid_records = []
    exact_duplicates_removed_total = 0

    total = len(pdf_paths)
    for index, pdf_path in enumerate(pdf_paths, start=1):
        if progress:
            progress({"phase": "start", "current": index, "total": total, "pdf": str(pdf_path)})
        if tee_log:
            tee_log("")
            tee_log(f"[{index}/{total}] Processing: {pdf_path.name}")
            tee_log("  Scanning + extracting control point tables…")

        output_csv_path = individual_output_folder / f"{pdf_path.stem}_control_points.csv"

        # rest of your loop...
        try:
            result = run_control_point_pipeline(
                str(pdf_path),
                str(output_csv_path),
                log=tee_log
            )

            all_valid_records.extend(result["records"])
            exact_duplicates_removed_total += int(result.get("exact_duplicates_removed") or 0)
            if tee_log:
                tee_log(f"  Done. Found {result['valid_count']} valid record(s).")
                tee_log(f"  Saved per-file CSV: {output_csv_path.name}")

            results.append({
                "pdf": str(pdf_path),
                "output_csv": str(output_csv_path),
                "extraction_pages": result["extraction_pages"],
                "reference_pages": result["reference_pages"],
                "parsed_count": result["parsed_count"],
                "valid_count": result["valid_count"],
                "status": "success",
            })

        except Exception as error:
            if tee_log:
                tee_log(f"  Failed: {error}")
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
    arcgis_csv_path = output_folder / ARCGIS_CSV_NAME

    if tee_log:
        tee_log("")
        tee_log("Combining results into one CSV…")

    all_valid_records, cross_removed = deduplicate_records(
        all_valid_records, log=tee_log, context="combined",
    )
    all_valid_records = flag_uncertain_duplicates(all_valid_records, log=tee_log, context="combined")

    # --- Review gate ---
    low_conf, other_records = _split_low_confidence(all_valid_records)

    if low_conf and review_request_q is not None and review_result_q is not None:
        if tee_log:
            tee_log(f"  Found {len(low_conf)} low-confidence record(s) — sending to review modal…")
        pdf_path_map = {p.name: str(p) for p in pdf_paths}
        review_request_q.put({"low_conf": low_conf, "pdf_path_map": pdf_path_map})
        modal_result = review_result_q.get(timeout=600)
        accepted_from_modal = modal_result["accepted"]
        skipped_from_modal = modal_result["skipped"]
        for rec in skipped_from_modal:
            rec["review_status"] = "needs_review"
            rec["review_reason"] = "skipped_in_modal_review"
        if tee_log:
            tee_log(
                f"  Modal review done: {len(accepted_from_modal)} accepted, "
                f"{len(skipped_from_modal)} skipped."
            )
    else:
        accepted_from_modal = low_conf
        skipped_from_modal = []

    merged = other_records + accepted_from_modal
    clean_records, auto_review_records = split_clean_vs_review(merged)
    review_records = auto_review_records + skipped_from_modal

    write_csv(clean_records + review_records, str(combined_csv_path))
    write_csv(clean_records, str(clean_csv_path))
    write_csv(review_records, str(review_csv_path))
    write_arcgis_csv(clean_records, str(arcgis_csv_path))

    if tee_log:
        tee_log(
            "Deduplication complete. "
            f"Removed {exact_duplicates_removed_total + cross_removed} exact duplicate point(s)."
        )
        tee_log(f"Wrote clean export: {clean_csv_path.name} ({len(clean_records)} row(s))")
        tee_log(f"Wrote needs review: {review_csv_path.name} ({len(review_records)} row(s))")
        tee_log(f"Wrote ArcGIS CSV:   {arcgis_csv_path.name} ({len(clean_records)} row(s))")

    ended_at = _utc_iso_now()
    summary_path = _write_summary(output_folder, {
        "pdf_count": len(pdf_paths),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "clean_csv": str(clean_csv_path),
        "review_csv": str(review_csv_path),
        "arcgis_csv": str(arcgis_csv_path),
        "total_records": len(clean_records) + len(review_records),
        "clean_records": len(clean_records),
        "review_records": len(review_records),
        "duplicate_points_removed": exact_duplicates_removed_total + cross_removed,
    }, started_at=started_at, ended_at=ended_at)

    return {
        "pdf_count": len(pdf_paths),
        "results": results,
        "combined_csv": str(combined_csv_path),
        "clean_csv": str(clean_csv_path),
        "review_csv": str(review_csv_path),
        "arcgis_csv": str(arcgis_csv_path),
        "log_txt": log_path,
        "summary_txt": summary_path,
        "individual_csv_folder": str(individual_output_folder),
        "total_records": len(clean_records) + len(review_records),
        "clean_records": len(clean_records),
        "review_records": len(review_records),
        "duplicate_points_removed": exact_duplicates_removed_total + cross_removed,
        "found_pdfs": [str(path) for path in pdf_paths],
    }


def _process_single_pdf(args: tuple) -> dict:
    """Picklable worker for ProcessPoolExecutor. No callbacks — returns result dict."""
    pdf_path_str, output_csv_path_str = args
    from control_point import run_control_point_pipeline
    try:
        result = run_control_point_pipeline(pdf_path_str, output_csv_path_str, log=None)
        return {"ok": True, "result": result, "pdf_path": pdf_path_str, "output_csv": output_csv_path_str}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "pdf_path": pdf_path_str, "output_csv": output_csv_path_str}


def run_batch(input_folder, output_folder, log=None, progress=None,
              review_request_q=None, review_result_q=None):
    input_folder = Path(input_folder)
    pdf_paths = sorted(
        path for path in input_folder.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )
    return _run_pdf_list(
        pdf_paths,
        output_folder=Path(output_folder),
        log=log,
        progress=progress,
        context_label=f"Searching for PDFs in: {input_folder}",
        review_request_q=review_request_q,
        review_result_q=review_result_q,
    )


def run_multi(pdf_paths: list[str | Path], output_folder, log=None, progress=None,
              review_request_q=None, review_result_q=None):
    paths = [Path(p) for p in (pdf_paths or [])]
    paths = [p for p in paths if p.is_file() and p.suffix.lower() == ".pdf"]
    paths = sorted(paths)
    return _run_pdf_list(
        paths,
        output_folder=Path(output_folder),
        log=log,
        progress=progress,
        context_label="Processing selected PDFs…",
        review_request_q=review_request_q,
        review_result_q=review_result_q,
    )


def run_single(pdf_path, output_folder, log=None, progress=None,
               review_request_q=None, review_result_q=None):
    pdf_path = Path(pdf_path)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    return _run_pdf_list(
        [pdf_path],
        output_folder=output_folder,
        log=log,
        progress=progress,
        context_label=f"Processing: {pdf_path.name}",
        review_request_q=review_request_q,
        review_result_q=review_result_q,
    )


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


def run_batch_folder(input_folder, output_folder, log=None, progress=None,
                     review_request_q=None, review_result_q=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    result = run_batch(input_folder, output_folder, log=log, progress=progress,
                       review_request_q=review_request_q, review_result_q=review_result_q)
    _write_manifest(output_folder, {
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
            "arcgis_csv": ARCGIS_CSV_NAME,
            "log_txt": Path(result.get("log_txt") or LOG_TXT_NAME).name,
            "summary_txt": Path(result.get("summary_txt") or SUMMARY_TXT_NAME).name,
            "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
        },
        "found_pdfs": result["found_pdfs"],
        "results": result["results"],
    })
    return {**result, "delivery_path": str(output_folder)}


def run_single_folder(pdf_path, output_folder, log=None, progress=None,
                      review_request_q=None, review_result_q=None):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    result = run_single(pdf_path, output_folder, log=log, progress=progress,
                        review_request_q=review_request_q, review_result_q=review_result_q)
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
                "arcgis_csv": ARCGIS_CSV_NAME,
                "log_txt": Path(result.get("log_txt") or LOG_TXT_NAME).name,
                "summary_txt": Path(result.get("summary_txt") or SUMMARY_TXT_NAME).name,
                "individual_csv_folder": INDIVIDUAL_CSV_FOLDER + "/",
            },
            "found_pdfs": result["found_pdfs"],
            "results": result["results"],
        },
    )
    return {**result, "delivery_path": str(output_folder)}


def run_batch_packaged(input_folder, package_path, log=None, progress=None,
                       review_request_q=None, review_result_q=None):
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_batch(input_folder, tmp_output, log=log, progress=progress,
                           review_request_q=review_request_q, review_result_q=review_result_q)

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
                    "arcgis_csv": ARCGIS_CSV_NAME,
                    "log_txt": Path(result.get("log_txt") or LOG_TXT_NAME).name,
                    "summary_txt": Path(result.get("summary_txt") or SUMMARY_TXT_NAME).name,
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


def run_single_packaged(pdf_path, package_path, log=None, progress=None,
                        review_request_q=None, review_result_q=None):
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_single(pdf_path, tmp_output, log=log, progress=progress,
                            review_request_q=review_request_q, review_result_q=review_result_q)

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
                    "arcgis_csv": ARCGIS_CSV_NAME,
                    "log_txt": Path(result.get("log_txt") or LOG_TXT_NAME).name,
                    "summary_txt": Path(result.get("summary_txt") or SUMMARY_TXT_NAME).name,
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


def run_multi_packaged(pdf_paths: list[str | Path], package_path, log=None, progress=None,
                       review_request_q=None, review_result_q=None):
    """
    Multi-select equivalent of run_batch_packaged/run_single_packaged.
    Creates a normal output folder in a temp dir and zips it.
    """
    package_path = Path(package_path)

    with tempfile.TemporaryDirectory(prefix="control_point_outputs_") as tmpdir:
        tmp_output = Path(tmpdir)
        result = run_multi(pdf_paths, tmp_output, log=log, progress=progress,
                           review_request_q=review_request_q, review_result_q=review_result_q)

        _write_manifest(
            tmp_output,
            {
                "mode": "multi",
                "input_pdfs": [str(Path(p).resolve()) for p in (pdf_paths or [])],
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
                    "arcgis_csv": ARCGIS_CSV_NAME,
                    "log_txt": Path(result.get("log_txt") or LOG_TXT_NAME).name,
                    "summary_txt": Path(result.get("summary_txt") or SUMMARY_TXT_NAME).name,
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
