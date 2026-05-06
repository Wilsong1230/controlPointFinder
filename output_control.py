import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEDUPLICATION_FIELDS = ("point", "easting", "northing", "elevation")


def _normalize_numeric(value):
    text = (value or "").strip()

    try:
        normalized = format(Decimal(text).normalize(), "f")
    except (InvalidOperation, ValueError):
        return text

    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")

    return normalized or "0"


def _build_point_key(record):
    return (
        (record.get("point") or "").strip(),
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


def deduplicate_records(records):
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

        _merge_missing_fields(unique_records[existing_index], record)
        duplicates_removed += 1

    return unique_records, duplicates_removed


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
