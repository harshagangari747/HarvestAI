"""
Satellite Ingestion Module — Sentinel-2 L2A via EarthSearch STAC

Pipeline:
  1. STAC search for latest clear scene over the field polygon
  2. Download required bands (B04, B08, B11, B05, SCL) as COGs via rio-tiler
  3. Cloud-mask using SCL
  4. Compute NDVI, NDMI, NDRE, CIre
  5. Compute field-level stats + spatial variability zones
  6. Generate NDVI/NDMI/NDRE colourised PNG previews → S3
  7. Return structured observation dict

EarthSearch STAC v1 endpoint: https://earth-search.aws.element84.com/v1
Collection: sentinel-2-l2a
No API key required.
"""

import io
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import boto3
import numpy as np
import requests
from PIL import Image

logger = logging.getLogger(__name__)

STAC_ENDPOINT   = "https://earth-search.aws.element84.com/v1"
STAC_COLLECTION = "sentinel-2-l2a"
CLOUD_FILTER    = 30          # Max scene-level cloud cover % to consider
MIN_VALID_FRAC  = 0.40        # Min valid pixel fraction after SCL masking
MAX_SEARCH_DAYS = 30          # How far back to look for a clear scene

# SCL classes to KEEP (valid land pixels)
# 4=Vegetation, 5=Bare Soil, 6=Water
VALID_SCL_CLASSES = {4, 5, 6}

s3 = boto3.client("s3")


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _unwrap_geometry(geometry: Dict[str, Any]) -> Dict[str, Any]:
    """
    EarthSearch STAC v1 `intersects` requires a bare GeoJSON Geometry object
    (e.g. {"type":"Polygon","coordinates":[...]}), NOT a Feature or
    FeatureCollection wrapper.

    Also converts any Decimal values (DynamoDB artefact) back to float so
    rio-tiler and the STAC API can iterate over coordinates.
    """
    import decimal

    def _floatify(obj):
        """Recursively convert Decimal → float throughout the geometry."""
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, dict):
            return {k: _floatify(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_floatify(i) for i in obj]
        return obj

    geom = _floatify(geometry)

    if geom.get("type") == "Feature":
        return geom.get("geometry", geom)
    if geom.get("type") == "FeatureCollection":
        features = geom.get("features", [])
        if features:
            return _unwrap_geometry(features[0])
    return geom


# ── STAC search ───────────────────────────────────────────────────────────────

def search_sentinel2(
    geometry: Dict[str, Any],
    days_back: int = MAX_SEARCH_DAYS,
    max_cloud: int = CLOUD_FILTER,
) -> List[Dict[str, Any]]:
    """
    Search EarthSearch STAC v1 for Sentinel-2 L2A scenes over the field polygon.

    Uses the CQL2-JSON filter extension (replacing the deprecated `query`
    extension that was removed in EarthSearch v1).

    Returns items sorted by cloud cover ascending (clearest first).
    """
    bare_geometry = _unwrap_geometry(geometry)

    end_dt   = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days_back)

    body = {
        "collections": [STAC_COLLECTION],
        "intersects":  bare_geometry,
        "datetime":    (
            f"{start_dt.strftime('%Y-%m-%dT00:00:00Z')}/"
            f"{end_dt.strftime('%Y-%m-%dT23:59:59Z')}"
        ),
        # CQL2-JSON filter (EarthSearch v1 dropped the old `query` extension)
        "filter": {
            "op": "lte",
            "args": [
                {"property": "eo:cloud_cover"},
                max_cloud
            ]
        },
        "filter-lang": "cql2-json",
        # No sortby — EarthSearch v1's Elasticsearch backend doesn't support
        # OAFeat sortby syntax reliably. Sort client-side after results return.
        "limit": 10,
    }

    url = f"{STAC_ENDPOINT}/search"
    logger.info(
        f"STAC search: collection={STAC_COLLECTION} "
        f"cloud<={max_cloud}% days_back={days_back}"
    )

    try:
        resp = requests.post(url, json=body, timeout=20)
        # Log body on failure to aid debugging
        if not resp.ok:
            logger.error(
                f"STAC 400 response body: {resp.text[:500]}"
            )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"STAC search failed: {e}")
        raise

    features = resp.json().get("features", [])
    # Sort by cloud cover ascending (clearest first) — done client-side
    # because EarthSearch v1's sortby is unreliable
    features.sort(key=lambda f: f.get("properties", {}).get("eo:cloud_cover", 999))
    logger.info(f"STAC found {len(features)} candidate scenes")
    return features


