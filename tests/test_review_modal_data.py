import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from review_modal import apply_modal_actions


def _rec(point_id="CP000001", confidence_level="low", **kwargs):
    base = {
        "system_point_id": point_id,
        "point": "1",
        "easting": "100.0",
        "northing": "200.0",
        "elevation": "10.0",
        "description": "TEST",
        "source_pdf": "a.pdf",
        "confidence_level": confidence_level,
    }
    base.update(kwargs)
    return base


def test_all_accepted():
    records = [_rec("CP1"), _rec("CP2")]
    actions = {0: "accepted", 1: "accepted"}
    result = apply_modal_actions(records, actions, edits={})
    assert len(result["accepted"]) == 2
    assert len(result["skipped"]) == 0


def test_all_skipped():
    records = [_rec("CP1"), _rec("CP2")]
    actions = {0: "skipped", 1: "skipped"}
    result = apply_modal_actions(records, actions, edits={})
    assert len(result["accepted"]) == 0
    assert len(result["skipped"]) == 2


def test_mixed_actions():
    records = [_rec("CP1"), _rec("CP2"), _rec("CP3")]
    actions = {0: "accepted", 1: "skipped", 2: "edited"}
    result = apply_modal_actions(records, actions, edits={2: {"elevation": "99.9"}})
    assert len(result["accepted"]) == 2
    assert result["accepted"][1]["system_point_id"] == "CP3"
    assert result["accepted"][1]["elevation"] == "99.9"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["system_point_id"] == "CP2"


def test_edited_fields_applied():
    records = [_rec("CP1")]
    actions = {0: "edited"}
    edits = {0: {"easting": "111.1", "description": "UPDATED"}}
    result = apply_modal_actions(records, actions, edits=edits)
    r = result["accepted"][0]
    assert r["easting"] == "111.1"
    assert r["description"] == "UPDATED"
    assert r["northing"] == "200.0"  # unchanged field preserved


def test_original_records_not_mutated():
    original = _rec("CP1")
    records = [original]
    actions = {0: "edited"}
    edits = {0: {"easting": "999.0"}}
    apply_modal_actions(records, actions, edits=edits)
    assert original["easting"] == "100.0"  # original untouched
