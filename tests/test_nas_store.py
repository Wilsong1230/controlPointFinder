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
