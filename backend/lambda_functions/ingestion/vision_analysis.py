"""
Satellite Image Trend Analysis Module

Uses Amazon Bedrock (Claude Haiku 4.5 — vision) to analyze the last 7 satellite
capture dates for a field (NDVI/NDMI/NDRE preview PNGs already produced by
satellite.py) and produce a narrative trend summary + suggestions.

Model: us.anthropic.claude-haiku-4-5-20251001-v1:0 — the same model used for the
daily text brief (bedrock_brief.py). It's Anthropic's cheapest current-generation
model and is vision-capable, so no additional model or IAM permission is needed.

Design notes:
  - Bedrock caps Claude Messages API requests at 20 images. 7 captures x 3 indices
    (NDVI/NDMI/NDRE) = 21 images, just over that limit. To stay under the cap (and
    reduce cost/latency), the 3 index PNGs for a given capture date are composited
    side-by-side into a single labeled JPEG, so each capture = 1 image (<=7 total).
  - Callers should skip invoking Bedrock again if the most recent observation date
    hasn't changed since the last stored analysis (satellite scenes refresh every
    few days, not daily) — see daily_batch/handler.py for the caching check.
"""

import base64
import io
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "us-west-2"))
MODEL_ID       = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_TOKENS     = 2048
MAX_CAPTURES   = 7
PANEL_WIDTH    = 300   # px per index panel inside the composite image
JPEG_QUALITY   = 80

bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
s3      = boto3.client("s3")

_INDEX_LABELS = {"ndvi": "NDVI", "ndmi": "NDMI", "ndre": "NDRE"}


# ── S3 helpers ────────────────────────────────────────────────────────────────

def _parse_s3_uri(uri: str) -> Optional[Tuple[str, str]]:
    """Parse s3://bucket/key into (bucket, key). Returns None if malformed."""
    if not uri or not uri.startswith("s3://"):
        return None
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key    = parsed.path.lstrip("/")
    if not bucket or not key:
        return None
    return bucket, key


def _download_preview(uri: str) -> Optional[Image.Image]:
    """Download a preview PNG from S3 and return a PIL Image, or None on failure."""
    parsed = _parse_s3_uri(uri)
    if not parsed:
        return None
    bucket, key = parsed
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return Image.open(io.BytesIO(resp["Body"].read())).convert("RGB")
    except Exception as e:
        logger.warning(f"Could not download preview {uri}: {e}")
        return None


# ── Composite builder ─────────────────────────────────────────────────────────

def _make_panel(img: Optional[Image.Image], label: str) -> Image.Image:
    """Resize one index image to PANEL_WIDTH and stamp a caption bar on top."""
    caption_h = 22
    if img is not None:
        w, h = img.size
        scale = PANEL_WIDTH / w
        img = img.resize((PANEL_WIDTH, max(1, int(h * scale))))
    else:
        img = Image.new("RGB", (PANEL_WIDTH, PANEL_WIDTH), (60, 60, 60))

    panel = Image.new("RGB", (img.width, img.height + caption_h), (20, 20, 20))
    panel.paste(img, (0, caption_h))
    draw = ImageDraw.Draw(panel)
    draw.text((4, 4), label, fill=(255, 255, 255))
    return panel


def build_composite(preview_urls: Dict[str, str], observation_date: str) -> Optional[bytes]:
    """
    Build one side-by-side JPEG (NDVI | NDMI | NDRE) for a single capture date.
    Returns JPEG bytes, or None if no preview images were available at all.
    """
    panels = []
    any_found = False
    for idx in ["ndvi", "ndmi", "ndre"]:
        uri = (preview_urls or {}).get(idx)
        img = _download_preview(uri) if uri else None
        if img is not None:
            any_found = True
        panels.append(_make_panel(img, f"{_INDEX_LABELS[idx]} \u2014 {observation_date}"))

    if not any_found:
        return None

    total_w   = sum(p.width for p in panels)
    max_h     = max(p.height for p in panels)
    composite = Image.new("RGB", (total_w, max_h), (20, 20, 20))
    x = 0
    for p in panels:
        composite.paste(p, (x, 0))
        x += p.width

    buf = io.BytesIO()
    composite.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


# ── Bedrock invocation ────────────────────────────────────────────────────────

