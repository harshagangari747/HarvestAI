"""
Bedrock AI Brief Generation Module

Uses Amazon Bedrock (Claude) to transform computed field metrics into:
  - daily_summary (narrative string)
  - top_risks     (list of strings)
  - recommended_actions (list of strings)
  - scouting_checklist  (list of strings)
  - confidence + confidence_reason

Model: us.anthropic.claude-haiku-4-5-20251001-v1:0 (US inference profile)
No alternate Bedrock model is used; generation falls back to the deterministic local brief if Haiku fails.
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

BEDROCK_REGION   = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-west-2"))
# Claude Haiku 4.5 requires a geo or global inference profile on bedrock-runtime.
PRIMARY_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_TOKENS       = 2048

bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(
    field: Dict[str, Any],
    satellite: Dict[str, Any],
    weather_today: Dict[str, Any],
    weather_forecast: list,
    et_summary: Dict[str, Any],
    metrics: Dict[str, Any],
) -> str:
    """
    Assemble a comprehensive prompt for crop posture & health analysis.

    Includes:
    - Current crop stage & health metrics
    - Health diagnosis (why low if applicable)
    - Next 48h weather & water outlook
    - Soil test context
    - Fertilizer recommendations
    """
    sat_date    = satellite.get("observationDate", "unknown")
    sat_quality = satellite.get("quality", "unknown")
    ndvi        = satellite.get("indices", {}).get("ndvi", {})
    ndmi        = satellite.get("indices", {}).get("ndmi", {})
    ndre        = satellite.get("indices", {}).get("ndre", {})

    days_since_obs = _days_since(sat_date)
    confidence     = _derive_confidence(days_since_obs, sat_quality)

    # Next 2 days (48h) forecast — rainfall, sunlight (via radiation), water balance
    fc2 = weather_forecast[:2]
    precip_48h = round(sum(r.get("precipitation_mm", 0) for r in fc2), 1)
    radiation_48h = round(sum(r.get("radiation_mj", 0) for r in fc2), 1)
    tmax_48h = [r.get("tmax_f", 0) for r in fc2]
    
    # Next 7 days summary for longer-term context
    fc7 = weather_forecast[:7]
    avg_tmax_7d = round(sum(r.get("tmax_f", 0) for r in fc7) / max(len(fc7), 1), 1)
    total_precip_7d = round(sum(r.get("precipitation_mm", 0) for r in fc7), 1)
    heat_days_7d = sum(1 for r in fc7 if r.get("tmax_f", 0) > 95)

    soil_test = field.get("soilTest", {})
    
    # Current health & stress
    health_score = metrics.get("healthScore")
    water_stress = metrics.get("waterStressScore")
    heat_stress = metrics.get("heatStress", {})
    stage = metrics.get("estimatedStage", "unknown")
    gdd_acc = metrics.get("gddAccumulated", 0)
    days_to_mat = metrics.get("maturityForecast", {}).get("daysToMaturity", 0)
    
    # Determine if health is concerning
    health_status = "excellent" if health_score and health_score >= 80 else \
                    "good" if health_score and health_score >= 60 else \
                    "fair" if health_score and health_score >= 40 else \
                    "poor" if health_score else "unknown"

    context = {
        "field": {
            "plantingDate":      field.get("plantingDate", "unknown")[:10],
            "hybridRM":          field.get("hybridRM"),
            "irrigationType":    field.get("irrigationType", "rainfed"),
            "areaAcres":         field.get("areaAcres"),
        },
        "soilProfile": {
            "texture":           field.get("soilContext", {}).get("dominantTexture", "unknown"),
            "drainageClass":     field.get("soilContext", {}).get("drainageClass", "unknown"),
            "pH":                soil_test.get("pH"),
            "organicMatter_%":   soil_test.get("organicMatter"),
            "phosphorus_ppm":    soil_test.get("phosphorus"),
            "potassium_ppm":     soil_test.get("potassium"),
        },
        "cropPosture": {
            "currentStage":          stage,
            "gddAccumulated":        gdd_acc,
            "daysSincePlanting":     metrics.get("daysSincePlanting"),
            "daysToMaturity":        days_to_mat,
            "healthScore_0_100":     health_score,
            "healthStatus":          health_status,
            "waterStressScore_0_1":  water_stress,
            "heatStressSeverity":    heat_stress.get("heatStressSeverity", "none"),
            "heatStressFlag":        heat_stress.get("stressed", False),
        },
        "satellite": {
            "lastObservationDate":   sat_date,
            "daysSinceObservation":  days_since_obs,
            "quality":               sat_quality,
            "ndvi_mean":             ndvi.get("mean"),
            "ndvi_p10":              ndvi.get("p10"),
            "ndvi_p90":              ndvi.get("p90"),
            "ndmi_mean":             ndmi.get("mean"),
            "ndre_mean":             ndre.get("mean"),
        },
        "todayWeather": {
            "tmin_f":                weather_today.get("tmin_f"),
            "tmax_f":                weather_today.get("tmax_f"),
            "precipitation_mm":      weather_today.get("precipitation_mm"),
            "radiation_mj_m2":       weather_today.get("radiation_mj"),
            "et0_mm":                weather_today.get("et0_mm"),
        },
        "next48hOutlook": {
            "totalRainfall_mm":      precip_48h,
            "totalSolarRadiation_mj": radiation_48h,
            "tempRange_f":           [min(tmax_48h) if tmax_48h else None, max(tmax_48h) if tmax_48h else None],
        },
        "next7daysOutlook": {
            "avgMaxTemp_f":          avg_tmax_7d,
            "totalRainfall_mm":      total_precip_7d,
            "heatStressDays":        heat_days_7d,
        },
        "waterBalance": {
            "cumulativeDeficit_mm":  et_summary.get("cumulativeDeficit_mm"),
            "waterStressScore_0_1":  et_summary.get("waterStressScore"),
            "etEstimate_mm":         et_summary.get("etEstimate_mm"),
            "etSource":              et_summary.get("source", "model"),
        },
    }

    prompt = f"""You are an expert agronomist generating a comprehensive daily field brief for a corn farmer.

