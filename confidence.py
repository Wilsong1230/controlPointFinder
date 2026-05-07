from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class ConfidenceResult:
    score: int  # 0-100
    level: str  # "high" | "medium" | "low"
    reasons: str  # semicolon-separated


def score_table(table: list[list[Optional[str]]] | None) -> int:
    """
    Lightweight heuristic for "does this look like a control point table?"
    Returns an integer 0..(roughly 35).
    """
    if not table:
        return 0

    table_text = []
    for row in table:
        for cell in row or []:
            if cell:
                table_text.append(str(cell).lower())

    blob = " ".join(table_text)
    score = 0

    if "reference points" in blob:
        score += 10
    if "vertical control" in blob:
        score += 10
    if "northing" in blob:
        score += 5
    if "easting" in blob:
        score += 5
    if "elevation" in blob or "elev" in blob:
        score += 3
    if "description" in blob:
        score += 2

    return score


def find_best_table(page) -> tuple[Optional[list[list[Optional[str]]]], int]:
    """
    Returns (best_table, table_score). Page is a pdfplumber Page.
    """
    tables = page.extract_tables() or []

    best_table: Optional[list[list[Optional[str]]]] = None
    best_score = 0

    for table in tables:
        score = score_table(table)
        if score > best_score:
            best_score = score
            best_table = table

    return best_table, best_score


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_flags(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(";")]
    return [p for p in parts if p]


def _clamp_int(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def compute_record_confidence(record: dict[str, Any]) -> ConfidenceResult:
    """
    Produces a 0-100 confidence score for an extracted control point row.

    Design goals:
    - Use signals already present in the pipeline (validation/dedupe/conversion).
    - Be explainable: return reasons for the score.
    - Conservative defaults: missing/flagged data should push scores down.
    """
    score = 70.0
    reasons: list[str] = []

    # --- Core coordinate sanity ---
    e = _as_float(record.get("easting"))
    n = _as_float(record.get("northing"))
    z = _as_float(record.get("elevation"))
    if e is None or n is None or z is None:
        return ConfidenceResult(score=0, level="low", reasons="missing_or_non_numeric_coordinates")

    # --- Provenance signals ---
    table_score = _as_float(record.get("table_score"))
    if table_score is not None:
        if table_score >= 25:
            score += 10
            reasons.append("strong_table_header_signal")
        elif table_score >= 15:
            score += 5
            reasons.append("moderate_table_header_signal")
        elif table_score <= 5:
            score -= 10
            reasons.append("weak_table_header_signal")

    parse_method = str(record.get("parse_method") or "").strip().lower()
    if parse_method:
        if "column" in parse_method:
            score += 4
            reasons.append("column_parse")
        elif "blob" in parse_method or "regex" in parse_method:
            score -= 2
            reasons.append("blob_parse")

    # --- Content completeness ---
    desc = str(record.get("description") or "").strip()
    if desc:
        score += 2
        reasons.append("has_description")
    else:
        score -= 2
        reasons.append("missing_description")

    pt = str(record.get("point_normalized") or record.get("source_point_id") or record.get("point") or "").strip()
    if not pt:
        score -= 20
        reasons.append("missing_point_id")

    # --- Validation signals (most important) ---
    status = str(record.get("validation_status") or "").strip().lower()
    vflags = _split_flags(record.get("validation_flags"))
    if status and status != "ok":
        score = min(score, 25.0)
        reasons.append(f"validation_status:{status}")
    if vflags:
        score -= min(35.0, 8.0 * len(vflags))
        reasons.append("validation_flags_present")

    # --- Datum conversion / CRS confidence ---
    conv_status = str(record.get("conversion_status") or "").strip().lower()
    if conv_status.startswith("failed"):
        score -= 12
        reasons.append("datum_conversion_failed")
    elif conv_status.startswith("skipped"):
        score -= 6
        reasons.append("datum_conversion_skipped")
    elif conv_status == "converted":
        score += 2
        reasons.append("datum_converted")

    # If the pipeline couldn't compute lat/lon, reduce trust in downstream geo usage.
    lat = str(record.get("latitude") or "").strip()
    lon = str(record.get("longitude") or "").strip()
    if not lat or not lon:
        score -= 3
        reasons.append("missing_lat_lon")
    else:
        reasons.append("has_lat_lon")

    # --- Dedupe / conflicts ---
    dedupe_status = str(record.get("dedupe_status") or "").strip().lower()
    dflags = _split_flags(record.get("dedupe_flags"))
    if dedupe_status == "uncertain":
        score -= 15
        reasons.append("uncertain_duplicate_group")
    if dflags:
        score -= min(12.0, 4.0 * len(dflags))
        reasons.append("dedupe_flags_present")

    # --- Finalize ---
    score_i = _clamp_int(score)
    if score_i >= 80:
        level = "high"
    elif score_i >= 55:
        level = "medium"
    else:
        level = "low"

    # De-duplicate reasons but preserve order.
    seen = set()
    ordered: list[str] = []
    for r in reasons:
        if r in seen:
            continue
        seen.add(r)
        ordered.append(r)

    return ConfidenceResult(score=score_i, level=level, reasons=";".join(ordered))


def apply_confidence(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Mutates each record by adding:
      - confidence_score (int 0-100)
      - confidence_level ("high"|"medium"|"low")
      - confidence_reasons (semicolon-separated string)
    Returns a list for convenience.
    """
    out: list[dict[str, Any]] = []
    for rec in records:
        res = compute_record_confidence(rec)
        rec["confidence_score"] = res.score
        rec["confidence_level"] = res.level
        rec["confidence_reasons"] = res.reasons
        out.append(rec)
    return out

