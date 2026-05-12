import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from batch import _split_low_confidence


def test_splits_correctly():
    records = [
        {"system_point_id": "CP1", "confidence_level": "low"},
        {"system_point_id": "CP2", "confidence_level": "high"},
        {"system_point_id": "CP3", "confidence_level": "medium"},
        {"system_point_id": "CP4", "confidence_level": "low"},
    ]
    low, other = _split_low_confidence(records)
    assert [r["system_point_id"] for r in low] == ["CP1", "CP4"]
    assert [r["system_point_id"] for r in other] == ["CP2", "CP3"]


def test_all_high_returns_empty_low():
    records = [{"confidence_level": "high"}, {"confidence_level": "medium"}]
    low, other = _split_low_confidence(records)
    assert low == []
    assert len(other) == 2


def test_missing_confidence_level_goes_to_other():
    records = [{"confidence_level": ""}, {"confidence_level": None}]
    low, other = _split_low_confidence(records)
    assert low == []
    assert len(other) == 2