def _build_content_blocks(prepared: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the Anthropic multi-image content array: one text label + one composite
    image per capture (oldest -> newest), followed by grounding stats + instructions.
    """
    content: List[Dict[str, Any]] = []

    for i, obs in enumerate(prepared):
        date    = obs.get("observationDate", "unknown")
        indices = obs.get("indices", {}) or {}
        ndvi    = (indices.get("ndvi") or {}).get("mean")
        ndmi    = (indices.get("ndmi") or {}).get("mean")
        ndre    = (indices.get("ndre") or {}).get("mean")
        quality = obs.get("quality", "unknown")
        cloud   = obs.get("sceneCloudPct")

        label = (
            f"Capture {i + 1} of {len(prepared)} \u2014 date: {date} \u2014 quality: {quality} \u2014 "
            f"cloud: {cloud}% \u2014 NDVI mean: {ndvi} \u2014 NDMI mean: {ndmi} \u2014 NDRE mean: {ndre}. "
            f"Image layout left\u2192right: NDVI, NDMI, NDRE (gray = cloud/invalid masked pixels)."
        )
        content.append({"type": "text", "text": label})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": obs["_composite_b64"],
            },
        })

    instructions = f"""You are an expert agronomist reviewing a {len(prepared)}-capture time series of Sentinel-2
vegetation index maps (NDVI, NDMI, NDRE) for one corn field, shown above in chronological order
(oldest first, most recent last). Each composite image shows NDVI | NDMI | NDRE side by side.
Color scale for all three: red/orange = low/stressed, yellow = moderate, green = high/healthy.
Gray = cloud or invalid pixels masked out (ignore gray areas).

TASK:
1. Describe what is visually happening across the sequence - canopy development, greening,
   browning, moisture changes, any emerging bare/stressed patches, cloud interference.
2. Identify the overall trend: improving, declining, stable, or mixed.
3. Call out any specific visual changes between consecutive captures worth flagging
   (e.g. a patch that appeared, a moisture drop, uneven canopy development).
4. Give 2-4 concrete, actionable suggestions for the farmer based on what you see.
5. State your confidence - lower confidence if many captures are cloudy/gray or sparse.

CRITICAL: Return ONLY valid JSON, double-quoted strings, no markdown, no trailing commas,
concise strings (<150 chars each).

Return ONLY this JSON:
{{
  "overallTrend": "improving" | "declining" | "stable" | "mixed",
  "summary": "<3-4 sentence narrative of what's happening across all captures>",
  "perCaptureNotes": [
    {{"date": "<date>", "observation": "<1 sentence: what changed vs previous capture>"}}
  ],
  "keyChanges": ["<specific visual change 1>", "<specific visual change 2>"],
  "suggestions": ["<actionable suggestion 1>", "<actionable suggestion 2>"],
  "confidence": "high" | "medium" | "low",
  "confidenceReason": "<1 sentence>"
}}
"""
    content.append({"type": "text", "text": instructions})
    return content


def _invoke_vision(prepared: List[Dict[str, Any]]) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "user", "content": _build_content_blocks(prepared)}
        ],
    }
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    if "content" in result and isinstance(result["content"], list):
        return result["content"][0].get("text", "")
    return str(result)


def _parse_response(raw_text: str) -> Dict[str, Any]:
    """Extract JSON from Claude's response, tolerating markdown fences / trailing commas."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.strip().startswith("```"))

    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in vision response")

    json_str = text[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        import re
        fixed = re.sub(r",(\s*[}\]])", r"\1", json_str)
        return json.loads(fixed)


# ── Fallback ──────────────────────────────────────────────────────────────────

def _fallback_analysis(reason: str, num_captures: int) -> Dict[str, Any]:
    return {
        "overallTrend": "unknown",
        "summary": (
            "Image trend analysis is temporarily unavailable. "
            "Review the satellite gallery manually to compare recent captures."
        ),
        "perCaptureNotes": [],
        "keyChanges": [],
        "suggestions": [
            "Manually compare NDVI/NDMI/NDRE thumbnails in the satellite gallery for trend changes.",
        ],
        "confidence": "low",
        "confidenceReason": f"Vision analysis failed: {reason or 'unknown error'}",
        "capturesAnalyzed": num_captures,
        "model": None,
        "generatedAt": datetime.utcnow().isoformat() + "Z",
    }


# ── Main entry ────────────────────────────────────────────────────────────────

def generate_image_trend_analysis(observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze up to the last 7 satellite captures (NDVI/NDMI/NDRE previews) for a
    field using Claude Haiku 4.5 vision, and return a structured trend summary.

    Args:
        observations: Observations-table records, MOST RECENT FIRST (as returned
                       by a DynamoDB Query with ScanIndexForward=False, Limit=7).
                       If fewer than 7 exist, pass all of them - this function
                       uses whatever it's given, up to MAX_CAPTURES.

    Returns:
        {
            overallTrend, summary, perCaptureNotes, keyChanges, suggestions,
            confidence, confidenceReason, capturesAnalyzed, latestObservationDate,
            model, generatedAt
        }
    """
    usable = [o for o in observations if o.get("previewUrls")][:MAX_CAPTURES]

    if not usable:
        return _fallback_analysis("No satellite captures with preview images available", 0)

    latest_date = usable[0].get("observationDate")

    # Build composites oldest -> newest so the model sees temporal progression in order
    chronological = list(reversed(usable))

    prepared = []
    for obs in chronological:
        composite = build_composite(obs.get("previewUrls", {}), obs.get("observationDate", "unknown"))
        if composite is None:
            continue
        obs_copy = dict(obs)
        obs_copy["_composite_b64"] = base64.b64encode(composite).decode("utf-8")
        prepared.append(obs_copy)

    if not prepared:
        fallback = _fallback_analysis("Could not download any preview images from S3", len(usable))
        fallback["latestObservationDate"] = latest_date
        return fallback

    try:
        logger.info(f"Invoking vision model {MODEL_ID} on {len(prepared)} capture(s)")
        raw_text = _invoke_vision(prepared)
        analysis = _parse_response(raw_text)

        required = {"overallTrend", "summary", "confidence"}
        if not required.issubset(analysis.keys()):
            raise ValueError("Missing required keys in vision analysis response")

        analysis["capturesAnalyzed"]      = len(prepared)
        analysis["latestObservationDate"] = latest_date
        analysis["model"]                 = MODEL_ID
        analysis["generatedAt"]           = datetime.utcnow().isoformat() + "Z"
        logger.info("Vision trend analysis generated successfully")
        return analysis

    except ClientError as e:
        code = e.response["Error"]["Code"]
        logger.warning(f"Bedrock vision ClientError: {code} \u2014 {e}")
        fallback = _fallback_analysis(str(e), len(prepared))
        fallback["latestObservationDate"] = latest_date
        return fallback
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse vision response: {e}")
        fallback = _fallback_analysis(str(e), len(prepared))
        fallback["latestObservationDate"] = latest_date
        return fallback
    except Exception as e:
        logger.error(f"Unexpected vision analysis error: {e}")
        fallback = _fallback_analysis(str(e), len(prepared))
        fallback["latestObservationDate"] = latest_date
        return fallback