# ── Band reading via rio-tiler ────────────────────────────────────────────────

def read_band_over_polygon(
    asset_href: str,
    geometry: Dict[str, Any],
) -> Tuple[np.ndarray, float]:
    """
    Read a single COG band clipped to the field polygon using rio-tiler.

    Returns:
        (data array float32, valid_pixel_fraction 0–1)
    """
    from rio_tiler.io import COGReader

    with COGReader(asset_href) as cog:
        img = cog.feature(geometry, max_size=512)

    arr  = img.data.squeeze().astype(np.float32)
    mask = img.mask.squeeze()   # 0 = masked, 255 = valid

    valid_fraction = float((mask > 0).sum()) / max(mask.size, 1)
    arr[mask == 0] = np.nan
    return arr, valid_fraction


def read_scl_over_polygon(
    scl_href: str,
    geometry: Dict[str, Any],
) -> np.ndarray:
    """Read the SCL (Scene Classification Layer) band."""
    from rio_tiler.io import COGReader

    with COGReader(scl_href) as cog:
        img = cog.feature(geometry, max_size=512)

    return img.data.squeeze()


# ── Cloud masking ─────────────────────────────────────────────────────────────

def build_valid_mask(scl: np.ndarray) -> np.ndarray:
    """Boolean mask: True = valid (vegetation / bare soil / water)."""
    mask = np.zeros(scl.shape, dtype=bool)
    for cls in VALID_SCL_CLASSES:
        mask |= (scl == cls)
    return mask


# ── Index computation ─────────────────────────────────────────────────────────

def _safe_ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    denom = a + b
    denom[denom == 0] = np.nan
    return (a - b) / denom


def compute_all_indices(
    b04: np.ndarray,   # Red
    b05: np.ndarray,   # Red-Edge 1
    b08: np.ndarray,   # NIR
    b11: np.ndarray,   # SWIR
    mask: np.ndarray,  # Boolean valid mask
) -> Dict[str, np.ndarray]:
    def apply(arr):
        out = arr.copy()
        out[~mask] = np.nan
        return out

    ndvi = apply(np.clip(_safe_ratio(b08, b04), -1, 1))
    ndmi = apply(np.clip(_safe_ratio(b08, b11), -1, 1))
    ndre = apply(np.clip(_safe_ratio(b08, b05), -1, 1))

    cire_denom = b05.copy().astype(float)
    cire_denom[cire_denom == 0] = np.nan
    cire = apply(b08.astype(float) / cire_denom - 1)

    return {"ndvi": ndvi, "ndmi": ndmi, "ndre": ndre, "cire": cire}


# ── Statistics ────────────────────────────────────────────────────────────────

def field_stats(arr: np.ndarray) -> Dict[str, Any]:
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return {"mean": None, "median": None, "p10": None, "p90": None,
                "std": None, "cv": None, "count": 0}
    mean = float(np.mean(valid))
    std  = float(np.std(valid))
    return {
        "mean":   round(mean, 4),
        "median": round(float(np.median(valid)), 4),
        "p10":    round(float(np.percentile(valid, 10)), 4),
        "p90":    round(float(np.percentile(valid, 90)), 4),
        "std":    round(std, 4),
        "cv":     round(std / (abs(mean) + 1e-6), 4),
        "count":  int(valid.size),
    }


def zone_stats(ndvi: np.ndarray) -> Dict[str, Any]:
    valid = ndvi[~np.isnan(ndvi)]
    if valid.size == 0:
        return {}
    p33 = float(np.percentile(valid, 33))
    p66 = float(np.percentile(valid, 66))
    total = float(valid.size)

    def z(arr):
        return {
            "pct_area":  round(arr.size / total * 100, 1) if total else 0,
            "mean_ndvi": round(float(np.mean(arr)), 4) if arr.size else None,
        }

    return {
        "p33": round(p33, 4),
        "p66": round(p66, 4),
        "lowZone":  z(ndvi[ndvi < p33]),
        "midZone":  z(ndvi[(ndvi >= p33) & (ndvi < p66)]),
        "highZone": z(ndvi[ndvi >= p66]),
    }


# ── PNG preview ───────────────────────────────────────────────────────────────

_NDVI_COLORMAP = [
    (-0.2, (170,  0,   0)),
    (0.1,  (210, 130,  50)),
    (0.3,  (255, 210,  80)),
    (0.5,  (120, 200,  80)),
    (0.7,  (40,  140,  40)),
    (1.0,  (0,    80,  20)),
]

