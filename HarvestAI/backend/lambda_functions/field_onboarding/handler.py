"""
Field Onboarding Lambda Handler

POST /fields — creates a field and immediately seeds an initial DailyStatus
with today's weather so the dashboard has something to show right away.

Also performs:
  - Random name generation if fieldName not provided
  - Reverse geocoding via Nominatim (OSM, no key)
  - Static boundary map PNG generation → S3
"""

import io
import json
import math
import random
import uuid
import os
import logging
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Dict, Any, Tuple, List

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb      = boto3.resource('dynamodb')
s3_client     = boto3.client('s3')
lambda_client = boto3.client('lambda')

fields_table       = dynamodb.Table(os.environ.get('FIELDS_TABLE',       'harvestai-fields-dev'))
daily_status_table = dynamodb.Table(os.environ.get('DAILY_STATUS_TABLE', 'harvestai-dailystatus-dev'))
DATA_BUCKET        = os.environ.get('DATA_BUCKET', 'harvestai-data-dev-777967551979')
DAILY_BATCH_FUNCTION = os.environ.get('DAILY_BATCH_FUNCTION', 'harvestai-daily-batch-dev')

C_TO_F = lambda c: c * 9 / 5 + 32
GDD_BASE, GDD_CAP = 50.0, 86.0

# ── Random name generator ─────────────────────────────────────────────────────
_ADJECTIVES = ['Sunrise', 'Golden', 'Prairie', 'Valley', 'Rolling', 'Green',
  'Harvest', 'Meadow', 'Crystal', 'Silver', 'Blue Ridge', 'Oak', 'Maple', 'Cedar',
  'Willow', 'Elm', 'Broad', 'Deep', 'Clear', 'Misty']
_NOUNS = ['Acres', 'Fields', 'Farm', 'Homestead', 'Ridge', 'Hollow',
  'Creek', 'Run', 'Bend', 'Flats', 'Knoll', 'Plain', 'Grove', 'Crossing', 'Bottom']

def random_field_name() -> str:
    return f"{random.choice(_ADJECTIVES)} {random.choice(_NOUNS)}"


# ── Geometry helpers ──────────────────────────────────────────────────────────

def compute_centroid(geometry: Dict[str, Any]) -> Tuple[float, float]:
    coords = geometry.get('coordinates', [[]])[0]
    if not coords:
        return 0.0, 0.0
    return (
        sum(c[1] for c in coords) / len(coords),
        sum(c[0] for c in coords) / len(coords),
    )


def compute_area_acres(geometry: Dict[str, Any]) -> float:
    coords = geometry.get('coordinates', [[]])[0]
    if len(coords) < 3:
        return 0.0
    lat0 = sum(c[1] for c in coords) / len(coords)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    pts = [(c[0] * m_per_deg_lon, c[1] * m_per_deg_lat) for c in coords]
    n = len(pts)
    area_m2 = abs(sum(
        pts[i][0] * pts[(i+1)%n][1] - pts[(i+1)%n][0] * pts[i][1]
        for i in range(n)
    )) / 2.0
    return round(area_m2 / 4_046.86, 2)


# ── Validation ────────────────────────────────────────────────────────────────

def validate_input(body: Dict[str, Any]) -> Tuple[bool, str]:
    for field in ['geometry', 'plantingDate', 'hybridRM', 'irrigationType']:
        if field not in body:
            return False, f"Missing required field: {field}"
    if body['geometry'].get('type') != 'Polygon':
        return False, "geometry must be a GeoJSON Polygon"
    try:
        datetime.fromisoformat(body['plantingDate'].replace('Z', '+00:00'))
    except ValueError:
        return False, "plantingDate must be ISO 8601"
    return True, ""


# ── Reverse geocoding (Nominatim / OSM, no API key) ──────────────────────────

def reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """
    Returns a location dict with city, state, country, displayName.
    Falls back gracefully on any error.
    """
    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={'lat': lat, 'lon': lon, 'format': 'jsonv2'},
            headers={'User-Agent': 'HarvestAI/1.0 (farm-monitoring-app)'},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get('address', {})

        city    = addr.get('city') or addr.get('town') or addr.get('village') or addr.get('hamlet') or ''
        county  = addr.get('county', '')
        state   = addr.get('state', '')
        country = addr.get('country', '')

        parts = [p for p in [city, state, country] if p]
        display = ', '.join(parts) if parts else data.get('display_name', '')[:80]

        return {
            'city':        city,
            'county':      county,
            'state':       state,
            'country':     country,
            'displayName': display,
        }
    except Exception as e:
        logger.warning(f"Reverse geocode failed: {e}")
        return {'displayName': f"{round(lat,4)}, {round(lon,4)}", 'city': '', 'state': '', 'country': ''}


