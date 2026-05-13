import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import threading


def test_standardize_records_empty_list():
    from datum_standardization import standardize_records
    result = standardize_records([], log=None)
    assert result == []


def test_standardize_records_returns_all_records():
    from datum_standardization import standardize_records
    records = [
        {
            "easting": "1.0", "northing": "2.0", "elevation": "3.0",
            "horizontal_datum": "NAD 83", "vertical_datum": "NAVD 1988",
            "coordinate_system": "",
        },
        {
            "easting": "4.0", "northing": "5.0", "elevation": "6.0",
            "horizontal_datum": "NAD 83", "vertical_datum": "NAVD 1988",
            "coordinate_system": "",
        },
    ]
    result = standardize_records(records, log=None)
    assert len(result) == 2


def test_ncat_session_is_thread_local():
    from datum_standardization import _ncat_session
    sessions = []  # keep strong references so GC doesn't reuse addresses

    def collect():
        sessions.append(_ncat_session())

    threads = [threading.Thread(target=collect) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Each thread creates its own session — all IDs should be distinct
    assert len(set(id(s) for s in sessions)) == 4


def test_ncat_session_reused_within_same_thread():
    from datum_standardization import _ncat_session
    id1 = id(_ncat_session())
    id2 = id(_ncat_session())
    assert id1 == id2
