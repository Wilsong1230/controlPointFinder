"""
Datum standardization: convert control point records toward NAD 83 / NAVD 1988.

Uses NOAA NCAT when online; falls back to pyproj (horizontal NAD27→NAD83 and
VERTCON grid where PROJ can resolve it). Preserves original coordinates and
datums on each record for audit.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

import requests
from pyproj import Transformer

_tls = threading.local()


def _ncat_session() -> requests.Session:
    if not hasattr(_tls, "session"):
        _tls.session = requests.Session()
    return _tls.session

NAVD88_LABEL = "NAVD 1988"
NAD83_LABEL = "NAD 83"

NCAT_URL = "https://geodesy.noaa.gov/api/ncat/llh"
NCAT_TIMEOUT = 8.0

# Exact US Survey foot definition (same as NGVD/NAVD engineering practice)
METERS_PER_US_SURVEY_FOOT = 1200.0 / 3937.0

LogFn = Optional[Callable[[str], None]]

# (coordinate_system normalized, horizontal_datum normalized) -> source SPC EPSG
CRS_SPC_EPSG: dict[tuple[str, str], str] = {
    ("florida state plane, west zone", "nad 83"): "EPSG:2882",
    ("florida state plane, west zone", "nad 27"): "EPSG:32040",
}

TARGET_SPC_EPSG = "EPSG:2882"  # NAD83 / Florida West (ftUS)
WGS84_EPSG = "EPSG:4326"
NAD83_GEO_EPSG = "EPSG:4269"
NAD27_GEO_EPSG = "EPSG:4267"

# PROJ VERTCON grid (may download via PROJ_NETWORK on first use)
_VERTCON_PIPELINE = (
    "+proj=pipeline "
    "+step +proj=axisswap +order=2,1 "
    "+step +proj=unitconvert +xy_in=deg +xy_out=rad "
    "+step +proj=vgridshift +grids=us_noaa_vertconc.tif "
    "+step +proj=unitconvert +xy_in=rad +xy_out=deg "
    "+step +proj=axisswap +order=2,1"
)


def _norm_datum_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _compact_datum_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def needs_conversion(record: dict[str, Any]) -> tuple[bool, bool]:
    """
    Return (needs_vertical, needs_horizontal) for conversion toward
    NAVD 1988 / NAD 83.
    """
    v_raw = str(record.get("vertical_datum") or "")
    h_raw = str(record.get("horizontal_datum") or "")

    v_norm = _norm_datum_text(v_raw)

    needs_vertical = False
    if v_norm and "navd" not in v_norm:
        if "ngvd" in v_norm and "1929" in v_norm:
            needs_vertical = True
        elif _compact_datum_text(v_raw) == "ngvd1929":
            needs_vertical = True

    h_norm = _norm_datum_text(h_raw)
    h_compact = _compact_datum_text(h_raw)

    needs_horizontal = False
    if h_norm:
        if h_compact == "nad27" or h_norm == "nad 27":
            needs_horizontal = True

    return needs_vertical, needs_horizontal


def _lookup_spc_epsg(coordinate_system: str, horizontal_datum: str) -> Optional[str]:
    """
    Resolve SPC EPSG for known zones. If horizontal datum is omitted in the PDF
    metadata but the zone is Florida West, assume NAD 83 (typical for current
    plans); NAD 27 must appear explicitly in metadata to use EPSG:32040.
    """
    coord = _norm_datum_text(coordinate_system)
    horiz = _norm_datum_text(horizontal_datum)
    key = (coord, horiz)
    if key in CRS_SPC_EPSG:
        return CRS_SPC_EPSG[key]
    if not horiz and (coord, "nad 83") in CRS_SPC_EPSG:
        return CRS_SPC_EPSG[(coord, "nad 83")]
    return None


def _feet_us_to_meters(feet: float) -> float:
    return feet * METERS_PER_US_SURVEY_FOOT


def _meters_to_feet_us(meters: float) -> float:
    return meters / METERS_PER_US_SURVEY_FOOT


def _state_plane_to_lonlat_wgs84(easting: float, northing: float, spc_epsg: str) -> tuple[float, float]:
    transformer = Transformer.from_crs(spc_epsg, WGS84_EPSG, always_xy=True)
    return transformer.transform(easting, northing)


def _state_plane_to_lonlat_geo(easting: float, northing: float, spc_epsg: str, geo_epsg: str) -> tuple[float, float]:
    transformer = Transformer.from_crs(spc_epsg, geo_epsg, always_xy=True)
    return transformer.transform(easting, northing)


def _lonlat_to_state_plane_nad83_west(lon: float, lat: float) -> tuple[float, float]:
    transformer = Transformer.from_crs(WGS84_EPSG, TARGET_SPC_EPSG, always_xy=True)
    return transformer.transform(lon, lat)


def _parse_ncat_scalar(value: Any) -> Optional[float]:
    if value is None or value == "N/A":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _convert_via_ncat(
    lat: float,
    lon: float,
    ortho_ht_m: Optional[float],
    needs_vertical: bool,
    needs_horizontal: bool,
    geographic_is_nad27: bool,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
    """
    Call NCAT llh. Returns (dest_lat, dest_lon, dest_orthoht_m, error_message).
    dest_orthoht_m is None if vertical was not part of the request.
    """
    params: dict[str, Any] = {"lat": lat, "lon": lon}

    if needs_horizontal or geographic_is_nad27:
        params["inDatum"] = "NAD27"
        params["outDatum"] = "NAD83(2011)"
    else:
        params["inDatum"] = "NAD83(1986)"
        params["outDatum"] = "NAD83(2011)"

    if needs_vertical:
        if ortho_ht_m is None:
            return None, None, None, "missing orthometric height for vertical conversion"
        params["inVertDatum"] = "NGVD29"
        params["outVertDatum"] = "NAVD88"
        params["orthoHt"] = ortho_ht_m

    try:
        response = _ncat_session().get(NCAT_URL, params=params, timeout=NCAT_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return None, None, None, f"ncat request failed: {exc}"

    dest_lat = _parse_ncat_scalar(payload.get("destLat"))
    dest_lon = _parse_ncat_scalar(payload.get("destLon"))
    dest_ortho = _parse_ncat_scalar(payload.get("destOrthoht"))

    if dest_lat is None or dest_lon is None:
        return None, None, None, "ncat response missing destLat/destLon"

    if needs_vertical and dest_ortho is None:
        return None, None, None, "ncat response missing destOrthoht"

    return dest_lat, dest_lon, dest_ortho, None


def _pyproj_horizontal_nad27_to_nad83(lon: float, lat: float) -> tuple[float, float]:
    transformer = Transformer.from_crs(NAD27_GEO_EPSG, NAD83_GEO_EPSG, always_xy=True)
    return transformer.transform(lon, lat)


def _pyproj_vertical_ngvd29_to_navd88(lon: float, lat: float, z_m: float) -> tuple[float, float, float]:
    """Apply VERTCON via vgridshift pipeline. lon/lat in decimal degrees."""
    transformer = Transformer.from_pipeline(_VERTCON_PIPELINE)
    return transformer.transform(lon, lat, z_m)


def _convert_via_pyproj(
    lon_geo: float,
    lat_geo: float,
    ortho_ht_m: Optional[float],
    needs_vertical: bool,
    needs_horizontal: bool,
    geographic_is_nad27: bool,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
    """
    Fallback when NCAT fails. lon_geo/lat_geo match the horizontal datum of the
    source (NAD27 or NAD83 geographic). Returns (lon, lat, z_m, error) in the
    same geographic frame as the last step (NAD83 degrees if horizontal ran).
    """
    lon_work, lat_work = lon_geo, lat_geo
    z_work = ortho_ht_m

    try:
        if needs_horizontal:
            if not geographic_is_nad27:
                return None, None, None, "pyproj horizontal fallback requires NAD27 geographic"
            lon_work, lat_work = _pyproj_horizontal_nad27_to_nad83(lon_work, lat_work)

        if needs_vertical:
            if z_work is None:
                return None, None, None, "missing orthometric height for pyproj vertical"
            lon_work, lat_work, z_work = _pyproj_vertical_ngvd29_to_navd88(lon_work, lat_work, z_work)

        return lon_work, lat_work, z_work, None
    except Exception as exc:
        return None, None, None, f"pyproj fallback failed: {exc}"


def _format_coord(value: float) -> str:
    text = f"{value:.10f}"
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def standardize_record(record: dict[str, Any], log: LogFn = None) -> dict[str, Any]:
    """Normalize datums on a single record in place; returns the same dict."""
    needs_vertical, needs_horizontal = needs_conversion(record)

    easting = str(record.get("easting") or "").strip()
    northing = str(record.get("northing") or "").strip()
    elevation = str(record.get("elevation") or "").strip()
    h_datum = str(record.get("horizontal_datum") or "").strip()
    v_datum = str(record.get("vertical_datum") or "").strip()
    coord_sys = str(record.get("coordinate_system") or "").strip()

    record["original_easting"] = easting
    record["original_northing"] = northing
    record["original_elevation"] = elevation
    record["original_horizontal_datum"] = h_datum
    record["original_vertical_datum"] = v_datum

    spc_epsg = _lookup_spc_epsg(coord_sys, h_datum)
    if spc_epsg is None:
        record["conversion_method"] = "none"
        record["conversion_status"] = "skipped: unsupported crs or missing metadata"
        record["latitude"] = ""
        record["longitude"] = ""
        return record

    try:
        e_f = float(easting)
        n_f = float(northing)
        elev_f = float(elevation)
    except ValueError:
        record["conversion_method"] = "none"
        record["conversion_status"] = "skipped: invalid numeric coordinates"
        record["latitude"] = ""
        record["longitude"] = ""
        return record

    geographic_is_nad27 = _norm_datum_text(h_datum) == "nad 27"

    lon_wgs84, lat_wgs84 = _state_plane_to_lonlat_wgs84(e_f, n_f, spc_epsg)
    record["longitude"] = _format_coord(lon_wgs84)
    record["latitude"] = _format_coord(lat_wgs84)

    if not needs_vertical and not needs_horizontal:
        record["conversion_method"] = "none"
        record["conversion_status"] = "already_target"
        return record

    if not coord_sys:
        record["conversion_method"] = "none"
        record["conversion_status"] = "skipped: missing coordinate system"
        return record

    ortho_m = _feet_us_to_meters(elev_f) if needs_vertical else None

    if geographic_is_nad27 or needs_horizontal:
        ncat_lon, ncat_lat = _state_plane_to_lonlat_geo(e_f, n_f, spc_epsg, NAD27_GEO_EPSG)
    else:
        ncat_lon, ncat_lat = _state_plane_to_lonlat_geo(e_f, n_f, spc_epsg, NAD83_GEO_EPSG)

    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    dest_ortho_m: Optional[float] = None
    method_used = "ncat"
    err: Optional[str] = None

    dest_lat, dest_lon, dest_ortho_m, err = _convert_via_ncat(
        ncat_lat,
        ncat_lon,
        ortho_m,
        needs_vertical,
        needs_horizontal,
        geographic_is_nad27,
    )

    if err:
        if log:
            log(f"  Datum NCAT: {err}; trying pyproj…")
        method_used = "pyproj"
        dest_lon, dest_lat, dest_ortho_m, err = _convert_via_pyproj(
            ncat_lon,
            ncat_lat,
            ortho_m,
            needs_vertical,
            needs_horizontal,
            geographic_is_nad27,
        )

    if err or dest_lat is None or dest_lon is None:
        record["conversion_method"] = "none"
        record["conversion_status"] = f"failed: {err or 'unknown conversion error'}"
        return record

    e_out, n_out = _lonlat_to_state_plane_nad83_west(dest_lon, dest_lat)

    if needs_vertical and dest_ortho_m is not None:
        elev_out = _meters_to_feet_us(dest_ortho_m)
    else:
        elev_out = elev_f

    record["easting"] = f"{e_out:.4f}".rstrip("0").rstrip(".")
    record["northing"] = f"{n_out:.4f}".rstrip("0").rstrip(".")
    record["elevation"] = f"{elev_out:.4f}".rstrip("0").rstrip(".")
    record["horizontal_datum"] = NAD83_LABEL
    record["vertical_datum"] = NAVD88_LABEL if needs_vertical else v_datum
    record["coordinate_system"] = "Florida State Plane, West Zone"
    record["conversion_method"] = method_used
    record["conversion_status"] = "converted"

    lon_wgs_out, lat_wgs_out = _state_plane_to_lonlat_wgs84(e_out, n_out, TARGET_SPC_EPSG)
    record["longitude"] = _format_coord(lon_wgs_out)
    record["latitude"] = _format_coord(lat_wgs_out)

    return record


def standardize_records(records: list[dict[str, Any]], log: LogFn = None) -> list[dict[str, Any]]:
    """Standardize a list of records in place."""
    if not records:
        return records
    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda r: standardize_record(r, log=log), records))
    return records
