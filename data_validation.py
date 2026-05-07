"""
Record validation + normalization for exported control points.

Goals:
- Normalize numeric formatting (commas/spacing, trailing zeros).
- Normalize point/station identifier formatting.
- Validate easting/northing/elevation are present and sane.
- Detect likely swapped easting/northing columns and flag.
- Never silently drop rows: instead attach validation flags/status.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Callable, Optional


LogFn = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class Range:
    min_value: float
    max_value: float

    def contains(self, value: float) -> bool:
        return self.min_value <= value <= self.max_value


@dataclass(frozen=True)
class CoordinateProfile:
    name: str
    easting_ft: Range
    northing_ft: Range
    elevation_ft: Range


FL_WEST_PROFILE = CoordinateProfile(
    name="Florida State Plane, West Zone (ftUS)",
    easting_ft=Range(450_000.0, 1_000_000.0),
    northing_ft=Range(300_000.0, 3_000_000.0),
    elevation_ft=Range(-50.0, 500.0),
)

GENERIC_PROFILE = CoordinateProfile(
    name="Generic (ft)",
    easting_ft=Range(1_000.0, 50_000_000.0),
    northing_ft=Range(1_000.0, 50_000_000.0),
    elevation_ft=Range(-500.0, 10_000.0),
)


def _norm_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _norm_coord_system(value: str) -> str:
    return _norm_text(value).lower()


def _choose_profile(record: dict[str, Any]) -> CoordinateProfile:
    coord = _norm_coord_system(str(record.get("coordinate_system") or ""))
    if "florida state plane" in coord and "west" in coord:
        return FL_WEST_PROFILE
    return GENERIC_PROFILE


def normalize_numeric_text(value: Any) -> str:
    """
    Normalize numeric strings for CSV stability:
    - remove commas
    - trim whitespace
    - normalize Decimal (no exponent), strip trailing zeros
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    # Common formatting artifacts
    text = text.replace(",", "")
    text = text.replace("\u00a0", " ")  # nbsp
    text = " ".join(text.split())

    # Handle leading '+' or stray equals signs, etc.
    text = re.sub(r"^[=+]\s*", "", text)

    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return text

    normalized = format(dec.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def parse_float(value: Any) -> Optional[float]:
    text = normalize_numeric_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


_STATION_PREFIX_RE = re.compile(r"^(sta\.?|station)\s+", re.IGNORECASE)
_SPACE_AROUND_PLUS_RE = re.compile(r"\s*\+\s*")
_STATION_RE = re.compile(r"^\d+(\+\d+)(\.\d+)?$")


def normalize_point_text(value: Any) -> str:
    """
    Normalize point/station identifiers:
    - collapse whitespace
    - strip STA/STATION prefix
    - normalize station '+' spacing (e.g., '10 + 00' -> '10+00')
    - for pure integers: strip leading zeros
    """
    text = _norm_text("" if value is None else str(value))
    if not text:
        return ""

    text = _STATION_PREFIX_RE.sub("", text).strip()
    text = _SPACE_AROUND_PLUS_RE.sub("+", text)
    text = re.sub(r"\s+", " ", text)

    if text.isdigit():
        stripped = text.lstrip("0")
        return stripped or "0"

    if _STATION_RE.match(text):
        return text

    return text


def validate_and_normalize_record(record: dict[str, Any], log: LogFn = None) -> dict[str, Any]:
    """
    Adds:
    - point_normalized
    - validation_status: ok|suspicious|invalid
    - validation_flags: semicolon-separated flags

    Also normalizes the numeric text in easting/northing/elevation fields.
    """
    flags: list[str] = []
    profile = _choose_profile(record)

    record["point_normalized"] = normalize_point_text(record.get("point"))

    # Normalize numeric text in-place (keeps original_* separate if present)
    record["easting"] = normalize_numeric_text(record.get("easting"))
    record["northing"] = normalize_numeric_text(record.get("northing"))
    record["elevation"] = normalize_numeric_text(record.get("elevation"))

    e = parse_float(record.get("easting"))
    n = parse_float(record.get("northing"))
    z = parse_float(record.get("elevation"))

    if e is None:
        flags.append("missing_or_invalid_easting")
    if n is None:
        flags.append("missing_or_invalid_northing")
    if z is None:
        flags.append("missing_or_invalid_elevation")

    if e is not None and n is not None:
        e_in = profile.easting_ft.contains(e)
        n_in = profile.northing_ft.contains(n)

        if not e_in:
            flags.append("easting_out_of_expected_range")
        if not n_in:
            flags.append("northing_out_of_expected_range")

        # Swapped columns heuristic: each value fits the other's expected range better.
        if (not e_in or not n_in) and profile.easting_ft.contains(n) and profile.northing_ft.contains(e):
            flags.append("possible_swapped_easting_northing")

        # Extremely small / huge magnitudes are usually OCR issues
        if abs(e) < 1_000 or abs(n) < 1_000:
            flags.append("suspicious_small_coordinate_magnitude")
        if abs(e) > 100_000_000 or abs(n) > 100_000_000:
            flags.append("suspicious_large_coordinate_magnitude")

    if z is not None:
        if not profile.elevation_ft.contains(z):
            flags.append("elevation_out_of_sane_range")

        if abs(z) > 100_000:
            flags.append("suspicious_large_elevation_magnitude")

    # Point/station checks
    if not record.get("point") and not record["point_normalized"]:
        flags.append("missing_point_id")
    if record.get("point") and not record["point_normalized"]:
        flags.append("unparseable_point_id")

    # Determine status
    if any(flag.startswith("missing_or_invalid_") or flag == "missing_point_id" for flag in flags):
        status = "invalid"
    elif flags:
        status = "suspicious"
    else:
        status = "ok"

    record["validation_status"] = status
    record["validation_flags"] = ";".join(flags)

    if log and status != "ok":
        pt = record.get("point") or record.get("point_normalized") or "?"
        log(f"  Validation ({pt}): {status} [{record['validation_flags']}] ({profile.name})")

    return record


def validate_and_normalize_records(records: list[dict[str, Any]], log: LogFn = None) -> list[dict[str, Any]]:
    for record in records:
        validate_and_normalize_record(record, log=log)
    return records

