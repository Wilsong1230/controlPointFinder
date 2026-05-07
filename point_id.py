"""
System Point ID assignment.

We do not export external PDF "point" values as our primary identifiers.
Instead we assign stable, persistent IDs like CP000001.

Persistence:
- Stored in point_id_registry.json in the project root (workspace).
- Keeps last_id and a mapping from canonical_key -> system_point_id.

Canonical key strategy (current):
- Uses standardized coordinates (after datum standardization + exact dedupe):
  coordinate_system + easting + northing + elevation (normalized, rounded)
- This keeps IDs stable across runs for the same point location.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional


LogFn = Optional[Callable[[str], None]]


def _normalize_numeric(value: Any) -> str:
    text = ("" if value is None else str(value)).strip().replace(",", "")
    if not text:
        return ""
    try:
        normalized = format(Decimal(text).normalize(), "f")
    except (InvalidOperation, ValueError):
        return text
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _round_str(value: Any, places: int) -> str:
    text = _normalize_numeric(value)
    if not text:
        return ""
    try:
        q = Decimal(10) ** (-places)
        dec = Decimal(text).quantize(q)
    except (InvalidOperation, ValueError):
        return text
    s = format(dec.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def canonical_point_key(record: dict[str, Any]) -> str:
    """
    Builds a stable canonical key from standardized values.
    Rounding helps avoid tiny numeric differences run-to-run.
    """
    coord_sys = (record.get("coordinate_system") or "").strip()
    e = _round_str(record.get("easting"), 3)
    n = _round_str(record.get("northing"), 3)
    z = _round_str(record.get("elevation"), 3)
    return f"{coord_sys}|{e}|{n}|{z}"


@dataclass
class PointIdRegistry:
    path: Path
    prefix: str = "CP"
    width: int = 6
    last_id: int = 0
    mapping: dict[str, str] = None  # canonical_key -> system_id

    def __post_init__(self):
        if self.mapping is None:
            self.mapping = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.last_id = int(data.get("last_id") or 0)
        self.mapping = dict(data.get("mapping") or {})

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "last_id": self.last_id,
                    "mapping": self.mapping,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _format_id(self, n: int) -> str:
        return f"{self.prefix}{n:0{self.width}d}"

    def get_or_create(self, canonical_key: str) -> str:
        existing = self.mapping.get(canonical_key)
        if existing:
            return existing
        self.last_id += 1
        system_id = self._format_id(self.last_id)
        self.mapping[canonical_key] = system_id
        return system_id


def assign_system_point_ids(
    records: list[dict[str, Any]],
    *,
    registry_path: str | Path = "point_id_registry.json",
    log: LogFn = None,
) -> list[dict[str, Any]]:
    """
    Mutates records in place:
    - sets source_point_id (original PDF point field)
    - sets system_point_id (our generated)
    - sets point = system_point_id (so exports don't carry external IDs)
    """
    reg = PointIdRegistry(path=Path(registry_path))
    reg.load()

    created = 0
    reused = 0

    for record in records:
        if "source_point_id" not in record:
            record["source_point_id"] = record.get("point", "")

        key = canonical_point_key(record)
        before = reg.mapping.get(key)
        system_id = reg.get_or_create(key)
        if before:
            reused += 1
        else:
            created += 1

        record["system_point_id"] = system_id
        record["point"] = system_id

    reg.save()

    if log:
        log(
            f"  Point IDs: {created} new, {reused} reused. "
            f"Registry last_id={reg.last_id} ({reg.path})"
        )

    return records

