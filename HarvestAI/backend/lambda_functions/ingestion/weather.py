"""
Weather Ingestion Module — Open-Meteo API

Fetches daily observed weather + 14-day forecast for a field centroid.
No API key required.

Docs: https://open-meteo.com/en/docs
"""

import requests
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# Temperature unit is Celsius from Open-Meteo; convert to Fahrenheit for GDD
C_TO_F = lambda c: c * 9 / 5 + 32

# Corn GDD constants (°F)
GDD_BASE = 50.0
GDD_CAP  = 86.0


# ── GDD helpers ──────────────────────────────────────────────────────────────

def compute_daily_gdd(tmin_f: float, tmax_f: float) -> float:
    """
    Corn GDD (base 50°F, cap 86°F).

    GDD = ((min(Tmax, 86) + max(Tmin, 50)) / 2) − 50
    Returns 0 if result is negative.
    """
    tmax_c = min(tmax_f, GDD_CAP)
    tmin_c = max(tmin_f, GDD_BASE)
    return max(0.0, (tmax_c + tmin_c) / 2.0 - GDD_BASE)


def accumulate_gdd(daily_records: List[Dict[str, Any]], planting_date: date) -> float:
    """
    Sum GDD from planting_date to today across all stored weather records.
    Expects each record to have keys: weatherDate (ISO str), gddDaily (float).
    """
    total = 0.0
    for rec in daily_records:
        rec_date = date.fromisoformat(rec["weatherDate"][:10])
        if rec_date >= planting_date:
            total += float(rec.get("gddDaily", 0.0))
    return round(total, 2)


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_weather(
    lat: float,
    lon: float,
    start_date: Optional[str] = None,
    forecast_days: int = 14,
) -> Dict[str, Any]:
    """
    Call Open-Meteo and return structured daily weather data.

    Uses two endpoints:
    - Historical API (open-meteo.com/v1/archive) for past dates
    - Forecast API  (open-meteo.com/v1/forecast)  for today + future

    Args:
        lat: Field centroid latitude
        lon: Field centroid longitude
        start_date: ISO date string (YYYY-MM-DD) for historical start.
                    Defaults to 30 days ago.
        forecast_days: How many future days to include (max 16 for free tier).

    Returns:
        {
            "observed": [ {weatherDate, tmin_f, tmax_f, precipitation_mm,
                           radiation_mj, gddDaily}, ... ],
            "forecast": [ same shape ... ],
            "fetchedAt": ISO timestamp
        }
    """
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    if start_date is None:
        start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")

    DAILY_VARS = [
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "shortwave_radiation_sum",
        "windspeed_10m_max",
        "et0_fao_evapotranspiration",
    ]

    COMMON_PARAMS = {
        "latitude":           lat,
        "longitude":          lon,
        "daily":              DAILY_VARS,
        "timezone":           "UTC",
        "temperature_unit":   "celsius",
        "windspeed_unit":     "ms",
        "precipitation_unit": "mm",
    }

    observed_records = []
    forecast_records = []

    # ── Historical: start_date → yesterday ────────────────────────────────
    hist_start = date.fromisoformat(start_date)
    if hist_start <= yesterday:
        hist_params = {
            **COMMON_PARAMS,
            "start_date": hist_start.strftime("%Y-%m-%d"),
            "end_date":   yesterday.strftime("%Y-%m-%d"),
        }
        logger.info(f"Fetching Open-Meteo archive lat={lat} lon={lon} "
                    f"{hist_params['start_date']} → {hist_params['end_date']}")
        try:
            resp = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params=hist_params, timeout=20
            )
            resp.raise_for_status()
            observed_records = _parse_daily_response(resp.json(), today)
        except Exception as e:
            logger.warning(f"Open-Meteo archive error: {e}")

    # ── Forecast: today → today + forecast_days ───────────────────────────
    fc_params = {
        **COMMON_PARAMS,
        "forecast_days": forecast_days,
    }
    logger.info(f"Fetching Open-Meteo forecast lat={lat} lon={lon} {forecast_days} days")
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=fc_params, timeout=15
        )
        resp.raise_for_status()
        all_fc = _parse_daily_response(resp.json(), today)
        # Split: dates <= today go into observed, future into forecast
        for rec in all_fc:
            rec_date = date.fromisoformat(rec["weatherDate"])
            if rec_date <= today:
                # Only add if not already in observed_records
                existing_dates = {r["weatherDate"] for r in observed_records}
                if rec["weatherDate"] not in existing_dates:
                    observed_records.append(rec)
            else:
                forecast_records.append(rec)
    except Exception as e:
        logger.warning(f"Open-Meteo forecast error: {e}")

    observed_records.sort(key=lambda r: r["weatherDate"])
    forecast_records.sort(key=lambda r: r["weatherDate"])

    logger.info(
        f"Weather fetched: {len(observed_records)} observed days, "
        f"{len(forecast_records)} forecast days"
    )

    return {
        "observed":  observed_records,
        "forecast":  forecast_records,
        "fetchedAt": datetime.utcnow().isoformat() + "Z",
    }