Below is the detailed field status in JSON format:
<field_context>
{json.dumps(context, indent=2)}
</field_context>

TASK: Analyze the current crop posture, diagnose health issues (if any), and provide actionable recommendations considering:
1. Crop stage, GDD accumulation, and days to maturity
2. Health score & stress indicators (water, heat)
3. Satellite vegetation indices (NDVI trend)
4. Next 48h weather (rainfall, sunlight) and 7-day outlook
5. Water balance (deficit, stress score) and irrigation outlook
6. Soil test results (if available)
7. Fertilizer needs based on stage & stress
8. Observable scouting priorities

INSTRUCTIONS:
- ALL recommendations must be specific, actionable, and tied to actual field data.
- Health diagnosis: Explain clearly WHY health is low (e.g., "water deficit + high temp stress" or "early stress from cool/wet start").
- Next 48h actions: Prioritize based on rainfall & sunlight forecast.
- Fertilizer suggestions: Include NPK guidance ONLY if soil test is present; otherwise recommend "consult agronomist for soil-specific rates".
- Scouting items: Must be observable in-field signs (leaf color, canopy, pest damage, etc.).
- Confidence: high = satellite < 5 days + good data; medium = 5-12 days; low = > 12 days or issues.

CRITICAL: Return ONLY valid JSON. Every string value must use double quotes. Every list/object must have commas between elements. Do not add trailing commas. Ensure all brackets and braces are properly closed. Keep all text values concise (< 150 characters per string).

