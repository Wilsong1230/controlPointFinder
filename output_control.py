import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional


DEDUPLICATION_FIELDS = ("point", "easting", "northing", "elevation")

LogFn = Optional[Callable[[str], None]]


def _normalize_numeric(value):
    text = (value or "").strip()

    try:
        normalized = format(Decimal(text).normalize(), "f")
    except (InvalidOperation, ValueError):
        return text

    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")

    return normalized or "0"

def _parse_float(value: Any) -> Optional[float]:
    text = _normalize_numeric(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def _point_id(record) -> str:
    return (record.get("point_normalized") or record.get("source_point_id") or record.get("point") or "").strip()


def _build_point_key(record):
    return (
        (_point_id(record) or "").strip(),
        _normalize_numeric(record.get("easting")),
        _normalize_numeric(record.get("northing")),
        _normalize_numeric(record.get("elevation")),
    )


def _merge_missing_fields(existing_record, duplicate_record):
    for field, value in duplicate_record.items():
        if field in DEDUPLICATION_FIELDS:
            continue

        if not existing_record.get(field) and value:
            existing_record[field] = value


def deduplicate_records(records, log: LogFn = None, context: str = ""):
    """
    Exact dedupe only (same point + easting/northing/elevation after numeric normalization).
    Removes duplicates, merges missing non-key fields.
    Logs each removal when log is provided.
    """
    unique_records = []
    seen_keys = {}
    duplicates_removed = 0

    for record in records:
        point_key = _build_point_key(record)
        existing_index = seen_keys.get(point_key)

        if existing_index is None:
            unique_records.append(dict(record))
            seen_keys[point_key] = len(unique_records) - 1
            continue

        if log:
            pt = record.get("point_normalized") or record.get("point") or "?"
            where = f" ({context})" if context else ""
            log(f"  Deduped exact duplicate{where}: point {pt} on page {record.get('source_page')}")

        _merge_missing_fields(unique_records[existing_index], record)
        duplicates_removed += 1

    return unique_records, duplicates_removed


def flag_uncertain_duplicates(
    records,
    *,
    horizontal_tolerance_ft: float = 1.0,
    vertical_tolerance_ft: float = 0.5,
    log: LogFn = None,
    context: str = "",
):
    """
    Does NOT remove rows. Flags "uncertain duplicates" for user review.

    Heuristic:
    - Same point id (point_normalized if present, else point)
    - Coordinates are present and within tolerances, but not an exact-match key
    """
    groups = {}
    for idx, rec in enumerate(records):
        pid = _point_id(rec)
        if not pid:
            continue
        groups.setdefault(pid, []).append(idx)

    group_id = 0
    for pid, indices in groups.items():
        if len(indices) < 2:
            continue

        # Compare all pairs; for small N this is fine.
        for i in range(len(indices)):
            a = records[indices[i]]
            ea = _parse_float(a.get("easting"))
            na = _parse_float(a.get("northing"))
            za = _parse_float(a.get("elevation"))
            if ea is None or na is None:
                continue

            for j in range(i + 1, len(indices)):
                b = records[indices[j]]
                eb = _parse_float(b.get("easting"))
                nb = _parse_float(b.get("northing"))
                zb = _parse_float(b.get("elevation"))
                if eb is None or nb is None:
                    continue

                # Skip exact duplicates (handled elsewhere)
                if _build_point_key(a) == _build_point_key(b):
                    continue

                if abs(ea - eb) <= horizontal_tolerance_ft and abs(na - nb) <= horizontal_tolerance_ft:
                    if za is not None and zb is not None and abs(za - zb) > vertical_tolerance_ft:
                        continue

                    group_id += 1
                    gid = f"U{group_id}"

                    for rec in (a, b):
                        rec["dedupe_status"] = "uncertain"
                        existing = (rec.get("dedupe_flags") or "").strip()
                        flags = [f for f in existing.split(";") if f] if existing else []
                        if "possible_uncertain_duplicate" not in flags:
                            flags.append("possible_uncertain_duplicate")
                        rec["dedupe_flags"] = ";".join(flags)
                        rec["dedupe_group_id"] = rec.get("dedupe_group_id") or gid

                    if log:
                        where = f" ({context})" if context else ""
                        log(
                            f"  Uncertain duplicate{where}: point {pid} "
                            f"(pages {a.get('source_page')} vs {b.get('source_page')})"
                        )

    return records


def deduplicate_output_csv(csv_path):
    csv_path = Path(csv_path)

    with csv_path.open("r", newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        fieldnames = reader.fieldnames or []
        records = list(reader)

    unique_records, duplicates_removed = deduplicate_records(records)

    with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_records)

    return {
        "csv_path": str(csv_path),
        "original_count": len(records),
        "unique_count": len(unique_records),
        "duplicates_removed": duplicates_removed,
    }


ARCGIS_CSV_FIELDS = ["point_id", "x", "y", "elevation", "description", "source_pdf"]


def write_arcgis_csv(records: list[dict], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ARCGIS_CSV_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "point_id": rec.get("system_point_id") or rec.get("point") or "",
                "x": rec.get("easting") or "",
                "y": rec.get("northing") or "",
                "elevation": rec.get("elevation") or "",
                "description": rec.get("description") or "",
                "source_pdf": rec.get("source_pdf") or "",
            })