def _interp_color(v: float, cmap) -> Tuple[int, int, int]:
    for i in range(len(cmap) - 1):
        v0, c0 = cmap[i]
        v1, c1 = cmap[i + 1]
        if v0 <= v <= v1:
            t = (v - v0) / (v1 - v0)
            return tuple(int(c0[j] + t * (c1[j] - c0[j])) for j in range(3))
    return cmap[-1][1]


def raster_to_png_bytes(arr: np.ndarray, vmin=-0.2, vmax=1.0) -> bytes:
    h, w = arr.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    nan_mask = np.isnan(arr)
    for y in range(h):
        for x in range(w):
            if nan_mask[y, x]:
                rgb[y, x] = (50, 50, 50)
            else:
                rgb[y, x] = _interp_color(
                    float(np.clip(arr[y, x], vmin, vmax)), _NDVI_COLORMAP
                )
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def upload_preview_to_s3(
    png_bytes: bytes, bucket: str, field_id: str,
    index_name: str, scene_date: str,
) -> str:
    key = f"fields/{field_id}/previews/{index_name}_{scene_date}.png"
    s3.put_object(
        Bucket=bucket, Key=key, Body=png_bytes,
        ContentType="image/png", CacheControl="max-age=86400",
    )
    return f"s3://{bucket}/{key}"


# ── Per-scene processing (shared by single-scene and backfill paths) ──────────

def _process_scene(
    scene: Dict[str, Any],
    bare_geometry: Dict[str, Any],
    field_id: str,
    data_bucket: str,
) -> Dict[str, Any]:
    """
    Process ONE already-selected STAC scene into an observation dict: read
    bands, cloud-mask, compute indices, upload previews, return stats.

    Extracted from ingest_satellite() so both the single-scene daily path and
    the multi-scene historical backfill path (backfill_satellite_observations)
    can reuse the same processing logic per scene.

    Returns:
        Observation dict (status="success") or
        {"status": "too_cloudy" | "missing_bands", ...}
    """
    assets     = scene.get("assets", {})
    props      = scene.get("properties", {})
    scene_date = props.get("datetime", "")[:10]
    cloud_pct  = props.get("eo:cloud_cover", 100)

    logger.info(f"Processing scene date={scene_date} cloud={cloud_pct}%")

    # Read bands — try both short (red, nir) and long (B04, B08) asset keys
    def _get_href(keys):
        for k in keys:
            href = assets.get(k, {}).get("href")
            if href:
                return href
        return None

    band_map = {
        "b04": _get_href(["red",      "B04", "b04"]),
        "b08": _get_href(["nir",      "B08", "b08", "nir08"]),
        "b11": _get_href(["swir16",   "B11", "b11", "swir"]),
        "b05": _get_href(["rededge1", "B05", "b05"]),
    }

    missing = [k for k, v in band_map.items() if not v]
    if missing:
        logger.warning(
            f"Missing band assets {missing} in scene {scene.get('id')}. "
            f"Available: {list(assets.keys())}"
        )
        return {"status": "missing_bands", "missing": missing,
                "fieldId": field_id,
                "observationDate": scene_date or (datetime.utcnow().isoformat() + "Z")}

    bands = {}
    for band_name, href in band_map.items():
        arr, _ = read_band_over_polygon(href, bare_geometry)
        bands[band_name] = arr

    # Normalize all bands to the same shape (B08 = 10m reference resolution).
    # B05 and B11 are 20m native so may come back at a smaller pixel count.
    ref_shape = bands["b08"].shape

    def _resize_band(arr: np.ndarray, target_shape) -> np.ndarray:
        """Nearest-neighbour resize using numpy index arithmetic (no scipy)."""
        if arr.shape == target_shape:
            return arr
        th, tw = target_shape
        sh, sw = arr.shape
        row_idx = (np.arange(th) * sh / th).astype(int)
        col_idx = (np.arange(tw) * sw / tw).astype(int)
        return arr[np.ix_(row_idx, col_idx)]

    for bname in ["b04", "b05", "b11"]:
        bands[bname] = _resize_band(bands[bname], ref_shape)

    # SCL mask — resize to match band shape if different resolution
    scl_href = _get_href(["scl", "SCL"])
    if scl_href:
        scl  = read_scl_over_polygon(scl_href, bare_geometry)
        band_shape = bands["b08"].shape
        if scl.shape != band_shape:
            from PIL import Image as PILImage
            scl_img = PILImage.fromarray(scl.astype("uint8"))
            scl_img = scl_img.resize(
                (band_shape[1], band_shape[0]), PILImage.NEAREST
            )
            scl = np.array(scl_img)
        mask = build_valid_mask(scl)
    else:
        mask = ~np.isnan(bands["b08"])

    valid_pixel_fraction = float(mask.sum()) / max(mask.size, 1)
    logger.info(f"Valid pixel fraction: {valid_pixel_fraction:.2%}")

    if valid_pixel_fraction < MIN_VALID_FRAC:
        logger.info(f"Scene too cloudy ({valid_pixel_fraction:.1%}). Skipping.")
        return {"status": "too_cloudy", "cloudCoverPct": cloud_pct,
                "validPixelFraction": round(valid_pixel_fraction, 3),
                "fieldId": field_id, "observationDate": scene_date}

    # Compute indices
    indices = compute_all_indices(
        b04=bands["b04"], b05=bands["b05"],
        b08=bands["b08"], b11=bands["b11"],
        mask=mask,
    )

    # Statistics
    stats = {idx: field_stats(arr) for idx, arr in indices.items()}
    zones = zone_stats(indices["ndvi"])

    # PNG previews → S3
    preview_urls = {}
    for idx_name in ["ndvi", "ndmi", "ndre"]:
        try:
            png = raster_to_png_bytes(indices[idx_name])
            uri = upload_preview_to_s3(png, data_bucket, field_id, idx_name, scene_date)
            preview_urls[idx_name] = uri
        except Exception as e:
            logger.warning(f"Preview upload failed for {idx_name}: {e}")

    # Confidence
    quality = "high" if valid_pixel_fraction >= 0.70 else \
              "medium" if valid_pixel_fraction >= 0.40 else "low"

    return {
        "status":             "success",
        "fieldId":            field_id,
        "observationDate":    scene_date,
        "sceneCloudPct":      round(cloud_pct, 1),
        "validPixelFraction": round(valid_pixel_fraction, 3),
        "quality":            quality,
        "indices": {
            "ndvi": stats["ndvi"],
            "ndmi": stats["ndmi"],
            "ndre": stats["ndre"],
            "cire": stats["cire"],
        },
        "zones":       zones,
        "previewUrls": preview_urls,
        "stacItemId":  scene.get("id"),
        "satellite":   "Sentinel-2 L2A",
        "processedAt": datetime.utcnow().isoformat() + "Z",
    }