def _parse_daily_response(data: dict, today: date) -> List[Dict[str, Any]]:
    """Parse Open-Meteo daily JSON response into our record format."""
    daily = data.get("daily", {})
    dates       = daily.get("time", [])
    tmax_list   = daily.get("temperature_2m_max", [])
    tmin_list   = daily.get("temperature_2m_min", [])
    precip_list = daily.get("precipitation_sum", [])
    rad_list    = daily.get("shortwave_radiation_sum", [])
    wind_list   = daily.get("windspeed_10m_max", [])
    et0_list    = daily.get("et0_fao_evapotranspiration", [])

    records = []
    for i, d in enumerate(dates):
        tmax_c = tmax_list[i] if i < len(tmax_list) and tmax_list[i] is not None else 25.0
        tmin_c = tmin_list[i] if i < len(tmin_list) and tmin_list[i] is not None else 10.0
        tmax_f = round(C_TO_F(tmax_c), 2)
        tmin_f = round(C_TO_F(tmin_c), 2)
        gdd    = round(compute_daily_gdd(tmin_f, tmax_f), 2)

        records.append({
            "weatherDate":      d,
            "tmin_c":           round(tmin_c, 2),
            "tmax_c":           round(tmax_c, 2),
            "tmin_f":           tmin_f,
            "tmax_f":           tmax_f,
            "precipitation_mm": round(precip_list[i] if i < len(precip_list) and precip_list[i] is not None else 0.0, 2),
            "radiation_mj":     round(rad_list[i] if i < len(rad_list) and rad_list[i] is not None else 0.0, 2),
            "windspeed_ms":     round(wind_list[i] if i < len(wind_list) and wind_list[i] is not None else 0.0, 2),
            "et0_mm":           round(et0_list[i] if i < len(et0_list) and et0_list[i] is not None else 0.0, 2),
            "gddDaily":         gdd,
        })
    return records


# ── Heat stress helpers ───────────────────────────────────────────────────────

def count_heat_stress_days(forecast: List[Dict[str, Any]], threshold_f: float = 95.0) -> int:
    """
    Count forecast days where Tmax > threshold (default 95°F).
    Used to flag heat stress risk near tassel/silk window.
    """
    return sum(1 for r in forecast if r.get("tmax_f", 0) > threshold_f)


def heat_stress_flag(forecast_records: List[Dict[str, Any]], window: int = 7) -> Dict[str, Any]:
    """
    Returns heat stress summary over the next `window` days.
    """
    next_n = forecast_records[:window]
    stress_days = count_heat_stress_days(next_n)
    return {
        "heatStressDaysNext7":   stress_days,
        "heatStressSeverity":    "high" if stress_days >= 3 else "medium" if stress_days >= 1 else "none",
    }


# ── Maturity forecast ─────────────────────────────────────────────────────────

def predict_maturity_window(
    gdd_accumulated: float,
    target_gdd: float,
    forecast_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Walk forward through forecast GDD until target_gdd is reached.
    Returns three scenarios (pessimistic/normal/optimistic) as a window.

    Args:
        gdd_accumulated: GDD already accrued since planting
        target_gdd: GDD needed for physiological maturity (R6)
        forecast_records: List of forecast weather dicts with gddDaily

    Returns:
        { predictedDate, daysToMaturity, scenarioNote }
        or  { predictedDate: None, daysToMaturity: None, scenarioNote }
    """
    remaining = target_gdd - gdd_accumulated
    if remaining <= 0:
        return {
            "predictedDate":   datetime.utcnow().strftime("%Y-%m-%d"),
            "daysToMaturity":  0,
            "scenarioNote":    "GDD target already reached",
        }

    cumulative = 0.0
    today = datetime.utcnow().date()

    for i, rec in enumerate(forecast_records):
        cumulative += rec.get("gddDaily", 0.0)
        if cumulative >= remaining:
            predicted = today + timedelta(days=i + 1)
            return {
                "predictedDate":   predicted.isoformat(),
                "daysToMaturity":  i + 1,
                "scenarioNote":    "Forecast-based projection (14-day window)",
            }

    # Beyond forecast window — extrapolate from average forecast GDD/day
    if forecast_records:
        avg_gdd = sum(r.get("gddDaily", 0) for r in forecast_records) / len(forecast_records)
    else:
        avg_gdd = 10.0  # conservative fallback

    remaining_after_forecast = remaining - cumulative
    extra_days = int(remaining_after_forecast / avg_gdd) + 1 if avg_gdd > 0 else 999
    predicted = today + timedelta(days=len(forecast_records) + extra_days)

    return {
        "predictedDate":   predicted.isoformat(),
        "daysToMaturity":  len(forecast_records) + extra_days,
        "scenarioNote":    "Extrapolated beyond 14-day forecast using average GDD rate",
    }
