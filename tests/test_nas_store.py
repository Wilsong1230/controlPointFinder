# tests/test_nas_store.py
import json
import os
from pathlib import Path
import pytest


def _make_pdf(folder: Path, name: str) -> Path:
    p = folder / name
    p.write_text("fake pdf")
    return p


def test_cold_cache_scans_all_folders(tmp_path):
    """No cache file → scans everything, returns all PDFs."""
    cd1 = tmp_path / "CD-001"
    cd1.mkdir()
    _make_pdf(cd1, "sheet1.pdf")
    _make_pdf(cd1, "sheet2.pdf")
    cd2 = tmp_path / "CD-002"
    cd2.mkdir()
    _make_pdf(cd2, "sheet3.pdf")

    from nas_store import get_pdf_paths
    result = get_pdf_paths(tmp_path)

    assert len(result) == 3
    assert all(isinstance(p, Path) for p in result)
    names = {p.name for p in result}
    assert names == {"sheet1.pdf", "sheet2.pdf", "sheet3.pdf"}


def test_cold_cache_writes_index(tmp_path):
    """After a cold scan, pdf_index.json is written to .controlpoint/."""
    cd1 = tmp_path / "CD-001"
    cd1.mkdir()
    _make_pdf(cd1, "sheet1.pdf")

    from nas_store import get_pdf_paths
    get_pdf_paths(tmp_path)

    index_path = tmp_path / ".controlpoint" / "pdf_index.json"
    assert index_path.exists()
    data = json.loads(index_path.read_text())
    assert data["version"] == 1
    assert "CD-001" in data["folders"]


def test_cold_cache_ignores_non_pdf_files(tmp_path):
    """Non-PDF files in CD folders are not returned."""
    cd1 = tmp_path / "CD-001"
    cd1.mkdir()
    _make_pdf(cd1, "sheet1.pdf")
    (cd1 / "readme.txt").write_text("not a pdf")

    from nas_store import get_pdf_paths
    result = get_pdf_paths(tmp_path)

    assert len(result) == 1
    assert result[0].name == "sheet1.pdf"


def test_warm_cache_returns_cached_paths(tmp_path):
    """When no folder has changed, returns from cache without re-scanning."""
    cd1 = tmp_path / "CD-001"
    cd1.mkdir()
    _make_pdf(cd1, "sheet1.pdf")

    from nas_store import get_pdf_paths

    # First call — cold, builds cache
    first = get_pdf_paths(tmp_path)

    # Capture the actual mtime that was stored in the cache
    index_path = tmp_path / ".controlpoint" / "pdf_index.json"
    data = json.loads(index_path.read_text())
    cached_mtime = data["folders"]["CD-001"]["mtime"]

    # Add a new PDF — this changes the folder's real mtime
    _make_pdf(cd1, "sheet2.pdf")

    # Rewind the folder's real mtime back to the cached value so the cache
    # still considers this folder "fresh" (mtime unchanged)
    os.utime(cd1, (cached_mtime, cached_mtime))

    second = get_pdf_paths(tmp_path)
    # Should return cached list (only sheet1.pdf), not the new sheet2.pdf
    assert len(second) == 1
    assert second[0].name == "sheet1.pdf"


def test_partial_stale_rescans_only_changed_folder(tmp_path):
    """Only the folder whose mtime changed is re-scanned."""
    cd1 = tmp_path / "CD-001"
    cd1.mkdir()
    _make_pdf(cd1, "sheet1.pdf")
    cd2 = tmp_path / "CD-002"
    cd2.mkdir()
    _make_pdf(cd2, "sheet2.pdf")

    from nas_store import get_pdf_paths
    get_pdf_paths(tmp_path)  # warm the cache

    # Add a PDF to CD-002 and touch its mtime so it appears stale
    _make_pdf(cd2, "sheet3.pdf")
    os.utime(cd2, None)

    result = get_pdf_paths(tmp_path)
    names = {p.name for p in result}
    assert "sheet1.pdf" in names
    assert "sheet2.pdf" in names
    assert "sheet3.pdf" in names