# ── Static boundary map (Esri World Imagery satellite tiles via staticmap) ────
#
# Uses the same Esri World Imagery basemap as the field-boundary drawing tool
# in FieldSetup.jsx, so the "Field Overview" card actually shows an aerial/
# satellite photo of the field instead of a plain OSM road/schematic map.
# Free, no API key required.

def generate_boundary_map(geometry: Dict[str, Any], field_id: str) -> str:
    """
    Render the field polygon over an Esri World Imagery satellite tile
    background using the staticmap Python library (pure-Python, no external
    service API key).

    Returns S3 URI of the uploaded PNG, or '' on failure.
    """
    try:
        from staticmap import StaticMap, Polygon

        coords = geometry.get('coordinates', [[]])[0]   # [[lon, lat], ...]
        if len(coords) < 3:
            return ''

        # staticmap expects (lon, lat) tuples
        poly_coords = [(float(c[0]), float(c[1])) for c in coords]

        # Derive a bounding box centre for the map
        lats = [p[1] for p in poly_coords]
        lons = [p[0] for p in poly_coords]

        # Esri tile scheme is {z}/{y}/{x} (y before x) — different from
        # standard OSM {z}/{x}/{y}. staticmap's url_template just needs the
        # placeholders in the right order for whichever server is used.
        #
        # tile_request_timeout is REQUIRED here: staticmap's default is None,
        # meaning a single stalled tile request blocks render() forever with
        # no way out. The field-onboarding Lambda has a 60s timeout — without
        # this, one slow/stuck tile turns into a full field-creation failure
        # instead of just a missing boundary map image.
        m = StaticMap(
            800, 600,
            url_template='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            tile_request_timeout=8,
        )
        polygon = Polygon(poly_coords, fill_color='#ffd70033', outline_color='#ffd700', simplify=True)
        m.add_polygon(polygon)

        image = m.render()

        buf = io.BytesIO()
        image.save(buf, format='PNG')
        buf.seek(0)

        key = f'fields/{field_id}/boundary_map.png'
        s3_client.put_object(
            Bucket=DATA_BUCKET,
            Key=key,
            Body=buf.getvalue(),
            ContentType='image/png',
            CacheControl='max-age=604800',
        )
        return f's3://{DATA_BUCKET}/{key}'

    except ImportError as e:
        logger.warning(f"staticmap not installed — boundary map skipped: {e}")
        return ''
    except Exception as e:
        logger.warning(f"Boundary map generation failed: {e}")
        return ''


# ── Weather helpers ───────────────────────────────────────────────────────────

def fetch_current_weather(lat: float, lon: float) -> Dict[str, Any]:
    today     = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    DAILY  = ['temperature_2m_max', 'temperature_2m_min',
               'precipitation_sum', 'shortwave_radiation_sum',
               'et0_fao_evapotranspiration']
    COMMON = {'latitude': lat, 'longitude': lon, 'daily': DAILY,
               'timezone': 'UTC', 'temperature_unit': 'celsius',
               'precipitation_unit': 'mm'}
    observed = {}
    try:
        hist = requests.get('https://archive-api.open-meteo.com/v1/archive',
                            params={**COMMON, 'start_date': yesterday.isoformat(),
                                    'end_date': yesterday.isoformat()}, timeout=10)
        hist.raise_for_status()
        h = hist.json().get('daily', {})
        tmax_c = (h.get('temperature_2m_max') or [25])[0] or 25
        tmin_c = (h.get('temperature_2m_min') or [10])[0] or 10
        tmax_f = round(C_TO_F(tmax_c), 1)
        tmin_f = round(C_TO_F(tmin_c), 1)
        gdd = max(0, (min(tmax_f, GDD_CAP) + max(tmin_f, GDD_BASE)) / 2 - GDD_BASE)
        observed = {
            'weatherDate':      yesterday.isoformat(),
            'tmin_f': tmin_f, 'tmax_f': tmax_f,
            'tmin_c': round(tmin_c, 1), 'tmax_c': round(tmax_c, 1),
            'precipitation_mm': round((h.get('precipitation_sum') or [0])[0] or 0, 2),
            'radiation_mj':     round((h.get('shortwave_radiation_sum') or [0])[0] or 0, 2),
            'et0_mm':           round((h.get('et0_fao_evapotranspiration') or [0])[0] or 0, 2),
            'gddDaily':         round(gdd, 2),
        }
    except Exception as e:
        logger.warning(f"Weather archive: {e}")

    forecast = []
    try:
        fc = requests.get('https://api.open-meteo.com/v1/forecast',
                          params={**COMMON, 'forecast_days': 7}, timeout=10)
        fc.raise_for_status()
        fd = fc.json().get('daily', {})
        for i, d in enumerate(fd.get('time', [])[:7]):
            tmx = C_TO_F(fd.get('temperature_2m_max', [25])[i] or 25)
            tmn = C_TO_F(fd.get('temperature_2m_min', [10])[i] or 10)
            forecast.append({
                'weatherDate': d,
                'tmax_f': round(tmx, 1), 'tmin_f': round(tmn, 1),
                'precipitation_mm': round(fd.get('precipitation_sum', [0])[i] or 0, 2),
            })
    except Exception as e:
        logger.warning(f"Weather forecast: {e}")

    return {'observed': observed, 'forecast': forecast}


