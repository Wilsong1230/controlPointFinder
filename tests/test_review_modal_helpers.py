import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from review_modal import swap_column_data, fill_column_data, clear_column_data, next_unreviewed


def _rec(**kwargs):
    base = {"easting": "100.0", "northing": "200.0", "elevation": "10.0", "description": "TEST"}
    base.update(kwargs)
    return base


# --- swap_column_data ---

def test_swap_exchanges_values():
    records = [_rec(easting="1.0", northing="2.0"), _rec(easting="3.0", northing="4.0")]
    result = swap_column_data(records, "easting", "northing")
    assert result[0]["easting"] == "2.0"
    assert result[0]["northing"] == "1.0"
    assert result[1]["easting"] == "4.0"
    assert result[1]["northing"] == "3.0"


def test_swap_does_not_mutate_input():
    records = [_rec(easting="1.0", northing="2.0")]
    swap_column_data(records, "easting", "northing")
    assert records[0]["easting"] == "1.0"


def test_swap_preserves_other_fields():
    records = [_rec(easting="1.0", northing="2.0", elevation="5.0")]
    result = swap_column_data(records, "easting", "northing")
    assert result[0]["elevation"] == "5.0"


def test_swap_handles_missing_field():
    records = [{"easting": "1.0"}]
    result = swap_column_data(records, "easting", "northing")
    assert result[0]["easting"] == ""
    assert result[0]["northing"] == "1.0"


# --- fill_column_data ---

def test_fill_sets_value_on_all_rows():
    records = [_rec(elevation="1.0"), _rec(elevation="2.0")]
    result = fill_column_data(records, "elevation", "99.9")
    assert result[0]["elevation"] == "99.9"
    assert result[1]["elevation"] == "99.9"


def test_fill_does_not_mutate_input():
    records = [_rec(elevation="1.0")]
    fill_column_data(records, "elevation", "99.9")
    assert records[0]["elevation"] == "1.0"


def test_fill_preserves_other_fields():
    records = [_rec(easting="7.0", elevation="1.0")]
    result = fill_column_data(records, "elevation", "99.9")
    assert result[0]["easting"] == "7.0"


# --- clear_column_data ---

def test_clear_sets_empty_string_on_all_rows():
    records = [_rec(description="A"), _rec(description="B")]
    result = clear_column_data(records, "description")
    assert result[0]["description"] == ""
    assert result[1]["description"] == ""


def test_clear_does_not_mutate_input():
    records = [_rec(description="A")]
    clear_column_data(records, "description")
    assert records[0]["description"] == "A"


# --- next_unreviewed ---

def test_next_unreviewed_finds_first_gap():
    assert next_unreviewed(actions={0: "accepted"}, total=3, current=0) == 1


def test_next_unreviewed_skips_reviewed():
    assert next_unreviewed(actions={0: "accepted", 1: "skipped"}, total=4, current=0) == 2


def test_next_unreviewed_returns_none_when_all_done():
    assert next_unreviewed(actions={0: "accepted", 1: "skipped", 2: "accepted"}, total=3, current=0) is None


def test_next_unreviewed_returns_none_at_last_row():
    assert next_unreviewed(actions={}, total=3, current=2) is None
