import csv
import fitz
import pdfplumber
import re
from pathlib import Path

from datum_standardization import standardize_records
from data_validation import validate_and_normalize_records
from output_control import deduplicate_records, flag_uncertain_duplicates
from point_id import assign_system_point_ids


PDF_PATH = "sample.pdf"


def extract_project_metadata(pdf_path):
    metadata = {
        "horizontal_datum": "",
        "vertical_datum": "",
        "coordinate_system": "",
        "metadata_pages": [],
        "evidence": [],
    }

    doc = fitz.open(pdf_path)

    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text("text") or ""
        lower_text = text.lower()
        page_number = page_index + 1

        if (
            "datum" not in lower_text
            and "ngvd" not in lower_text
            and "navd" not in lower_text
            and "nad" not in lower_text
            and "state plane" not in lower_text
        ):
            continue

        metadata["metadata_pages"].append(page_number)

        lines = text.splitlines()

        for line in lines:
            lower_line = line.lower()

            if (
                "datum" in lower_line
                or "ngvd" in lower_line
                or "navd" in lower_line
                or "nad" in lower_line
                or "state plane" in lower_line
            ):
                metadata["evidence"].append({
                    "page": page_number,
                    "line": line.strip(),
                })

                if "ngvd 1929" in lower_line or "ngvd1929" in lower_line:
                    metadata["vertical_datum"] = "NGVD 1929"

                if "navd 1988" in lower_line or "navd88" in lower_line or "navd 88" in lower_line:
                    metadata["vertical_datum"] = "NAVD 1988"

                if "nad 83" in lower_line or "nad83" in lower_line:
                    metadata["horizontal_datum"] = "NAD 83"

                if "nad 27" in lower_line or "nad27" in lower_line:
                    metadata["horizontal_datum"] = "NAD 27"

                if "florida state plane" in lower_line and "west zone" in lower_line:
                    metadata["coordinate_system"] = "Florida State Plane, West Zone"

                elif "state plane" in lower_line and not metadata["coordinate_system"]:
                    metadata["coordinate_system"] = "State Plane"

    doc.close()

    return metadata

def analyze_page(text):
    text = text.lower()

    has_northing = "northing" in text
    has_easting = "easting" in text
    has_elevation = "elevation" in text or "elev" in text
    has_control_point = "control point" in text or "control points" in text
    has_project_control = "project control" in text
    has_vertical_control = "vertical control" in text
    has_horizontal_control = "horizontal control" in text

    looks_like_index = (
        "sheet no." in text
        and "sheet description" in text
    )

    has_coordinate_pair = has_northing and has_easting

    has_vertical_evidence = (
        has_vertical_control
        or (has_elevation and has_control_point)
    )

    if looks_like_index and (has_project_control or has_control_point):
        classification = "INDEX_REFERENCE_PAGE"

    elif has_coordinate_pair and has_vertical_evidence:
        classification = "PROJECT_CONTROL_TABLE"

    elif has_coordinate_pair and has_horizontal_control:
        classification = "HORIZONTAL_CONTROL_TABLE"

    elif has_control_point or has_project_control:
        classification = "FEATURE_CONTROL_REFERENCE"

    else:
        classification = "OTHER"

    return classification

def scanner(pdf_path, log=None, verbose=False):
    extraction_pages = []
    reference_pages = []

    doc = fitz.open(pdf_path)

    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text("text") or ""

        classification = analyze_page(text)

        if verbose and classification != "OTHER" and log:
            log(f"  - Page {page_index + 1}: {classification}")

        if classification == "PROJECT_CONTROL_TABLE":
            extraction_pages.append(page_index)
        elif classification != "OTHER":
            reference_pages.append(page_index)

    doc.close()

    return extraction_pages, reference_pages

def score_table(table):
    if not table:
        return 0

    table_text = ""

    for row in table:
        for cell in row:
            if cell:
                table_text += " " + cell.lower()

    score = 0

    if "reference points" in table_text:
        score += 10
    if "vertical control" in table_text:
        score += 10
    if "northing" in table_text:
        score += 5
    if "easting" in table_text:
        score += 5
    if "elevation" in table_text or "elev" in table_text:
        score += 3
    if "description" in table_text:
        score += 2

    return score

def find_best_table(page):
    tables = page.extract_tables()

    best_table = None
    best_score = 0

    for table in tables:
        score = score_table(table)

        if score > best_score:
            best_score = score
            best_table = table

    return best_table, best_score

def parse_blob_records(text):
    records = []

    if not text:
        return records

    pattern = re.compile(
        r"(?m)^\s*(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(.+?)\s*$"
    )

    for match in pattern.finditer(text):
        records.append({
            "point": match.group(1).strip(),
            "northing": match.group(2).strip(),
            "easting": match.group(3).strip(),
            "elevation": match.group(4).strip(),
            "description": clean_description(match.group(5)),
        })

    return records