def estimate_gdd_since_planting(planting_date_str: str, lat: float, lon: float) -> Dict[str, Any]:
    try:
        planting = datetime.fromisoformat(planting_date_str.replace('Z', '+00:00')).date()
    except Exception:
        planting = datetime.utcnow().date() - timedelta(days=60)
    today = datetime.utcnow().date()
    days_since = (today - planting).days
    cutoff = max(planting, today - timedelta(days=88))
    gdd_total = 0.0
    try:
        resp = requests.get('https://archive-api.open-meteo.com/v1/archive',
                            params={
                                'latitude': lat, 'longitude': lon,
                                'daily': ['temperature_2m_max', 'temperature_2m_min'],
                                'start_date': cutoff.isoformat(),
                                'end_date': (today - timedelta(days=1)).isoformat(),
                                'timezone': 'UTC', 'temperature_unit': 'celsius',
                            }, timeout=15)
        resp.raise_for_status()
        d = resp.json().get('daily', {})
        for tmax_c, tmin_c in zip(d.get('temperature_2m_max', []), d.get('temperature_2m_min', [])):
            gdd_total += max(0, (min(C_TO_F(tmax_c or 25), GDD_CAP) +
                                  max(C_TO_F(tmin_c or 10), GDD_BASE)) / 2 - GDD_BASE)
    except Exception as e:
        logger.warning(f"GDD accumulation: {e}")
        gdd_total = min(days_since, 88) * 10.0

    STAGES = [(0,'VE — Emergence'),(200,'V3 — 3rd leaf'),(450,'V6 — 6th leaf'),
              (750,'V10 — 10th leaf'),(1000,'VT — Tassel'),(1135,'R1 — Silk'),
              (1400,'R2 — Blister'),(1700,'R3 — Milk'),(1925,'R4 — Dough'),
              (2190,'R5 — Dent'),(2700,'R6 — Physiological Maturity')]
    stage = STAGES[0][1]
    for threshold, name in STAGES:
        if gdd_total >= threshold:
            stage = name
    return {'gddAccumulated': round(gdd_total, 1), 'daysSincePlanting': days_since, 'estimatedStage': stage}


# ── Satellite history backfill trigger ────────────────────────────────────────

def trigger_satellite_backfill(field_id: str) -> None:
    """
    Fire-and-forget async invocation of the daily-batch Lambda to backfill
    the last 7 available Sentinel-2 captures for a newly-created field.

    Uses InvocationType='Event' (async) rather than calling the satellite
    ingestion pipeline directly here: the daily-batch Lambda's container
    image has rio-tiler/rasterio/numpy (needed to read Sentinel-2 bands and
    compute NDVI/NDMI/NDRE) which this lightweight zip-packaged onboarding
    Lambda does not bundle. It also keeps POST /fields fast — API Gateway's
    29s hard integration timeout would very likely be exceeded by fetching
    and processing 7 satellite scenes synchronously inside field creation.

    Non-fatal: field creation has already succeeded and been persisted by
    the time this runs, so any failure here is logged and swallowed —
    the regular daily batch schedule will eventually pick up satellite data
    for this field regardless.
    """
    try:
        lambda_client.invoke(
            FunctionName=DAILY_BATCH_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'batchType': 'backfill', 'fieldId': field_id}),
        )
        logger.info(f"Satellite backfill triggered for {field_id}")
    except Exception as e:
        logger.warning(f"Could not trigger satellite backfill for {field_id} (non-fatal): {e}")


# ── DynamoDB serializer ───────────────────────────────────────────────────────

def _to_dynamo(obj):
    if isinstance(obj, float):
        return Decimal(str(round(obj, 8)))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(i) for i in obj]
    return obj


def _floatify(obj):
    """Recursively convert Decimal (DynamoDB artefact) to float/int."""
    import decimal
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _floatify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_floatify(i) for i in obj]
    return obj


# ── Handler ───────────────────────────────────────────────────────────────────

