"""
Daily Batch Pipeline Lambda Handler

Orchestrates the full daily ingestion pipeline for every active field:

  1. Retrieve API keys from Secrets Manager (once, cached for the invocation)
  2. For each active field:
     a. Weather   — Open-Meteo observed + 14-day forecast, GDD accumulation
     b. Satellite — Sentinel-2 EarthSearch STAC, NDVI/NDMI/NDRE, S3 previews
     c. ET        — OpenET (with ET0 fallback), water deficit
     d. Metrics   — health score, stress indicators, maturity forecast
     e. AI Brief  — Amazon Bedrock (Claude) daily narrative
     f. Persist   — DynamoDB DailyStatus + Observations + Weather/ET cache tables

Triggered by:
  - EventBridge schedule (daily at 02:00 UTC)
  - Manual POST /fields/{fieldId}/run via API Gateway
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# ── Ingestion modules ─────────────────────────────────────────────────────────
from lambda_functions.ingestion.weather         import fetch_weather, accumulate_gdd, heat_stress_flag, predict_maturity_window
from lambda_functions.ingestion.satellite       import ingest_satellite, backfill_satellite_observations
from lambda_functions.ingestion.et              import ingest_et
from lambda_functions.ingestion.bedrock_brief   import generate_daily_brief
from lambda_functions.ingestion.vision_analysis import generate_image_trend_analysis

# Number of most-recent satellite captures to feed into the image trend analysis
VISION_ANALYSIS_CAPTURES = 7

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── AWS clients ───────────────────────────────────────────────────────────────
dynamodb        = boto3.resource("dynamodb")
secrets_client  = boto3.client("secretsmanager")

# ── DynamoDB tables (injected via Lambda env vars) ────────────────────────────
FIELDS_TABLE        = os.environ.get("FIELDS_TABLE",         "harvestai-fields-dev")
OBSERVATIONS_TABLE  = os.environ.get("OBSERVATIONS_TABLE",   "harvestai-observations-dev")
DAILY_STATUS_TABLE  = os.environ.get("DAILY_STATUS_TABLE",   "harvestai-dailystatus-dev")
WEATHER_TABLE       = os.environ.get("WEATHER_TABLE",        "harvestai-weather-dev")
ET_TABLE            = os.environ.get("ET_TABLE",             "harvestai-et-dev")
BATCH_LOG_TABLE     = os.environ.get("BATCH_LOG_TABLE",      "harvestai-batchlog-dev")
DATA_BUCKET         = os.environ.get("DATA_BUCKET",          "")
SECRETS_ARN         = os.environ.get("SECRETS_ARN",          "")

fields_table        = dynamodb.Table(FIELDS_TABLE)
observations_table  = dynamodb.Table(OBSERVATIONS_TABLE)
daily_status_table  = dynamodb.Table(DAILY_STATUS_TABLE)
weather_table       = dynamodb.Table(WEATHER_TABLE)
et_table            = dynamodb.Table(ET_TABLE)
batch_log_table     = dynamodb.Table(BATCH_LOG_TABLE)

# TTL offset for cached tables (90 days)
_TTL_DAYS = 90


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _floatify(obj: Any) -> Any:
    """Recursively convert Decimal (DynamoDB artefact) to float/int."""
    import decimal
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _floatify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_floatify(i) for i in obj]
    return obj


def _to_dynamo(obj: Any) -> Any:
    """
    Recursively convert floats → Decimal so DynamoDB put_item accepts them.
    DynamoDB does not accept Python float natively.
    """
    if isinstance(obj, float):
        return Decimal(str(round(obj, 6)))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(i) for i in obj]
    return obj


def _ttl(days: int = _TTL_DAYS) -> int:
    """Return Unix epoch timestamp `days` from now (for DynamoDB TTL attribute)."""
    return int((datetime.utcnow() + timedelta(days=days)).timestamp())


def _dedupe_weather_records(*record_lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge multiple weather record lists into one, keyed by weatherDate[:10].

    Lists are applied in order, so records from a later list overwrite
    records for the same date from an earlier list. Callers should pass
    cached (stale) records first and freshly-fetched records last, so the
    fresh observation wins — this prevents accumulate_gdd() from summing
    the same calendar day twice when cached_weather (read back from
    DynamoDB) and weather_result["observed"] (just fetched) overlap.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for records in record_lists:
        for rec in records or []:
            date_key = (rec.get("weatherDate") or "")[:10]
            if date_key:
                merged[date_key] = rec
    return [merged[d] for d in sorted(merged)]


def get_api_keys() -> Dict[str, str]:
    """Retrieve all API keys from Secrets Manager. Returns {} on failure."""
    if not SECRETS_ARN:
        logger.warning("SECRETS_ARN env var not set — running without API keys")
        return {}
    try:
        resp = secrets_client.get_secret_value(SecretId=SECRETS_ARN)
        return json.loads(resp["SecretString"])
    except ClientError as e:
        logger.error(f"Secrets Manager error: {e.response['Error']['Code']}: {e}")
        return {}


def get_active_fields() -> List[Dict[str, Any]]:
    """Scan the Fields table for all active fields."""
    try:
        resp = fields_table.scan(
            FilterExpression="attribute_exists(fieldId) AND #s = :active",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":active": "active"},
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.error(f"Failed to scan fields table: {e}")
        return []


def get_last_observation(field_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent satellite observation for a field."""
    try:
        resp = observations_table.query(
            KeyConditionExpression=Key("fieldId").eq(field_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.warning(f"Could not fetch last observation for {field_id}: {e}")
        return None


def get_recent_observations(field_id: str, limit: int = VISION_ANALYSIS_CAPTURES) -> List[Dict[str, Any]]:
    """Return up to `limit` most recent satellite observations, newest first."""
    try:
        resp = observations_table.query(
            KeyConditionExpression=Key("fieldId").eq(field_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return _floatify(resp.get("Items", []))
    except Exception as e:
        logger.warning(f"Could not fetch recent observations for {field_id}: {e}")
        return []


def get_cached_weather(field_id: str, days: int = 30) -> List[Dict[str, Any]]:
    """Return up to `days` stored weather records for GDD accumulation."""
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        resp = weather_table.query(
            KeyConditionExpression=(
                Key("fieldId").eq(field_id) & Key("weatherDate").gte(start)
            ),
            ScanIndexForward=True,
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.warning(f"Could not fetch cached weather for {field_id}: {e}")
        return []


def get_last_et_date(field_id: str) -> Optional[str]:
    """Return ISO date of the most recent ET record stored for the field."""
    try:
        resp = et_table.query(
            KeyConditionExpression=Key("fieldId").eq(field_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        return items[0].get("etDate") if items else None
    except Exception as e:
        logger.warning(f"Could not fetch last ET date for {field_id}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Derived metrics computation
# ─────────────────────────────────────────────────────────────────────────────

# GDD → corn growth stage look-up table (approximate)
_STAGE_TABLE = [
    (0,    "VE — Emergence"),
    (200,  "V3 — 3rd leaf"),
    (450,  "V6 — 6th leaf"),
    (750,  "V10 — 10th leaf"),
    (1000, "VT — Tassel"),
    (1135, "R1 — Silk"),
    (1400, "R2 — Blister"),
    (1700, "R3 — Milk"),
    (1925, "R4 — Dough"),
    (2190, "R5 — Dent"),
    (2700, "R6 — Physiological Maturity"),
]

def estimate_growth_stage(gdd_accumulated: float) -> str:
    """Map accumulated GDD to the closest corn growth stage."""
    stage = _STAGE_TABLE[0][1]
    for gdd_threshold, stage_name in _STAGE_TABLE:
        if gdd_accumulated >= gdd_threshold:
            stage = stage_name
        else:
            break
    return stage


def compute_health_score(
    ndvi_mean: Optional[float],
    ndmi_mean: Optional[float],
    water_stress: float,
    heat_stress_severity: str,
    days_since_obs: Optional[int],
) -> Tuple[int, str]:
    """
    Compute a 0–100 Health/Stature Score.

    Weights (tunable):
      60% vigor component  (NDVI)
      25% moisture component (NDMI adjusted by water stress)
      15% stress penalty (heat + confidence)

    Returns (score: int, confidence: str)
    """
    # ── Vigor ──────────────────────────────────────────────────────────────
    if ndvi_mean is not None:
        # Scale NDVI [0.1 … 0.9] → [0 … 100]
        vigor = max(0.0, min((ndvi_mean - 0.1) / 0.8, 1.0)) * 100
    else:
        vigor = 50.0   # neutral when no satellite data

    # ── Moisture ───────────────────────────────────────────────────────────
    if ndmi_mean is not None:
        moisture = max(0.0, min((ndmi_mean + 0.2) / 0.8, 1.0)) * 100
    else:
        moisture = 50.0

    # Apply water stress penalty to moisture component
    moisture = moisture * (1.0 - water_stress * 0.5)

    # ── Stress penalty ─────────────────────────────────────────────────────
    heat_penalty = {"none": 0, "medium": 5, "high": 15}.get(heat_stress_severity, 0)

    # ── Confidence decay ───────────────────────────────────────────────────
    if days_since_obs is None or days_since_obs > 12:
        confidence = "low"
        conf_penalty = 8
    elif days_since_obs > 5:
        confidence = "medium"
        conf_penalty = 4
    else:
        confidence = "high"
        conf_penalty = 0

    raw_score = (
        0.60 * vigor
        + 0.25 * moisture
        - heat_penalty
        - conf_penalty
    )
    score = int(max(0, min(100, round(raw_score))))
    return score, confidence


def compute_risk_indicators(
    health_score: int,
    ndvi_mean: Optional[float],
    ndvi_prev_mean: Optional[float],
    water_stress: float,
    heat_stress_days: int,
    days_since_obs: Optional[int],
) -> Dict[str, float]:
    """
    Compute failure and quality risk indicators (0–1).

    Labelled in UI as: "Risk indicator (model-based). Confirm with scouting."
    """
    failure_risk = 0.0

    # Low health score
    failure_risk += max(0, (60 - health_score) / 60) * 0.3

    # Sharp NDVI drop
    if ndvi_mean is not None and ndvi_prev_mean is not None:
        drop = ndvi_prev_mean - ndvi_mean
        failure_risk += max(0, drop / 0.3) * 0.3

    # Water stress
    failure_risk += water_stress * 0.25

    # Heat stress
    failure_risk += min(heat_stress_days / 5, 1.0) * 0.15

    # Satellite data stale
    if days_since_obs and days_since_obs > 12:
        failure_risk += 0.05

    quality_risk = water_stress * 0.4 + min(heat_stress_days / 5, 1.0) * 0.4 + (1 - health_score / 100) * 0.2

    return {
        "failureRisk": round(min(failure_risk, 1.0), 3),
        "qualityRisk": round(min(quality_risk, 1.0), 3),
    }


def estimate_harvest_window(maturity_forecast: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estimate the harvest date window from the projected physiological
    maturity (R6 / black layer) date.

    Corn dries down from ~30-35% kernel moisture at R6 to ~15.5% harvest-ready
    moisture over roughly 18-28 days under normal fall conditions, depending
    on starting moisture and weather (Iowa State Univ. Extension). This adds
    a fixed 18-28 day window to the projected R6 date — it does not model
    daily dry-down rate from actual weather, since that would require
    tracking kernel moisture directly.
    """
    predicted_r6 = maturity_forecast.get("predictedDate")
    if not predicted_r6:
        return {
            "maturityDate": None, "earliestDate": None,
            "estimatedDate": None, "latestDate": None,
            "note": "Maturity date unavailable",
        }

    try:
        r6_date = date.fromisoformat(predicted_r6)
    except Exception:
        return {
            "maturityDate": None, "earliestDate": None,
            "estimatedDate": None, "latestDate": None,
            "note": "Maturity date unavailable",
        }

    DRYDOWN_MIN_DAYS     = 18
    DRYDOWN_TYPICAL_DAYS = 23
    DRYDOWN_MAX_DAYS      = 28

    return {
        "maturityDate":  r6_date.isoformat(),
        "earliestDate":  (r6_date + timedelta(days=DRYDOWN_MIN_DAYS)).isoformat(),
        "estimatedDate": (r6_date + timedelta(days=DRYDOWN_TYPICAL_DAYS)).isoformat(),
        "latestDate":    (r6_date + timedelta(days=DRYDOWN_MAX_DAYS)).isoformat(),
        "note": ("Estimated from projected physiological maturity (R6) plus a "
                  "typical 18-28 day grain dry-down window."),
    }


# Corn growth stages where pollination/kernel-set is occurring — yield loss
# from water or heat stress during this window is disproportionately large
# relative to the same stress at other stages (agronomic consensus).
_YIELD_CRITICAL_STAGES = {"VT — Tassel", "R1 — Silk", "R2 — Blister"}


def estimate_yield_potential(
    health_score: int,
    water_stress: float,
    heat_stress_severity: str,
    estimated_stage: str,
) -> float:
    """
    Heuristic estimate of yield potential, as a percentage of the hybrid's
    genetic yield ceiling (100% = no meaningful stress detected).

    NOT a calibrated agronomic yield model. This is a transparent, explainable
    proxy built entirely from THIS RUN's snapshot of metrics — health score,
    water stress, heat stress, and current growth stage — so it reflects
    today's crop posture only, not a season-long projection. It is weighted
    more heavily when the crop's current stage falls in the
    pollination-sensitive window (VT-R2), where stress causes proportionally
    larger yield loss per agronomic literature.

    Deliberately NOT floored at an arbitrary "safe minimum" — the result is
    the real computed severity, so two fields with genuinely different health
    scores/stress levels will show genuinely different numbers instead of
    both collapsing to the same clamped value. Only bounded to the valid
    0-100% range (0 meaning severe, compounding stress detected today; not a
    literal guarantee of total crop failure).
    """
    stress_multiplier = 1.35 if estimated_stage in _YIELD_CRITICAL_STAGES else 1.0

    heat_penalty = {"none": 0.0, "medium": 6.0, "high": 14.0}.get(heat_stress_severity, 0.0)

    # health_score already blends NDVI vigor + moisture + heat/confidence penalties.
    water_penalty = water_stress * 20.0 * stress_multiplier
    heat_penalty_weighted = heat_penalty * stress_multiplier

    potential = float(health_score) - water_penalty - heat_penalty_weighted
    return round(max(0.0, min(100.0, potential)), 1)


def compute_all_metrics(
    field: Dict[str, Any],
    weather_result: Dict[str, Any],
    satellite_result: Dict[str, Any],
    et_result: Dict[str, Any],
    cached_weather: List[Dict[str, Any]],
    last_observation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Assemble all derived metrics from raw ingestion results.
    """
    import decimal
    def _f(v):
        """Safe float conversion — handles Decimal, None, and numeric strings."""
        if v is None:
            return None
        if isinstance(v, decimal.Decimal):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    planting_date_str = field.get("plantingDate", "")
    target_gdd = float(field.get("targetGDD") or (float(field.get("hybridRM", 105)) * 24))

    try:
        planting_date = datetime.fromisoformat(
            planting_date_str.replace("Z", "+00:00")
        ).date()
    except Exception:
        planting_date = datetime.utcnow().date() - timedelta(days=60)

    days_since_planting = (datetime.utcnow().date() - planting_date).days

    # ── GDD ────────────────────────────────────────────────────────────────
    # cached_weather (from DynamoDB) and weather_result["observed"] (freshly
    # fetched) usually overlap on the same calendar days — dedupe by date,
    # letting the fresh observation win, so accumulate_gdd() doesn't double-count.
    all_weather_records = _dedupe_weather_records(cached_weather, weather_result.get("observed", []))
    gdd_accumulated = accumulate_gdd(all_weather_records, planting_date)

    today_weather = (weather_result.get("observed") or [{}])[-1]
    gdd_daily     = today_weather.get("gddDaily", 0.0)

    # ── Growth stage ───────────────────────────────────────────────────────
    estimated_stage = estimate_growth_stage(gdd_accumulated)

    # ── Heat stress ────────────────────────────────────────────────────────
    heat_stress = heat_stress_flag(weather_result.get("forecast", []))

    # ── Maturity forecast ──────────────────────────────────────────────────
    maturity_forecast = predict_maturity_window(
        gdd_accumulated,
        target_gdd,
        weather_result.get("forecast", []),
    )

    # ── Satellite age ──────────────────────────────────────────────────────
    sat_date = satellite_result.get("observationDate")
    if sat_date:
        try:
            days_since_obs = (datetime.utcnow().date() - date.fromisoformat(sat_date)).days
        except Exception:
            days_since_obs = None
    else:
        days_since_obs = None

    # Fall back to previous observation age if no new satellite data
    if days_since_obs is None and last_observation:
        prev_date = last_observation.get("observationDate", "")[:10]
        try:
            days_since_obs = (datetime.utcnow().date() - date.fromisoformat(prev_date)).days
        except Exception:
            days_since_obs = None

    # ── Index means ────────────────────────────────────────────────────────
    indices   = satellite_result.get("indices", {})
    ndvi_mean = _f((indices.get("ndvi") or {}).get("mean"))
    ndmi_mean = _f((indices.get("ndmi") or {}).get("mean"))

    prev_ndvi_mean = None
    if last_observation:
        prev_ndvi_mean = _f(
            (last_observation.get("indices") or {})
            .get("ndvi", {})
            .get("mean")
        )

    # ── Health score ───────────────────────────────────────────────────────
    water_stress  = _f(et_result.get("waterStressScore")) or 0.0
    heat_severity = heat_stress.get("heatStressSeverity", "none")

    health_score, confidence = compute_health_score(
        ndvi_mean, ndmi_mean, water_stress, heat_severity, days_since_obs
    )

    # ── Risk indicators ────────────────────────────────────────────────────
    risks = compute_risk_indicators(
        health_score,
        ndvi_mean,
        prev_ndvi_mean,
        water_stress,
        heat_stress.get("heatStressDaysNext7", 0),
        days_since_obs,
    )

    # ── Harvest window + yield potential ────────────────────────────────────
    harvest_window  = estimate_harvest_window(maturity_forecast)
    yield_potential = estimate_yield_potential(
        health_score, water_stress, heat_severity, estimated_stage
    )

    return {
        "gddAccumulated":      round(float(gdd_accumulated), 1),
        "gddDaily":            round(float(gdd_daily), 2),
        "daysSincePlanting":   days_since_planting,
        "estimatedStage":      estimated_stage,
        "healthScore":         health_score,
        "healthScoreConfidence": confidence,
        "waterStressScore":    water_stress,
        "heatStress":          heat_stress,
        "maturityForecast":    maturity_forecast,
        "harvestWindow":       harvest_window,
        "yieldPotentialPct":   yield_potential,
        "daysSinceObservation": days_since_obs,
        "riskIndicators":      risks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_weather_records(field_id: str, records: List[Dict[str, Any]]) -> None:
    """Cache weather records in the weather table."""
    with weather_table.batch_writer() as batch:
        for rec in records:
            item = {"fieldId": field_id, **rec, "expiresAt": _ttl()}
            batch.put_item(Item=_to_dynamo(item))


def save_et_records(field_id: str, records: List[Dict[str, Any]]) -> None:
    """Cache ET records in the ET table."""
    with et_table.batch_writer() as batch:
        for rec in records:
            item = {"fieldId": field_id, **rec, "expiresAt": _ttl()}
            batch.put_item(Item=_to_dynamo(item))


def save_observation(field_id: str, satellite_result: Dict[str, Any]) -> None:
    """Persist a satellite observation to the Observations table."""
    if satellite_result.get("status") != "success":
        return
    item = {
        "fieldId":         field_id,
        "observationDate": satellite_result["observationDate"],
        **satellite_result,
        "expiresAt": _ttl(180),
    }
    observations_table.put_item(Item=_to_dynamo(item))


def save_daily_status(field_id: str, status: Dict[str, Any]) -> None:
    """Write the daily status record to DynamoDB."""
    daily_status_table.put_item(Item=_to_dynamo(status))


def get_or_generate_vision_analysis(
    field_id: str, recent_observations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Return the image trend analysis for the last N satellite captures, reusing
    the previously stored analysis when the newest capture date hasn't changed
    (satellite scenes refresh every few days, so re-invoking Bedrock vision on
    every daily batch run would be wasteful).
    """
    latest_date = recent_observations[0].get("observationDate") if recent_observations else None

    try:
        prev_status = get_latest_status(field_id)
    except Exception:
        prev_status = None

    prev_vision = (prev_status or {}).get("visionAnalysis") if prev_status else None
    if (
        prev_vision
        and latest_date
        and prev_vision.get("latestObservationDate") == latest_date
        and prev_vision.get("capturesAnalyzed") == len(recent_observations[:7])
    ):
        logger.info(f"[{field_id}] Reusing cached vision analysis (no new capture since {latest_date})")
        return prev_vision

    return generate_image_trend_analysis(recent_observations)


def update_field_last_observation(field_id: str, user_id: str, obs_date: str) -> None:
    """Update the lastObservationDate on the Fields record."""
    try:
        fields_table.update_item(
            Key={"fieldId": field_id, "userId": user_id},
            UpdateExpression="SET lastObservationDate = :d, updatedAt = :u",
            ExpressionAttributeValues={
                ":d": obs_date,
                ":u": datetime.utcnow().isoformat() + "Z",
            },
        )
    except Exception as e:
        logger.warning(f"Could not update field last observation: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# New-field satellite backfill
# ─────────────────────────────────────────────────────────────────────────────

def backfill_field_satellite_history(field: Dict[str, Any]) -> Dict[str, Any]:
    """
    For a newly-created field: fetch and process up to the last 7 available
    historical Sentinel-2 captures in one pass (instead of waiting ~7 daily
    batch runs for that much history to accumulate one observation at a
    time), persist each as an Observations record, then run the vision
    trend analysis across whatever was found.

    Safe to call on a field that already has observations — existing dates
    are simply overwritten with the same data (save_observation is an
    idempotent put_item keyed on fieldId+observationDate).

    Returns:
        {"capturesFound": int, "visionAnalysis": {...}}
    """
    field_id = field["fieldId"]
    logger.info(f"[{field_id}] Starting satellite history backfill")

    observations = backfill_satellite_observations(field, DATA_BUCKET, num_scenes=VISION_ANALYSIS_CAPTURES)

    for obs in observations:
        save_observation(field_id, obs)

    if observations:
        newest = observations[0]
        try:
            update_field_last_observation(
                field_id, field.get("userId", "unknown"), newest["observationDate"]
            )
        except Exception as e:
            logger.warning(f"[{field_id}] Could not update lastObservationDate after backfill: {e}")

    logger.info(f"[{field_id}] Backfill found {len(observations)} usable capture(s)")

    # Vision analysis expects newest-first — backfill_satellite_observations
    # already returns them in that order.
    vision_analysis = generate_image_trend_analysis(observations)
    logger.info(
        f"[{field_id}] Backfill vision analysis: captures={vision_analysis.get('capturesAnalyzed')} "
        f"trend={vision_analysis.get('overallTrend')}"
    )

    # Merge the backfill results into whatever DailyStatus already exists
    # (the onboarding Lambda seeds an initial status with weather/GDD but
    # satellite=None — this fills in the satellite + visionAnalysis pieces
    # without needing a full process_field() run, which would also refetch
    # weather/ET/AI-brief unnecessarily right after onboarding already did).
    existing_status = get_latest_status(field_id) or {
        "fieldId": field_id,
        "statusDate": datetime.utcnow().strftime("%Y-%m-%d") + "T00:00:00Z",
    }
    existing_status["satellite"]     = observations[0] if observations else existing_status.get("satellite")
    existing_status["visionAnalysis"] = vision_analysis
    existing_status["processedAt"]    = datetime.utcnow().isoformat() + "Z"
    save_daily_status(field_id, existing_status)

    return {"capturesFound": len(observations), "visionAnalysis": vision_analysis}


# ─────────────────────────────────────────────────────────────────────────────
# Per-field processing
# ─────────────────────────────────────────────────────────────────────────────

def process_field(
    field: Dict[str, Any],
    api_keys: Dict[str, str],
    batch_job_id: str,
) -> Dict[str, Any]:
    """
    Run the complete ingestion + analysis pipeline for one field.
    """
    field_id = field["fieldId"]

    # DynamoDB returns numeric types as Decimal; convert everything to float/int
    # before passing to external APIs or numpy operations
    field = _floatify(field)

    lat = float(field.get("centroidLat", 0))
    lon = float(field.get("centroidLon", 0))

    logger.info(f"[{field_id}] Starting pipeline lat={lat:.4f} lon={lon:.4f}")

    # ── 1. Weather ─────────────────────────────────────────────────────────
    # Open-Meteo free tier archives go back ~92 days; cap start date accordingly
    planting_iso_str = field.get("plantingDate", "")[:10]
    ninety_days_ago = (datetime.utcnow() - timedelta(days=88)).strftime("%Y-%m-%d")
    start_date = max(planting_iso_str, ninety_days_ago) if planting_iso_str else ninety_days_ago

    weather_result = fetch_weather(lat, lon, start_date=start_date)
    save_weather_records(field_id, weather_result.get("observed", []))
    logger.info(f"[{field_id}] Weather: {len(weather_result.get('observed', []))} observed days")

    # ── 2. Satellite ───────────────────────────────────────────────────────
    last_obs          = get_last_observation(field_id)
    last_clear_date   = last_obs.get("observationDate") if last_obs else None

    satellite_result  = ingest_satellite(field, DATA_BUCKET, last_clear_date)
    save_observation(field_id, satellite_result)

    if satellite_result.get("status") == "success":
        update_field_last_observation(
            field_id, field.get("userId", "unknown"), satellite_result["observationDate"]
        )
    logger.info(f"[{field_id}] Satellite: status={satellite_result.get('status')}")

    # ── 3. ET ──────────────────────────────────────────────────────────────
    last_et_date   = get_last_et_date(field_id)
    cached_weather = get_cached_weather(field_id, days=90)
    # DynamoDB returns Decimals; convert before passing to numpy/arithmetic
    cached_weather = _floatify(cached_weather)

    et_result = ingest_et(
        field,
        api_keys,
        weather_records=weather_result.get("observed", []),
        last_et_date=last_et_date,
    )
    save_et_records(field_id, et_result.get("etRecords", []))
    logger.info(f"[{field_id}] ET: deficit={et_result.get('cumulativeDeficit_mm')} mm source={et_result.get('source')}")

    # ── 4. Derived metrics ─────────────────────────────────────────────────
    metrics = compute_all_metrics(
        field, weather_result, satellite_result, et_result, cached_weather, last_obs
    )
    logger.info(f"[{field_id}] Metrics: health={metrics['healthScore']} stage={metrics['estimatedStage']}")

    # ── 5. AI Brief ────────────────────────────────────────────────────────
    ai_brief = generate_daily_brief(
        field        = field,
        satellite    = satellite_result,
        weather_observed = weather_result.get("observed", []),
        weather_forecast = weather_result.get("forecast", []),
        et_summary   = et_result,
        metrics      = metrics,
    )
    logger.info(f"[{field_id}] AI brief confidence={ai_brief.get('confidence')}")

    # ── 6. Image trend analysis (vision) ───────────────────────────────────
    recent_observations = get_recent_observations(field_id, VISION_ANALYSIS_CAPTURES)
    vision_analysis = get_or_generate_vision_analysis(field_id, recent_observations)
    logger.info(
        f"[{field_id}] Vision analysis: captures={vision_analysis.get('capturesAnalyzed')} "
        f"trend={vision_analysis.get('overallTrend')}"
    )

    # ── 7. Persist daily status ────────────────────────────────────────────
    today_str    = datetime.utcnow().strftime("%Y-%m-%d")
    daily_status = {
        "fieldId":      field_id,
        "statusDate":   today_str + "T00:00:00Z",
        "weather":      (weather_result.get("observed") or [{}])[-1],
        "forecast":     weather_result.get("forecast", [])[:7],
        "satellite":    satellite_result,
        "et":           {
            "cumulativeDeficit_mm": et_result.get("cumulativeDeficit_mm"),
            "waterStressScore":     et_result.get("waterStressScore"),
            "source":               et_result.get("source"),
            "latestET_mm":          (et_result.get("etRecords") or [{}])[-1].get("et_mm"),
        },
        "metrics":         metrics,
        "aiBrief":         ai_brief,
        "visionAnalysis":  vision_analysis,
        "batchJobId":      batch_job_id,
        "processedAt":     datetime.utcnow().isoformat() + "Z",
    }
    save_daily_status(field_id, daily_status)

    return {
        "fieldId":          field_id,
        "status":           "success",
        "healthScore":      metrics["healthScore"],
        "satelliteStatus":  satellite_result.get("status"),
        "etSource":         et_result.get("source"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lambda handler
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_status(field_id: str) -> Optional[Dict[str, Any]]:
    """Query DynamoDB for the most recent daily status for a field."""
    try:
        resp = daily_status_table.query(
            KeyConditionExpression=Key("fieldId").eq(field_id),
            ScanIndexForward=False,  # Most recent first
            Limit=1,
        )
        items = resp.get("Items", [])
        return _floatify(items[0]) if items else None
    except Exception as e:
        logger.error(f"Failed to query latest status for {field_id}: {e}")
        return None


def handler(event, context):
    """
    Entry point for both scheduled (EventBridge) and manual (API Gateway) invocations.

    API Gateway event shapes:
        GET /fields/{fieldId}/status/latest
        → event["httpMethod"] = "GET"
        → event["pathParameters"]["fieldId"] = "<id>"

        POST /fields/{fieldId}/run
        → event["httpMethod"] = "POST"
        → event["pathParameters"]["fieldId"] = "<id>"

    EventBridge event shape:
        { "batchType": "daily", "triggerType": "scheduled" }
    """
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }

    # ── Check if this is a GET request (fetch latest status) ─────────────────
    http_method = event.get("httpMethod")
    if http_method == "GET":
        field_id = (event.get("pathParameters") or {}).get("fieldId")
        if not field_id:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "Missing fieldId in path"}),
            }
        
        status = get_latest_status(field_id)
        if not status:
            return {
                "statusCode": 404,
                "headers": headers,
                "body": json.dumps({"error": f"No status found for field {field_id}"}),
            }
        
        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps(status, default=str),
        }

    # ── Async invocation: satellite history backfill for a newly-created field ──
    # Triggered by field_onboarding's handler via a fire-and-forget
    # lambda:InvokeFunction (InvocationType="Event") right after field
    # creation — not via API Gateway, so no HTTP response path here.
    if event.get("batchType") == "backfill":
        single_field_id = event.get("fieldId")
        if not single_field_id:
            logger.error("backfill invocation missing fieldId")
            return {"status": "error", "error": "Missing fieldId"}
        try:
            resp = fields_table.query(
                KeyConditionExpression=Key("fieldId").eq(single_field_id),
                Limit=1,
            )
            fields = resp.get("Items", [])
        except Exception as e:
            logger.error(f"Backfill: could not retrieve field {single_field_id}: {e}")
            fields = []

        if not fields:
            logger.error(f"Backfill: field {single_field_id} not found")
            return {"status": "error", "error": f"Field {single_field_id} not found"}

        try:
            result = backfill_field_satellite_history(_floatify(fields[0]))
            return {"status": "success", "fieldId": single_field_id, **result}
        except Exception as e:
            logger.error(f"Backfill failed for {single_field_id}: {e}", exc_info=True)
            return {"status": "failed", "fieldId": single_field_id, "error": str(e)}

    # ── POST request: trigger batch run ───────────────────────────────────────
    batch_job_id    = f"batch-{uuid.uuid4()}"
    trigger_type    = event.get("triggerType", "scheduled")
    single_field_id = (event.get("pathParameters") or {}).get("fieldId")

    logger.info(f"Batch job {batch_job_id} started — trigger={trigger_type} "
                f"single_field={single_field_id or 'all'}")

    # ── Retrieve API keys once for the entire batch run ────────────────────
    api_keys = get_api_keys()

    # ── Determine which fields to process ──────────────────────────────────
    if single_field_id:
        # Manual trigger for one field — fetch directly by ID
        try:
            resp = fields_table.query(
                KeyConditionExpression=Key("fieldId").eq(single_field_id),
                Limit=1,
            )
            fields = resp.get("Items", [])
        except Exception as e:
            logger.error(f"Could not retrieve field {single_field_id}: {e}")
            fields = []
    else:
        fields = get_active_fields()

    total_fields    = len(fields)
    processed_count = 0
    failed_count    = 0
    field_results   = []

    logger.info(f"Processing {total_fields} field(s)")

    for field in fields:
        try:
            result = process_field(_floatify(field), api_keys, batch_job_id)
            field_results.append(result)
            processed_count += 1
        except Exception as e:
            failed_count += 1
            fid = field.get("fieldId", "unknown")
            logger.error(f"Pipeline failed for field {fid}: {e}", exc_info=True)
            field_results.append({"fieldId": fid, "status": "failed", "error": str(e)})

    # ── Write batch log ────────────────────────────────────────────────────
    batch_log = _to_dynamo({
        "batchJobId":      batch_job_id,
        "startTime":       datetime.utcnow().isoformat() + "Z",
        "triggerType":     trigger_type,
        "totalFields":     total_fields,
        "fieldsProcessed": processed_count,
        "fieldsFailed":    failed_count,
        "fieldResults":    field_results,
        "status":          "completed" if failed_count == 0 else "partial",
        "expiresAt":       _ttl(90),
    })
    try:
        batch_log_table.put_item(Item=batch_log)
    except Exception as e:
        logger.error(f"Failed to write batch log: {e}")

    logger.info(f"Batch {batch_job_id} complete: {processed_count}/{total_fields} ok, "
                f"{failed_count} failed")

    response_body = {
        "batchJobId":      batch_job_id,
        "fieldsProcessed": processed_count,
        "fieldsFailed":    failed_count,
        "totalFields":     total_fields,
        "message":         "Batch pipeline completed",
    }

    return {
        "statusCode": 200 if failed_count == 0 else 207,
        "headers": {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(response_body),
    }
