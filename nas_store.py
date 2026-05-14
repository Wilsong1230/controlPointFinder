# nas_store.py
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_STORE_DIR = ".controlpoint"
_INDEX_FILE = "pdf_index.json"
_REGISTRY_FILE = "point_id_registry.json"
_INDEX_VERSION = 1
_SCAN_THREADS = 20


def _store_dir(input_folder: Path) -> Path:
    return input_folder / _STORE_DIR


def _index_path(input_folder: Path) -> Path:
    return _store_dir(input_folder) / _INDEX_FILE


def _scan_folder_for_pdfs(folder: Path) -> list[str]:
    """Recursively collect absolute PDF paths under folder using os.scandir."""
    results = []
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".pdf"):
                        results.append(entry.path)
        except OSError:
            pass
    return results


def _read_index(input_folder: Path) -> dict:
    path = _index_path(input_folder)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != _INDEX_VERSION:
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _write_index(input_folder: Path, folders_data: dict) -> None:
    store = _store_dir(input_folder)
    store.mkdir(parents=True, exist_ok=True)
    path = _index_path(input_folder)
    payload = {"version": _INDEX_VERSION, "folders": folders_data}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _get_top_level_dirs(input_folder: Path) -> list[tuple[str, Path, float]]:
    """Return (name, path, mtime) for each top-level directory."""
    entries = []
    try:
        with os.scandir(input_folder) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    entries.append((entry.name, Path(entry.path), mtime))
    except OSError:
        pass
    return entries


def get_pdf_paths(input_folder: Path, log=None) -> list[Path]:
    """
    Return sorted list of all PDF paths under input_folder.
    Uses a NAS-backed JSON cache; only re-scans folders whose mtime changed.
    Falls back to rglob on any error accessing the cache.
    """
    input_folder = Path(input_folder)

    try:
        return _cached_get_pdf_paths(input_folder, log=log)
    except Exception:
        if log:
            log("PDF index cache unavailable — falling back to full directory scan.")
        return _rglob_fallback(input_folder)


def _cached_get_pdf_paths(input_folder: Path, log=None) -> list[Path]:
    index = _read_index(input_folder)
    cached_folders: dict = index.get("folders", {})

    top_dirs = _get_top_level_dirs(input_folder)
    stale = [(name, path) for name, path, mtime in top_dirs
             if name not in cached_folders or cached_folders[name]["mtime"] != mtime]
    fresh = [(name, path, mtime) for name, path, mtime in top_dirs
             if name in cached_folders and cached_folders[name]["mtime"] == mtime]

    if log:
        if not cached_folders:
            log(f"PDF index: cold cache — scanning {len(top_dirs)} folder(s).")
        elif stale:
            log(f"PDF index: {len(fresh)} folder(s) cached, {len(stale)} stale — re-scanning stale.")
        else:
            log(f"PDF index: all {len(fresh)} folder(s) cached — skipping scan.")

    new_folders_data: dict = {name: cached_folders[name] for name, _, _ in fresh}

    if stale:
        with ThreadPoolExecutor(max_workers=_SCAN_THREADS) as pool:
            futures = {pool.submit(_scan_folder_for_pdfs, path): (name, path) for name, path in stale}
            for future in as_completed(futures):
                name, path = futures[future]
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                pdf_abs_paths = future.result()
                rel_paths = sorted(
                    str(Path(p).relative_to(input_folder)) for p in pdf_abs_paths
                )
                new_folders_data[name] = {"mtime": mtime, "pdfs": rel_paths}

    _write_index(input_folder, new_folders_data)

    all_paths = []
    for folder_data in new_folders_data.values():
        for rel in folder_data["pdfs"]:
            all_paths.append(input_folder / rel)
    return sorted(all_paths)


def _rglob_fallback(input_folder: Path) -> list[Path]:
    return sorted(
        path for path in input_folder.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )


def get_registry_path(input_folder: Path, *, local_fallback: Path | None = None) -> Path:
    """
    Return the NAS-backed registry path (.controlpoint/point_id_registry.json).
    Creates .controlpoint/ if needed.
    If the NAS registry doesn't exist and local_fallback does, copies it up.
    """
    input_folder = Path(input_folder)
    store = _store_dir(input_folder)
    store.mkdir(parents=True, exist_ok=True)
    nas_path = store / _REGISTRY_FILE

    if not nas_path.exists() and local_fallback and Path(local_fallback).exists():
        import shutil
        shutil.copy2(local_fallback, nas_path)

    return nas_path