Return ONLY this valid JSON (no markdown, no extra text):
{{
  "cropPostureAnalysis": {{
    "currentStage": "<e.g. V6, VT, R2>",
    "maturityProgress": "<e.g. on track, slightly ahead, behind>",
    "canopyCondition": "<visual/biomass assessment from satellite & metrics>",
    "stressIndicators": ["<stress type 1>", "<stress type 2>"]
  }},
  "healthDiagnosis": {{
    "overallHealthRating": "<excellent | good | fair | poor>",
    "primaryConcerns": ["<concern 1>", "<concern 2>"],
    "rootCauses": ["<cause 1: e.g. water deficit>", "<cause 2: e.g. N deficiency>"],
    "timeToImpact": "<days if condition persists>"
  }},
  "next48hForecast": {{
    "rainfall_mm": <value>,
    "sunlightExpectation": "<abundant | moderate | limited>",
    "waterSupplyOutlook": "<adequate | marginal | deficit>",
    "actionsDuringNextTwoDays": ["<action 1>", "<action 2>"]
  }},
  "interventions": {{
    "fertiliserRecommendations": {{
      "timing": "<apply now | wait 3-5 days | apply after rain>",
      "npkGuidance": "<e.g. '50 lbs N/ac split application' or 'consult agronomist for soil-specific rates'>",
      "micronutrients": "<if relevant, e.g. 'Zn if stress visible'>",
      "rationale": "<why these nutrients given crop stage & stress>"
    }},
    "irrigationAdvisory": "<if rainfed: expected shortfall; if irrigated: timing & amount; if adequate rainfall expected: hold off>",
    "pestDiseasePrevention": ["<risk 1>", "<risk 2>"]
  }},
  "scoutingChecklist": [
    "<observable 1: e.g. leaf color, edge yellowing>",
    "<observable 2: e.g. canopy spread, plant height vs stage>",
    "<observable 3: e.g. pest/disease damage, lodging>",
    "<observable 4: e.g. soil moisture, compaction>"
  ],
  "confidence": "high" | "medium" | "low",
  "confidenceReason": "<1 sentence: e.g. 'High: satellite < 3 days old, clear sky, soil test available'>",
  "summary": "<2-3 sentence actionable narrative for farmer>"
}}