def handler(event, context):
    headers = {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}
    
    # ── GET /fields/{fieldId} — retrieve field metadata ──────────────────────
    http_method = event.get('httpMethod')
    if http_method == 'GET':
        field_id = (event.get('pathParameters') or {}).get('fieldId')
        if not field_id:
            return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'error': 'Missing fieldId in path'})}
        
        try:
            resp = fields_table.get_item(Key={'fieldId': field_id})
            field = resp.get('Item')
            if not field:
                return {'statusCode': 404, 'headers': headers, 'body': json.dumps({'error': f'Field {field_id} not found'})}
            
            return {'statusCode': 200, 'headers': headers, 'body': json.dumps(_floatify(field), default=str)}
        except Exception as e:
            logger.error(f'Failed to retrieve field {field_id}: {e}')
            return {'statusCode': 500, 'headers': headers, 'body': json.dumps({'error': 'Internal server error'})}
    
    # ── POST /fields — create new field ────────────────────────────────────
    try:
        body = json.loads(event.get('body') or '{}')
    except json.JSONDecodeError:
        return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'error': 'Invalid JSON'})}

    ok, err = validate_input(body)
    if not ok:
        return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'error': err})}

    field_id  = str(uuid.uuid4())
    user_id   = (event.get('requestContext', {}).get('authorizer', {})
                      .get('claims', {}).get('sub', 'anonymous'))

    geometry     = body['geometry']
    hybrid_rm    = int(body['hybridRM'])
    target_gdd   = int(body.get('targetGDD') or hybrid_rm * 24)
    now_iso      = datetime.utcnow().isoformat() + 'Z'

    # Name — use provided or generate random
    field_name = (body.get('fieldName') or '').strip() or random_field_name()

    # Centroid + area
    centroid_lat, centroid_lon = compute_centroid(geometry)
    area_acres = compute_area_acres(geometry)

    # Reverse geocode (fast, ~1s)
    location = reverse_geocode(centroid_lat, centroid_lon)

    # Boundary map (renders a static OSM tile PNG)
    boundary_map_s3 = generate_boundary_map(geometry, field_id)

    field_data = {
        'fieldId':         field_id,
        'userId':          user_id,
        'fieldName':       field_name,
        'geometry':        geometry,
        'centroidLat':     centroid_lat,
        'centroidLon':     centroid_lon,
        'areaAcres':       area_acres,
        'location':        location,
        'boundaryMapS3':   boundary_map_s3,
        'plantingDate':    body['plantingDate'],
        'hybridRM':        hybrid_rm,
        'targetGDD':       target_gdd,
        'irrigationType':  body['irrigationType'],
        'irrigationEvents': body.get('irrigationEvents', []),
        'soilTest':        body.get('soilTest', {}),
        'soilContext':     {'source': 'pending'},
        'createdAt':       now_iso,
        'updatedAt':       now_iso,
        'status':          'active',
        'lastObservationDate': None,
    }

    fields_table.put_item(Item=_to_dynamo(field_data))
    logger.info(f"Field created: {field_id} '{field_name}' @ {location.get('displayName')} ({area_acres} ac)")

    # Seed initial DailyStatus (weather + GDD)
    try:
        weather = fetch_current_weather(centroid_lat, centroid_lon)
        growth  = estimate_gdd_since_planting(body['plantingDate'], centroid_lat, centroid_lon)
        initial_status = {
            'fieldId':    field_id,
            'statusDate': datetime.utcnow().strftime('%Y-%m-%d') + 'T00:00:00Z',
            'weather':    weather.get('observed', {}),
            'forecast':   weather.get('forecast', [])[:7],
            'satellite':  None,
            'et':         None,
            'metrics': {
                'gddAccumulated':        growth['gddAccumulated'],
                'daysSincePlanting':     growth['daysSincePlanting'],
                'estimatedStage':        growth['estimatedStage'],
                'gddDaily':              (weather.get('observed') or {}).get('gddDaily', 0),
                'healthScore':           None,
                'healthScoreConfidence': 'pending',
                'waterStressScore':      None,
                'heatStress':            {},
                'maturityForecast':      {'predictedDate': None, 'daysToMaturity': None,
                                          'scenarioNote': 'Run batch pipeline for full forecast'},
                'riskIndicators':        {},
            },
            'aiBrief':    None,
            'source':     'initial_seed',
            'processedAt': now_iso,
        }
        daily_status_table.put_item(Item=_to_dynamo(initial_status))
        logger.info(f"Initial status seeded for {field_id}")
    except Exception as e:
        logger.warning(f"Initial status seed failed (non-fatal): {e}")

    # Kick off satellite history backfill (last 7 captures) asynchronously —
    # does not block this response; dashboard will show satellite/vision
    # data once the daily-batch Lambda finishes processing in the background.
    trigger_satellite_backfill(field_id)

    return {
        'statusCode': 201,
        'headers': headers,
        'body': json.dumps({
            'fieldId':   field_id,
            'fieldName': field_name,
            'message':   'Field created successfully',
            'field':     json.loads(json.dumps(field_data, default=str)),
        }),
    }
