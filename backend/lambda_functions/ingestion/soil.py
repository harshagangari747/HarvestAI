"""
Soil Ingestion Module — USDA NRCS SSURGO Soil Data Access (SDA)

Fetches dominant soil texture, drainage class, and available water capacity
for a field polygon via POST SQL query to the SDA REST endpoint.

No API key required.
Docs: https://sdmdataaccess.nrcs.usda.gov/
REST: https://sdmdataaccess.nrcs.usda.gov/Tabular/post.rest
"""

import json
import logging
import math
from typing import Dict, Any, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

SDA_ENDPOINT = "https://sdmdataaccess.nrcs.usda.gov/Tabular/post.rest"
SDA_TIMEOUT  = 20   # seconds


# ── Coordinate helpers ────────────────────────────────────────────────────────

def geometry_to_wkt(geometry: Dict[str, Any]) -> str:
    """
    Convert a GeoJSON Polygon to a WKT POLYGON string
    suitable for embedding in SDA SQL queries.
    """
    coords = geometry.get("coordinates", [[]])[0]
    pts = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"POLYGON(({pts}))"


def compute_centroid(geometry: Dict[str, Any]) -> Tuple[float, float]:
    """Return (lat, lon) centroid of a GeoJSON Polygon."""
    coords = geometry.get("coordinates", [[]])[0]
    if not coords:
        return 0.0, 0.0
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


# ── SDA query helpers ─────────────────────────────────────────────────────────

def _post_sda(query: str) -> Optional[List[Dict]]:
    """
    Execute a SQL query against the USDA SDA REST endpoint.
    Returns list-of-dicts from the first Table, or None on failure.
    """
    payload = {"format": "JSON+COLUMNNAME", "query": query}
    try:
        resp = requests.post(SDA_ENDPOINT, data=payload, timeout=SDA_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"SDA request failed: {e}")
        return None

    body = resp.json()
    tables = body.get("Table", [])
    if not tables:
        return []

    # First row is column names
    cols = tables[0]
    rows = []
    for row in tables[1:]:
        rows.append(dict(zip(cols, row)))
    return rows


# ── Main queries ──────────────────────────────────────────────────────────────

def fetch_map_unit_keys(wkt: str) -> List[str]:
    """
    Intersect the field polygon with SSURGO map units and return mukeys.
    """
    query = f"""
        SELECT DISTINCT mu.mukey
        FROM mapunit mu
        INNER JOIN mupolygon mp ON mu.mukey = mp.mukey
        WHERE mu.mukey IN (
            SELECT mukey
            FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
        )
    """
    rows = _post_sda(query)
    if not rows:
        return []
    return [r["mukey"] for r in rows if r.get("mukey")]


def fetch_soil_properties(mukeys: List[str]) -> List[Dict[str, Any]]:
    """
    Fetch dominant texture, drainage class, and available water capacity
    for a list of map unit keys.
    """
    if not mukeys:
        return []

    mukey_list = ", ".join(f"'{k}'" for k in mukeys)
    query = f"""
        SELECT
            mu.mukey,
            mu.muname,
            c.compname,
            c.comppct_r,
            c.drainagecl,
            c.taxorder,
            ch.hzname,
            ch.hzdept_r,
            ch.hzdepb_r,
            cht.texcl,
            ch.awc_r
        FROM mapunit mu
        INNER JOIN component c   ON mu.mukey = c.mukey
        INNER JOIN chorizon ch   ON c.cokey  = ch.cokey
        LEFT  JOIN chtexturegrp ctg ON ch.chkey = ctg.chkey AND ctg.rvindicator = 'Yes'
        LEFT  JOIN chtexture cht    ON ctg.chtgkey = cht.chtgkey
        WHERE mu.mukey IN ({mukey_list})
          AND c.majcompflag = 'Yes'
          AND ch.hzdept_r < 30   -- surface horizon (0-30 cm)
        ORDER BY mu.mukey, c.comppct_r DESC, ch.hzdept_r
    """
    rows = _post_sda(query)
    return rows or []


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate_soil_properties(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarise soil data rows into a single dominant texture, drainage class,
    and mean available water capacity (AWC).
    """
    if not rows:
        return _fallback_soil()

    # Weight by component percentage
    texture_votes:  Dict[str, float] = {}
    drainage_votes: Dict[str, float] = {}
    awc_values:     List[float]      = []

    for row in rows:
        pct = float(row.get("comppct_r") or 10)
        tex = row.get("texcl") or "Unknown"
        drn = row.get("drainagecl") or "Unknown"
        awc = row.get("awc_r")

        texture_votes[tex]  = texture_votes.get(tex, 0)  + pct
        drainage_votes[drn] = drainage_votes.get(drn, 0) + pct
        if awc is not None:
            try:
                awc_values.append(float(awc))
            except (TypeError, ValueError):
                pass

    dominant_texture  = max(texture_votes,  key=texture_votes.get)
    dominant_drainage = max(drainage_votes, key=drainage_votes.get)
    avg_awc = round(sum(awc_values) / len(awc_values), 3) if awc_values else None

    return {
        "dominantTexture":      dominant_texture,
        "drainageClass":        dominant_drainage,
        "availableWaterCap_cm_cm": avg_awc,
        "textureBreakdown":     texture_votes,
        "source":               "SSURGO_SDA",
    }


def _fallback_soil() -> Dict[str, Any]:
    """Return a generic fallback when SDA is unavailable."""
    return {
        "dominantTexture":         "Unknown",
        "drainageClass":           "Unknown",
        "availableWaterCap_cm_cm": None,
        "textureBreakdown":        {},
        "source":                  "fallback_no_data",
    }


# ── Main entry ────────────────────────────────────────────────────────────────

def fetch_soil_context(geometry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch SSURGO soil context for a field polygon.

    Called during field onboarding (one-time, cached in Fields table).

    Args:
        geometry: GeoJSON Polygon dict

    Returns:
        {
            dominantTexture, drainageClass, availableWaterCap_cm_cm,
            textureBreakdown, source
        }
    """
    logger.info("Fetching SSURGO soil data")

    wkt = geometry_to_wkt(geometry)

    # Step 1 — get map unit keys
    mukeys = fetch_map_unit_keys(wkt)
    if not mukeys:
        logger.warning("No SSURGO map units found for polygon — using fallback")
        return _fallback_soil()

    logger.info(f"Found {len(mukeys)} SSURGO map units")

    # Step 2 — fetch soil properties
    rows = fetch_soil_properties(mukeys[:10])  # cap at 10 mukeys

    # Step 3 — aggregate
    result = aggregate_soil_properties(rows)
    logger.info(f"Soil: texture={result['dominantTexture']} drainage={result['drainageClass']}")
    return result
