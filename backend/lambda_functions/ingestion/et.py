"""
ET Ingestion Module — OpenET API

Fetches evapotranspiration (ET) time series for a field polygon.
Computes water balance deficit: deficit[t] = deficit[t-1] + ET[t] - (Rain[t] + Irrigation[t])

API docs: https://openetdata.org/developers
Requires: openet_api_key  (stored in Secrets Manager)
"""

import logging
import json
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

OPENET_BASE        = "https://openet-api.org"
OPENET_TIMESERIES  = f"{OPENET_BASE}/raster/timeseries/polygon"
OPENET_MODEL       = "ensemble"          # Ensemble mean — most reliable for MVP
OPENET_UNITS       = "mm"
OPENET_VARIABLE    = "et"


# ── OpenET API ────────────────────────────────────────────────────────────────

def fetch_et_timeseries(
    geometry: Dict[str, Any],
    api_key: str,
    start_date: str,
    end_date:   str,
    model:      str = OPENET_MODEL,
) -> List[Dict[str, Any]]:
    """
    Call OpenET raster/timeseries/polygon endpoint.

    Returns list of { date: "YYYY-MM-DD", et_mm: float } dicts sorted ascending.
    """
    if not api_key or api_key == "PLACEHOLDER":
        logger.warning("OpenET API key not configured — using ET0 fallback.")
        return []

    headers = {
        "Authorization": api_key,
        "Content-Type":  "application/json",
    }
    body = {
        "date_range":    [start_date, end_date],
        "interval":      "daily",
        "geometry":      geometry,
        "model":         model,
        "variable":      OPENET_VARIABLE,
        "units":         OPENET_UNITS,
        "file_format":   "JSON",
    }

    logger.info(f"Fetching OpenET ET: {start_date} → {end_date} model={model}")
    try:
        resp = requests.post(
            OPENET_TIMESERIES,
            headers=headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"OpenET API error {e.response.status_code}: {e.response.text[:300]}")
        return []
    except requests.exceptions.Timeout:
        logger.error("OpenET API timed out")
        return []

    raw = resp.json()

    # OpenET returns a list of { "time": "YYYY-MM-DD", "et": value }
    records = []
    for item in raw:
        et_val = item.get("et") or item.get("value")
        d      = item.get("time") or item.get("date")
        if d is not None and et_val is not None:
            records.append({
                "etDate": str(d)[:10],
                "et_mm":  round(float(et_val), 3),
            })

    records.sort(key=lambda r: r["etDate"])
    logger.info(f"OpenET returned {len(records)} daily ET values")
    return records


# ── ET0 fallback (from Open-Meteo weather) ────────────────────────────────────

