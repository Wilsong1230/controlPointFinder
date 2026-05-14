# Control Point Finder

A desktop app that extracts survey control points from engineering PDF plan sets. Drop in a folder of PDFs (or individual files), and it finds, parses, deduplicates, and exports all control points to CSV — ready to import into surveying software.

## What It Does

Engineering plan sets often contain control point tables listing benchmarks, monuments, and geodetic reference points. This tool reads those PDFs, extracts the data, standardizes datums (via NCAT), and produces clean CSVs with system-wide unique point IDs.

**Key features:**

- Drag-and-drop GUI — drop a folder or individual PDFs onto the window
- Batch mode — processes an entire NAS folder with a cached PDF index (warm runs are near-instant)
- Datum standardization — queries NOAA's NCAT API to normalize horizontal/vertical datums
- Deduplication — removes exact duplicates and flags uncertain duplicates for manual review
- Review modal — surfaces low-confidence extractions for human sign-off before export
- Per-PDF and combined CSVs — individual output per plan set plus a merged `all_control_points.csv`
- Shared point ID registry — stored on the NAS so IDs stay consistent across machines
- Zip export — outputs bundled as a `.zip` for easy sharing

## Output Format

Each extracted control point includes:

| Field | Description |
|-------|-------------|
| `system_point_id` | Unique ID assigned across all runs |
| `point_name` | Name/label from the plan set |
| `northing` / `easting` | Coordinates |
| `horizontal_datum` | Standardized datum (e.g., NAD83) |
| `vertical_datum` | Standardized vertical datum (e.g., NAVD88) |
| `elevation` | Elevation if present |
| `coordinate_system` | Projection or zone |
| `source_pdf` | Source file name |
| `confidence` | Extraction confidence score |

## Setup

**Requirements:** Python 3.11+

```bash
pip install -r requirements.txt
```

**Dependencies:**

| Package | Purpose |
|---------|---------|
| `PyMuPDF` | PDF text extraction |
| `pdfplumber` | Table parsing |
| `pyproj` | Coordinate system handling |
| `requests` | NCAT API calls |
| `tkinterdnd2` | Drag-and-drop support |

## Running

```bash
python gui.py
```

The GUI lets you:

- **Run Batch** — select a folder; discovers all PDFs using a cached index
- **Run on Selected Files** — drag and drop or browse for specific PDFs
- **Review** — approve or reject low-confidence extractions before export

## NAS / Network Folder Support

When your PDFs live on a NAS with thousands of files, discovery is optimized automatically:

- On first run, all folders are scanned in parallel (20 threads) and indexed
- On subsequent runs, only folders whose modification time changed are re-scanned
- The index is stored in `.controlpoint/pdf_index.json` inside the input folder
- The point ID registry is stored in `.controlpoint/point_id_registry.json` on the NAS so it's shared across machines

Cold scan: minutes. Warm scan: seconds.

## Project Structure

```
controlPointFinder/
├── gui.py                  # Tkinter desktop app
├── batch.py                # Batch processing orchestration
├── control_point.py        # PDF scanning and control point extraction
├── nas_store.py            # NAS-cached PDF discovery and shared registry
├── datum_standardization.py # NCAT API integration
├── point_id.py             # System-wide point ID assignment
├── output_control.py       # Deduplication and flagging
├── review_modal.py         # Manual review UI
├── confidence.py           # Extraction confidence scoring
├── data_validation.py      # Record validation
├── tests/                  # pytest test suite
└── requirements.txt
```

## Tests

```bash
pytest
```

All 51 tests cover extraction, deduplication, datum standardization, NAS cache behavior, and confidence scoring.
