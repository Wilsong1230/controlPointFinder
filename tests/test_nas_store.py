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


def test_corrupted_index_rebuilds_cache(tmp_path):
    """Malformed pdf_index.json is ignored and cache is rebuilt."""
    cd1 = tmp_path / "CD-001"
    cd1.mkdir()
    _make_pdf(cd1, "sheet1.pdf")

    store_dir = tmp_path / ".controlpoint"
    store_dir.mkdir()
    (store_dir / "pdf_index.json").write_text("not valid json {{{{")

    from nas_store import get_pdf_paths
    result = get_pdf_paths(tmp_path)

    assert len(result) == 1
    assert result[0].name == "sheet1.pdf"
    # Cache should now be valid
    data = json.loads((store_dir / "pdf_index.json").read_text())
    assert data["version"] == 1


def test_unreachable_folder_falls_back_to_rglob(tmp_path):
    """If the input_folder doesn't exist, falls back to rglob (returns empty list)."""
    from nas_store import get_pdf_paths
    missing = tmp_path / "does_not_exist"
    result = get_pdf_paths(missing)
    assert result == []


def test_get_registry_path_returns_nas_path(tmp_path):
    """get_registry_path returns path inside .controlpoint/ on the NAS."""
    from nas_store import get_registry_path
    result = get_registry_path(tmp_path)
    assert result == tmp_path / ".controlpoint" / "point_id_registry.json"


def test_get_registry_path_creates_store_dir(tmp_path):
    """get_registry_path creates .controlpoint/ if it doesn't exist."""
    from nas_store import get_registry_path
    get_registry_path(tmp_path)
    assert (tmp_path / ".controlpoint").is_dir()


def test_get_registry_path_migrates_local_registry(tmp_path):
    """If NAS registry missing but local exists, copies local to NAS."""
    local_registry = tmp_path / "point_id_registry.json"
    local_registry.write_text(json.dumps({"last_id": 42, "mapping": {"k": "CP000042"}}))

    from nas_store import get_registry_path
    nas_path = get_registry_path(tmp_path, local_fallback=local_registry)

    assert nas_path.exists()
    data = json.loads(nas_path.read_text())
    assert data["last_id"] == 42


def test_get_registry_path_no_migration_if_nas_exists(tmp_path):
    """If NAS registry already exists, local file is not used."""
    nas_dir = tmp_path / ".controlpoint"
    nas_dir.mkdir()
    nas_reg = nas_dir / "point_id_registry.json"
    nas_reg.write_text(json.dumps({"last_id": 7, "mapping": {}}))

    local_registry = tmp_path / "point_id_registry.json"
    local_registry.write_text(json.dumps({"last_id": 99, "mapping": {}}))

    from nas_store import get_registry_path
    nas_path = get_registry_path(tmp_path, local_fallback=local_registry)

    data = json.loads(nas_path.read_text())
    assert data["last_id"] == 7  # NAS wins, local is ignored