def et_from_weather_records(weather_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    When OpenET is unavailable, use Open-Meteo's FAO-56 ET0 field as a proxy.

    weather_records should be the observed list from weather.py,
    each containing 'weatherDate' and 'et0_mm'.
    """
    result = []
    for rec in weather_records:
        et_val = rec.get("et0_mm")
        if et_val is not None:
            result.append({
                "etDate":  rec["weatherDate"],
                "et_mm":   round(float(et_val), 3),
                "source":  "ET0_Open-Meteo_fallback",
            })
    return result


# ── Water deficit calculation ─────────────────────────────────────────────────

def compute_water_deficit(
    et_records:          List[Dict[str, Any]],
    weather_records:     List[Dict[str, Any]],
    irrigation_events:   List[Dict[str, Any]],
    planting_date:       date,
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Compute a running daily water deficit from planting date.

    deficit[t] = deficit[t-1] + ET[t] - (Precip[t] + Irrigation[t])
    Negative deficit = surplus water.
    Positive deficit = water stress accumulating.

    Args:
        et_records:        [ {etDate: str, et_mm: float}, ... ]
        weather_records:   [ {weatherDate: str, precipitation_mm: float}, ... ]
        irrigation_events: [ {date: str, amount_mm: float}, ... ]  (from field record)
        planting_date:     date object

    Returns:
        (daily_balance_list, cumulative_deficit_mm)
    """
    # Build lookup dicts by date string
    et_by_date      = {r["etDate"]:      r["et_mm"]           for r in et_records}
    precip_by_date  = {r["weatherDate"]: r["precipitation_mm"] for r in weather_records}
    irrig_by_date: Dict[str, float] = {}
    for ev in irrigation_events:
        irrig_by_date[ev.get("date", "")] = float(ev.get("amount_mm", 0))

    # Determine date range: planting to today
    today = datetime.utcnow().date()
    all_dates = sorted(set(et_by_date) | set(precip_by_date))

    deficit     = 0.0
    daily_rows  = []

    for d_str in all_dates:
        d = date.fromisoformat(d_str)
        if d < planting_date or d > today:
            continue

        et_mm     = et_by_date.get(d_str, 0.0)
        rain_mm   = precip_by_date.get(d_str, 0.0)
        irrig_mm  = irrig_by_date.get(d_str, 0.0)
        supply_mm = rain_mm + irrig_mm

        daily_deficit = et_mm - supply_mm
        deficit      += daily_deficit

        daily_rows.append({
            "deficitDate":  d_str,
            "et_mm":        round(et_mm, 2),
            "precip_mm":    round(rain_mm, 2),
            "irrigation_mm": round(irrig_mm, 2),
            "supply_mm":    round(supply_mm, 2),
            "dailyDelta":   round(daily_deficit, 2),
            "cumulativeDeficit_mm": round(deficit, 2),
        })

    cumulative = round(deficit, 2)
    logger.info(f"Water deficit computed: {len(daily_rows)} days, cumulative={cumulative} mm")
    return daily_rows, cumulative


def water_stress_score(cumulative_deficit_mm: float, cap_mm: float = 150.0) -> float:
    """
    Normalise cumulative deficit to a 0–1 stress score.
    0 = no stress, 1 = maximum stress (deficit >= cap).
    """
    if cumulative_deficit_mm <= 0:
        return 0.0
    score = min(cumulative_deficit_mm / cap_mm, 1.0)
    return round(float(score), 3)


# ── Main entry ────────────────────────────────────────────────────────────────

def ingest_et(
    field: Dict[str, Any],
    api_keys: Dict[str, str],
    weather_records: List[Dict[str, Any]],
    last_et_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch ET, compute water deficit, return structured ET summary.

    Args:
        field:           DynamoDB field record
        api_keys:        Dict from Secrets Manager
        weather_records: Observed weather list from weather.ingest_weather()
        last_et_date:    ISO date of last stored ET value (for incremental fetch)

    Returns:
        {
            etRecords:            [ {etDate, et_mm}, ... ],
            dailyBalance:         [ {deficitDate, et_mm, precip_mm, ...}, ... ],
            cumulativeDeficit_mm: float,
            waterStressScore:     0.0–1.0,
            source:               "openet" | "et0_fallback",
            fetchedAt:            ISO timestamp
        }
    """
    geometry        = field["geometry"]
    irrigation_events = field.get("irrigationEvents", [])
    planting_date_str = field.get("plantingDate", "")

    try:
        planting_date = datetime.fromisoformat(
            planting_date_str.replace("Z", "+00:00")
        ).date()
    except Exception:
        planting_date = datetime.utcnow().date() - timedelta(days=60)

    # Date range for ET fetch
    start_date = last_et_date or planting_date.isoformat()
    end_date   = datetime.utcnow().strftime("%Y-%m-%d")

    openet_key  = api_keys.get("openet_api_key", "")
    et_records  = fetch_et_timeseries(geometry, openet_key, start_date, end_date)

    source = "openet"
    if not et_records:
        logger.info("Falling back to ET0 from Open-Meteo weather records")
        et_records = et_from_weather_records(weather_records)
        source = "et0_fallback"

    daily_balance, cumulative_deficit = compute_water_deficit(
        et_records, weather_records, irrigation_events, planting_date
    )

    stress_score = water_stress_score(cumulative_deficit)

    return {
        "etRecords":            et_records[-30:],    # keep last 30 days in status
        "dailyBalance":         daily_balance[-30:],
        "cumulativeDeficit_mm": cumulative_deficit,
        "waterStressScore":     stress_score,
        "source":               source,
        "fetchedAt":            datetime.utcnow().isoformat() + "Z",
    }