Current date: {datetime.utcnow().strftime("%Y-%m-%d")}
Satellite age: {days_since_obs} days (confidence baseline: {confidence})
"""
    return prompt


# ── Bedrock invocation ────────────────────────────────────────────────────────

def _invoke_claude(prompt: str, model_id: str) -> str:
    """Send prompt to Bedrock (Anthropic Claude) and return raw text."""
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }
    
    response = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    
    # Claude response format
    if "content" in result and isinstance(result["content"], list):
        return result["content"][0].get("text", "")
    
    return str(result)


def _parse_brief(raw_text: str) -> Dict[str, Any]:
    """
    Extract JSON from Claude's response.
    Handles cases where Claude wraps JSON in markdown code fences or adds trailing commas.
    """
    text = raw_text.strip()

    # Strip markdown code fence if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    # Find first { and last }
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in Bedrock response")

    json_str = text[start:end]
    
    # Try parsing as-is first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Try removing trailing commas before closing brackets/braces
        import re
        fixed = re.sub(r',(\s*[}\]])', r'\1', json_str)
        return json.loads(fixed)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_since(date_str: str) -> Optional[int]:
    """Return integer days since an ISO date string."""
    try:
        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.utcnow() - d.replace(tzinfo=None)).days
    except Exception:
        return None


def _derive_confidence(days_since: Optional[int], quality: str) -> str:
    if days_since is None:
        return "low"
    if days_since <= 5 and quality == "high":
        return "high"
    if days_since <= 12 or quality == "medium":
        return "medium"
    return "low"


def _fallback_brief(reason: str) -> Dict[str, Any]:
    """Return a fallback brief with structured crop analysis."""
    return {
        "cropPostureAnalysis": {
            "currentStage": "Unknown — check satellite data",
            "maturityProgress": "Unable to assess",
            "canopyCondition": "Review manually from satellite preview",
            "stressIndicators": []
        },
        "healthDiagnosis": {
            "overallHealthRating": "unknown",
            "primaryConcerns": ["AI service temporarily unavailable"],
            "rootCauses": [reason or "Bedrock API access issue — check IAM policy and model availability"],
            "timeToImpact": "Monitor manually in next 24h"
        },
        "next48hForecast": {
            "rainfall_mm": None,
            "sunlightExpectation": "Check weather forecast manually",
            "waterSupplyOutlook": "Check ET deficit in Water Balance card",
            "actionsDuringNextTwoDays": ["Review satellite indices for trends", "Monitor water stress score"]
        },
        "interventions": {
            "fertiliserRecommendations": {
                "timing": "Consult agronomist with current metrics",
                "npkGuidance": "Use soil test + growth stage to guide rates",
                "micronutrients": "Assess visually for deficiency symptoms",
                "rationale": "AI analysis temporarily unavailable"
            },
            "irrigationAdvisory": "Check water balance and ET forecast to plan next irrigation",
            "pestDiseasePrevention": ["Scout for pest pressure", "Monitor for foliar diseases"]
        },
        "scoutingChecklist": [
            "Inspect canopy color — look for yellowing or purple tints",
            "Check leaf size and plant height vs expected for stage",
            "Look for pest damage (spider mites, armyworms, etc.)",
            "Check soil moisture at root depth"
        ],
        "confidence": "low",
        "confidence_reason": f"AI generation failed: {reason or 'Bedrock service unavailable'}",
        "summary": "AI analysis is temporarily unavailable. Use the metrics above and satellite preview to assess crop health manually. Scout the field for visual stress indicators."
    }


# ── Main entry ────────────────────────────────────────────────────────────────

def generate_daily_brief(
    field: Dict[str, Any],
    satellite: Dict[str, Any],
    weather_observed: list,
    weather_forecast: list,
    et_summary: Dict[str, Any],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate a daily AI brief for a field using Amazon Bedrock.

    Args:
        field:            DynamoDB field record
        satellite:        Satellite observation dict (from satellite.py)
        weather_observed: Observed weather list (from weather.py)
        weather_forecast: Forecast weather list (from weather.py)
        et_summary:       ET + water balance dict (from et.py)
        metrics:          Computed metrics dict (from daily_batch)

    Returns:
        {
            summary, top_risks, recommended_actions,
            scouting_checklist, confidence, confidence_reason,
            generatedAt
        }
    """
    # Today's observed weather (most recent record)
    weather_today = weather_observed[-1] if weather_observed else {}

    prompt = build_prompt(
        field, satellite, weather_today, weather_forecast, et_summary, metrics
    )

    # Claude Haiku only. If it fails, use the deterministic local brief; never switch models.
    for model_id in [PRIMARY_MODEL_ID]:
        try:
            logger.info(f"Invoking Bedrock model: {model_id}")
            raw_text = _invoke_claude(prompt, model_id)
            brief    = _parse_brief(raw_text)

            # Validate required keys
            # Validate required keys — both legacy & new format supported
            new_schema_keys = {"cropPostureAnalysis", "healthDiagnosis", "next48hForecast",
                               "interventions", "scoutingChecklist", "confidence",
                               "confidenceReason", "summary"}
            legacy_keys = {"summary", "top_risks", "recommended_actions",
                          "scouting_checklist", "confidence", "confidence_reason"}
            
            has_new_schema = new_schema_keys.issubset(brief.keys())
            has_legacy_schema = legacy_keys.issubset(brief.keys())
            
            if not (has_new_schema or has_legacy_schema):
                raise ValueError(f"Missing required keys in brief")

            brief["generatedAt"] = datetime.utcnow().isoformat() + "Z"
            brief["model"]       = model_id
            logger.info("Bedrock brief generated successfully")
            return brief

        except ClientError as e:
            code = e.response["Error"]["Code"]
            logger.warning(f"Bedrock ClientError ({model_id}): {code} — {e}")
            return _fallback_brief(str(e))

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse Bedrock response: {e}")
            logger.error(f"Raw response text (full): {raw_text}")
            return _fallback_brief(str(e))

        except Exception as e:
            logger.error(f"Unexpected Bedrock error: {e}")
            return _fallback_brief(str(e))

    # The single Haiku attempt failed; return structured crop analysis instead of an empty brief.
    return _fallback_brief(
        f"Claude Haiku is unavailable in {BEDROCK_REGION}. AI analysis will resume when Haiku access is available."
    )