# ── Main entry ────────────────────────────────────────────────────────────────

def ingest_satellite(
    field: Dict[str, Any],
    data_bucket: str,
    last_clear_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Single most-recent-scene Sentinel-2 ingestion pipeline for one field.
    Used by the daily batch pipeline (one new observation per run).

    Args:
        field:            DynamoDB field record (needs geometry, fieldId)
        data_bucket:      S3 bucket name for PNG previews
        last_clear_date:  ISO date of last confirmed clear observation (limits search window)

    Returns:
        Observation dict (status="success") or
        {"status": "no_new_scene" | "too_cloudy" | "missing_bands", ...}
    """
    geometry = field["geometry"]
    field_id = field["fieldId"]

    # Always pass a bare geometry to STAC
    bare_geometry = _unwrap_geometry(geometry)

    days_back = MAX_SEARCH_DAYS
    if last_clear_date:
        delta = (datetime.utcnow() - datetime.fromisoformat(last_clear_date)).days + 2
        days_back = max(delta, 6)

    # 1. STAC search
    scenes = search_sentinel2(bare_geometry, days_back=days_back)
    if not scenes:
        logger.info(f"No Sentinel-2 scenes found for field {field_id}")
        return {"status": "no_new_scene", "fieldId": field_id,
                "observationDate": datetime.utcnow().isoformat() + "Z"}

    # 2. Pick clearest scene (already sorted by cloud cover) and process it
    best = scenes[0]
    return _process_scene(best, bare_geometry, field_id, data_bucket)


# ── Historical backfill (multiple scenes in one call) ─────────────────────────

def backfill_satellite_observations(
    field: Dict[str, Any],
    data_bucket: str,
    num_scenes: int = 7,
    days_back: int = 120,
    search_limit: int = 30,
) -> List[Dict[str, Any]]:
    """
    Fetch and process up to `num_scenes` of the most recent historical
    Sentinel-2 captures for a field in one call — used when a field is first
    created, so the dashboard has a real multi-capture trend history
    immediately instead of waiting ~num_scenes daily batch runs for it to
    accumulate one observation at a time.

    Unlike ingest_satellite() (which takes the single clearest scene within a
    narrow rolling window), this widens the search window and walks scenes
    NEWEST-FIRST BY DATE (not by cloud cover), processing each one until
    `num_scenes` successful ("status": "success") observations are collected
    or candidates run out. Scenes that fail processing (too cloudy, missing
    bands) are skipped and do not count toward num_scenes, but do not stop
    the walk either — the next-older scene is tried instead.

    Args:
        field:         DynamoDB field record (needs geometry, fieldId)
        data_bucket:   S3 bucket name for PNG previews
        num_scenes:    Max number of successful observations to return (default 7)
        days_back:     How far back to search for candidate scenes (default 120)
        search_limit:  Max candidate scenes to request from STAC (default 30)

    Returns:
        List of successful observation dicts, most recent first (may be
        shorter than num_scenes if fewer clear scenes exist in the window).
    """
    geometry = field["geometry"]
    field_id = field["fieldId"]
    bare_geometry = _unwrap_geometry(geometry)

    # search_sentinel2() hardcodes limit=10, too few candidates for a
    # multi-month backfill window — use the wide-limit variant instead.
    candidates = _search_sentinel2_wide(bare_geometry, days_back, CLOUD_FILTER, search_limit)

    if not candidates:
        logger.info(f"No historical Sentinel-2 scenes found for field {field_id} backfill")
        return []

    # Walk newest-first by acquisition date (not cloud-cover order), so the
    # returned set represents genuine chronological history rather than just
    # the clearest scenes bunched into one short window.
    candidates.sort(key=lambda f: f.get("properties", {}).get("datetime", ""), reverse=True)

    # De-duplicate multiple tiles/orbits captured on the same calendar date —
    # keep only the least-cloudy one per date.
    best_per_date: Dict[str, Dict[str, Any]] = {}
    for scene in candidates:
        d = (scene.get("properties", {}).get("datetime") or "")[:10]
        if not d:
            continue
        existing = best_per_date.get(d)
        if existing is None or (
            scene.get("properties", {}).get("eo:cloud_cover", 999)
            < existing.get("properties", {}).get("eo:cloud_cover", 999)
        ):
            best_per_date[d] = scene

    ordered_dates = sorted(best_per_date.keys(), reverse=True)

    observations: List[Dict[str, Any]] = []
    for d in ordered_dates:
        if len(observations) >= num_scenes:
            break
        scene = best_per_date[d]
        try:
            result = _process_scene(scene, bare_geometry, field_id, data_bucket)
        except Exception as e:
            logger.warning(f"Backfill: scene {d} processing failed: {e}")
            continue
        if result.get("status") == "success":
            observations.append(result)
        else:
            logger.info(f"Backfill: scene {d} skipped ({result.get('status')})")

    logger.info(
        f"Backfill for {field_id}: {len(observations)}/{num_scenes} captures "
        f"from {len(ordered_dates)} candidate date(s)"
    )
    return observations


def _search_sentinel2_wide(
    geometry: Dict[str, Any],
    days_back: int,
    max_cloud: int,
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Same STAC query as search_sentinel2() but with a caller-supplied `limit`
    (search_sentinel2() hardcodes limit=10, too few candidates for a
    multi-month backfill window).
    """
    bare_geometry = _unwrap_geometry(geometry)
    end_dt   = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days_back)

    body = {
        "collections": [STAC_COLLECTION],
        "intersects":  bare_geometry,
        "datetime":    (
            f"{start_dt.strftime('%Y-%m-%dT00:00:00Z')}/"
            f"{end_dt.strftime('%Y-%m-%dT23:59:59Z')}"
        ),
        "filter": {"op": "lte", "args": [{"property": "eo:cloud_cover"}, max_cloud]},
        "filter-lang": "cql2-json",
        "limit": limit,
    }

    url = f"{STAC_ENDPOINT}/search"
    logger.info(
        f"STAC wide search: collection={STAC_COLLECTION} "
        f"cloud<={max_cloud}% days_back={days_back} limit={limit}"
    )

    try:
        resp = requests.post(url, json=body, timeout=25)
        if not resp.ok:
            logger.error(f"STAC wide search error body: {resp.text[:500]}")
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"STAC wide search failed: {e}")
        raise

    features = resp.json().get("features", [])
    logger.info(f"STAC wide search found {len(features)} candidate scenes")
    return features
