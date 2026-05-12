import csv
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from output_control import write_arcgis_csv


def _make_record(**kwargs):
    base = {
        "system_point_id": "CP000001",
        "point": "219",
        "easting": "746147.13",
        "northing": "770035.76",
        "elevation": "20.54",
        "description": "SET IRON PIPE",
        "source_pdf": "test.pdf",
        "confidence_level": "high",
    }
    base.update(kwargs)
    return base


def test_write_arcgis_csv_columns():
    records = [_make_record()]
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv(records, path)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["point_id", "x", "y", "elevation", "description", "source_pdf"]
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["point_id"] == "CP000001"
    assert rows[0]["x"] == "746147.13"
    assert rows[0]["y"] == "770035.76"
    assert rows[0]["elevation"] == "20.54"
    assert rows[0]["description"] == "SET IRON PIPE"
    assert rows[0]["source_pdf"] == "test.pdf"


def test_write_arcgis_csv_uses_system_point_id_over_point():
    records = [_make_record(system_point_id="CP000005", point="5")]
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv(records, path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["point_id"] == "CP000005"


def test_write_arcgis_csv_falls_back_to_point_when_no_system_id():
    records = [_make_record(system_point_id="", point="42")]
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv(records, path)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["point_id"] == "42"


def test_write_arcgis_csv_empty_list():
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        path = f.name
    write_arcgis_csv([], path)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ["point_id", "x", "y", "elevation", "description", "source_pdf"]
        assert list(reader) == []
