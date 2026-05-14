# NAS Shared Store — PDF Index Cache & Point ID Registry

**Date:** 2026-05-14
**Status:** Approved

## Problem

PDF discovery (`run_batch`) uses `rglob("*")` over a NAS, which serializes thousands of `is_file()` network round-trips. With ~4,000 PDFs across CD project folders, this takes ~1 hour. PDFs are added rarely (weekly/monthly). The point ID registry (`point_id_registry.json`) is stored locally, so it diverges across machines.

## Goals

- Reduce PDF discovery from ~1 hour to seconds on warm runs
- Reduce first/cold-cache scan from ~1 hour to minutes
- Make the point ID registry authoritative and shared across machines
- No server required; one user at a time

## Non-Goals

- Concurrent multi-user access (out of scope)
- Real-time NAS change detection (mtime polling on run is sufficient)

## Architecture

A new `nas_store.py` module owns all NAS-backed shared state. It manages two files inside a `.controlpoint/` directory at the root of the input PDF folder:

```
<input_folder>/
  .controlpoint/
    pdf_index.json
    point_id_registry.json
```

`batch.py` replaces its `rglob` call with `nas_store.get_pdf_paths(input_folder)`.
`point_id.py` reads/writes through `nas_store` instead of a local path.

## PDF Index Cache

### Structure of `pdf_index.json`

```json
{
  "version": 1,
  "folders": {
    "CD-001 Some Project": {
      "mtime": 1715123456.789,
      "pdfs": [
        "CD-001 Some Project/sheet1.pdf",
        "CD-001 Some Project/sheet2.pdf"
      ]
    }
  }
}
```

Paths stored relative to `input_folder` so the cache is portable across machines that mount the NAS at different drive letters or mount points.

### Cache Invalidation Logic

1. Read `pdf_index.json` from NAS (missing or unreadable → treat all folders as stale)
2. Call `os.scandir(input_folder)` to list top-level CD folders — one network call
3. For each top-level folder, compare its `mtime` to the cached value
4. **Stale/new folders** → submit to a `ThreadPoolExecutor(max_workers=20)` for recursive `os.scandir` scan
5. **Fresh folders** → return cached PDF paths immediately
6. Merge results into a sorted list
7. Write updated `pdf_index.json` back to NAS

### Thread Count

20 threads. NAS latency (~1–5 ms/call) is the bottleneck, not CPU. 20 threads parallelizes enough directory listings to bring a cold scan from ~1 hour to ~3–8 minutes. Tunable via a constant in `nas_store.py`.

## Point ID Registry

`point_id.py` currently reads/writes a local `point_id_registry.json`. Change:

- Path becomes `.controlpoint/point_id_registry.json` on the NAS
- On first use: if NAS copy is missing but a local copy exists, copy local → NAS (one-time migration)
- If neither exists, start fresh (current behavior)

No other changes to `point_id.py` logic.

## Error Handling

| Situation | Behavior |
|-----------|----------|
| NAS unreachable at startup | Fall back to current `rglob("*")` scan; log a warning |
| `pdf_index.json` is malformed JSON | Delete cache, rebuild from scratch on this run |
| PDF in cache has been deleted from NAS | `_process_single_pdf` handles missing files; cache rebuilds for that folder on its next mtime change |
| Cold cache (no `pdf_index.json`) | All folders treated as stale; parallel scan runs; cache written at end |
| `point_id_registry.json` missing on NAS | Promote local copy; if no local copy, start fresh |

The app never crashes due to cache issues — degraded performance (full scan) is the fallback.

## Data Flow (Batch Run)

```
run_batch(input_folder)
  → nas_store.get_pdf_paths(input_folder)
      → read pdf_index.json
      → os.scandir(input_folder)            # 1 network call
      → compare folder mtimes
      → ThreadPoolExecutor: scan stale dirs  # parallel
      → merge + sort paths
      → write pdf_index.json
  → _run_pdf_list(pdf_paths, ...)           # unchanged
```

## Files Changed

| File | Change |
|------|--------|
| `nas_store.py` | **New** — owns PDF index cache and registry path logic |
| `batch.py` | Replace `rglob` block in `run_batch` with `nas_store.get_pdf_paths` call |
| `point_id.py` | Read/write registry path via `nas_store.get_registry_path` |

## Testing

- `tests/test_nas_store.py` — unit tests using `tmp_path` (pytest fixture) to simulate NAS:
  - Cold cache: all folders scanned, cache written
  - Warm cache: no stale folders, returns instantly from cache
  - Partial stale: one folder changed, only that folder re-scanned
  - Corrupted `pdf_index.json`: cache rebuilt cleanly
  - Unreachable path: falls back to `rglob`, no crash
  - Registry migration: local file promoted to NAS on first use
- Existing batch and scan tests: unchanged (interface unchanged)