def parse_vertical_control_table(table):
    records = []
    seen_points = set()

    for row in table:
        if not row:
            continue

        # Handle blob-style records
        for cell in row:
            blob_records = parse_blob_records(cell or "")

            for record in blob_records:
                if record["point"] not in seen_points:
                    records.append(record)
                    seen_points.add(record["point"])

        # Handle column-style records
        if len(row) < 4:
            continue

        point_cell = row[0] or ""
        northing_cell = row[1] or ""
        easting_cell = row[2] or ""
        elevation_cell = row[3] or ""

        description_cell = ""
        for cell in reversed(row):
            if cell:
                description_cell = cell
                break

        points = point_cell.splitlines()
        northings = northing_cell.splitlines()
        eastings = easting_cell.splitlines()
        elevations = elevation_cell.splitlines()
        descriptions = description_cell.splitlines()

        count = min(len(points), len(northings), len(eastings), len(elevations))

        for i in range(count):
            point = points[i].strip()

            if not point.isdigit():
                continue

            if point in seen_points:
                continue

            record = {
                "point": point,
                "northing": northings[i].strip(),
                "easting": eastings[i].strip(),
                "elevation": elevations[i].strip(),
                "description": clean_description(descriptions[i]) if i < len(descriptions) else "",
            }

            records.append(record)
            seen_points.add(point)

    return records

def validate_record(record):
    required_fields = ["point", "northing", "easting", "elevation"]

    for field in required_fields:
        if not record.get(field):
            return False

    try:
        float(record["northing"])
        float(record["easting"])
        float(record["elevation"])
    except ValueError:
        return False

    return True

def extract_control_points(pdf_path, page_indices, log=None):
    
    all_records = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index in page_indices:
            if log:
                log(f"  Extracting table from page {page_index + 1}…")

            page = pdf.pages[page_index]
            table, score = find_best_table(page)

            if table is None:
                if log:
                    log(f"  No table detected on page {page_index + 1}.")
                continue

            if log:
                log(f"  Table detected (confidence score {score}). Parsing rows…")

            records = parse_vertical_control_table(table)

            for record in records:
                record["source_page"] = page_index + 1

            all_records.extend(records)

    return all_records

def clean_description(description):
    if not description:
        return ""

    description = description.strip()

    # Collapse weird spacing
    description = " ".join(description.split())

    # Remove random unmatched quote at the very end
    if description.endswith('"') and description.count('"') % 2 == 1:
        description = description[:-1].strip()

    return description

def write_csv(records, output_path):
    fieldnames = [
        "point",
        "system_point_id",
        "source_point_id",
        "point_normalized",
        "easting",
        "northing",
        "elevation",
        "description",
        "horizontal_datum",
        "vertical_datum",
        "coordinate_system",
        "latitude",
        "longitude",
        "original_easting",
        "original_northing",
        "original_elevation",
        "original_horizontal_datum",
        "original_vertical_datum",
        "conversion_method",
        "conversion_status",
        "validation_status",
        "validation_flags",
        "dedupe_status",
        "dedupe_flags",
        "dedupe_group_id",
        "source_page",
        "source_pdf",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()

        for record in records:
            writer.writerow(record)

def run_control_point_pipeline(pdf_path, output_path, log=None):
    metadata = extract_project_metadata(pdf_path)

    if log:
        log("  Reading project metadata…")

    if log:
        log("  Scanning pages to find control point tables…")
    extraction_page_indices, reference_page_indices = scanner(pdf_path, log=log, verbose=False)

    if log:
        if extraction_page_indices:
            pages = ", ".join(str(i + 1) for i in extraction_page_indices)
            log(f"  Found table pages: {pages}.")
        else:
            log("  No control point table pages found.")

    records = extract_control_points(pdf_path, extraction_page_indices, log=log)

    all_records = []

    for record in records:
        record["horizontal_datum"] = metadata["horizontal_datum"]
        record["vertical_datum"] = metadata["vertical_datum"]
        record["coordinate_system"] = metadata["coordinate_system"]
        record["source_pdf"] = Path(pdf_path).name
        all_records.append(record)

    if log:
        log("  Validating + normalizing extracted data…")
    all_records = validate_and_normalize_records(all_records, log=log)

    if log:
        log("  Standardizing datums (NAD 83 / NAVD 1988)…")
    all_records = standardize_records(all_records, log=log)

    if log:
        log("  Deduplicating (exact) + flagging uncertain duplicates…")
    all_records, exact_removed = deduplicate_records(
        all_records,
        log=log,
        context=Path(pdf_path).name,
    )
    all_records = flag_uncertain_duplicates(all_records, log=log, context=Path(pdf_path).name)

    if log:
        log("  Assigning system point IDs…")
    all_records = assign_system_point_ids(all_records, log=log)

    if log:
        log(f"  Writing CSV output ({len(all_records)} record(s))…")
    write_csv(all_records, output_path)

    ok_count = sum(1 for record in all_records if (record.get("validation_status") or "") == "ok")
    return {
        "extraction_pages": [i + 1 for i in extraction_page_indices],
        "reference_pages": [i + 1 for i in reference_page_indices],
        "metadata": metadata,
        "parsed_count": len(records),
        "valid_count": ok_count,
        "exact_duplicates_removed": exact_removed,
        "records": all_records,
        "output_path": output_path,
    }