# HarvestAI API Contracts

Base URL: `https://your-api-gateway-url.execute-api.region.amazonaws.com/dev`

## Authentication

Currently, endpoints are open (no authentication). For production, add Cognito authorizer:

```
Authorization: Bearer <cognito-id-token>
```

## Endpoints

### 1. POST /fields - Create Field

Creates a new field for monitoring.

**Request Body:**
```json
{
  "geometry": {
    "type": "Polygon",
    "coordinates": [
      [
        [-93.5, 41.5],
        [-93.4, 41.5],
        [-93.4, 41.6],
        [-93.5, 41.6],
        [-93.5, 41.5]
      ]
    ]
  },
  "plantingDate": "2024-05-01T00:00:00Z",
  "hybridRM": 105,
  "targetGDD": 2500,
  "irrigationType": "rainfed",
  "soilTest": {
    "pH": 6.5,
    "organicMatter": 3.2,
    "phosphorus": 45,
    "potassium": 180
  },
  "tags": ["organic", "high-value"]
}
```

**Response (201 Created):**
```json
{
  "fieldId": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Field created successfully",
  "field": {
    "fieldId": "550e8400-e29b-41d4-a716-446655440000",
    "userId": "user123",
    "centroidLat": 41.55,
    "centroidLon": -93.45,
    "plantingDate": "2024-05-01T00:00:00Z",
    "hybridRM": 105,
    "targetGDD": 2500,
    "irrigationType": "rainfed",
    "createdAt": "2024-01-15T10:30:00Z",
    "status": "active"
  }
}
```

**Status Codes:**
- 201: Created successfully
- 400: Invalid input (missing required fields)
- 500: Server error

---

### 2. GET /fields/{fieldId} - Get Field

Retrieves field metadata and soil context.

**Response (200 OK):**
```json
{
  "fieldId": "550e8400-e29b-41d4-a716-446655440000",
  "userId": "user123",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "centroidLat": 41.55,
  "centroidLon": -93.45,
  "plantingDate": "2024-05-01T00:00:00Z",
  "hybridRM": 105,
  "targetGDD": 2500,
  "irrigationType": "rainfed",
  "soilTest": {
    "pH": 6.5,
    "organicMatter": 3.2,
    "phosphorus": 45,
    "potassium": 180
  },
  "soilContext": {
    "texture": "Silt Loam",
    "drainage": "Well Drained",
    "availableWaterCapacity": 0.18,
    "source": "SSURGO"
  },
  "createdAt": "2024-01-15T10:30:00Z",
  "updatedAt": "2024-01-15T10:30:00Z",
  "status": "active"
}
```

**Status Codes:**
- 200: Success
- 404: Field not found
- 500: Server error

---

### 3. GET /fields/{fieldId}/status/latest - Get Latest Daily Status

Retrieves the most recent daily status with satellite data, weather, and AI brief.

**Response (200 OK):**
```json
{
  "fieldId": "550e8400-e29b-41d4-a716-446655440000",
  "statusDate": "2024-01-20T00:00:00Z",
  "weather": {
    "date": "2024-01-20T00:00:00Z",
    "tmin": 15.0,
    "tmax": 28.0,
    "precipitation": 0.0,
    "radiation": 20.0
  },
  "satellite": {
    "date": "2024-01-19T00:00:00Z",
    "ndvi": 0.65,
    "ndmi": 0.35,
    "ndre": 0.42,
    "validPixelFraction": 0.95,
    "cloudCover": 0.02
  },
  "et": {
    "date": "2024-01-20T00:00:00Z",
    "et": 5.2
  },
  "metrics": {
    "gddAccumulated": 150.5,
    "gddDaily": 11.2,
    "daysSincePlanting": 15,
    "healthScore": 75,
    "healthScoreConfidence": "medium",
    "waterStressIndicator": 0.3,
    "heatStressIndicator": 0.1,
    "predictedMaturityDate": "2024-08-20T00:00:00Z",
    "riskIndicators": {
      "failureRisk": 0.1,
      "qualityRisk": 0.15
    }
  },
  "aiBrief": {
    "summary": "Corn field shows good vigor with stable moisture levels.",
    "topRisks": [
      "Potential heat stress in next 3-5 days",
      "Monitor water stress as deficit increases"
    ],
    "recommendedActions": [
      "Scout for insects and disease",
      "Check soil moisture at 6-12 inch depth"
    ],
    "scoutingChecklist": [
      "Visual inspection of canopy color",
      "Check leaf margin burn or striping",
      "Inspect soil for compaction"
    ],
    "confidence": "medium",
    "confidenceReason": "Based on satellite data 2 days old; recommend fresh observation"
  },
  "batchJobId": "batch-2024-01-20T02:00:00Z",
  "processedAt": "2024-01-20T02:00:15Z"
}
```

**Status Codes:**
- 200: Success
- 404: No status found
- 500: Server error

---

### 4. GET /fields/{fieldId}/timeseries - Get Time Series Data

Retrieves historical time series for charting (NDVI, health score, etc.).

**Query Parameters:**
- `days=30` (optional): Number of days back to retrieve (default 30)

**Response (200 OK):**
```json
{
  "fieldId": "550e8400-e29b-41d4-a716-446655440000",
  "timeseries": [
    {
      "date": "2024-01-05T00:00:00Z",
      "ndvi": 0.52,
      "ndmi": 0.28,
      "ndre": 0.35,
      "healthScore": 60,
      "gdd": 120.5,
      "et": 4.8,
      "precipitation": 0.5
    },
    {
      "date": "2024-01-10T00:00:00Z",
      "ndvi": 0.58,
      "ndmi": 0.32,
      "ndre": 0.38,
      "healthScore": 68,
      "gdd": 140.2,
      "et": 5.1,
      "precipitation": 0.0
    },
    {
      "date": "2024-01-20T00:00:00Z",
      "ndvi": 0.65,
      "ndmi": 0.35,
      "ndre": 0.42,
      "healthScore": 75,
      "gdd": 150.5,
      "et": 5.2,
      "precipitation": 0.0
    }
  ]
}
```

**Status Codes:**
- 200: Success
- 404: Field not found
- 500: Server error

---

### 5. GET /fields/{fieldId}/maps/latest - Get Map Data

Retrieves latest satellite map layers (NDVI, NDMI previews) and spatial zone statistics.

**Response (200 OK):**
```json
{
  "fieldId": "550e8400-e29b-41d4-a716-446655440000",
  "maps": {
    "ndviPreview": "https://harvestai-data.s3.amazonaws.com/fields/550e8400-e29b-41d4-a716-446655440000/ndvi_latest.png",
    "ndmiPreview": "https://harvestai-data.s3.amazonaws.com/fields/550e8400-e29b-41d4-a716-446655440000/ndmi_latest.png",
    "ndrePreview": "https://harvestai-data.s3.amazonaws.com/fields/550e8400-e29b-41d4-a716-446655440000/ndre_latest.png"
  },
  "statistics": {
    "ndvi": {
      "mean": 0.65,
      "median": 0.67,
      "p10": 0.52,
      "p90": 0.78,
      "std": 0.08
    },
    "ndmi": {
      "mean": 0.35,
      "median": 0.36,
      "p10": 0.22,
      "p90": 0.48,
      "std": 0.06
    },
    "zones": {
      "lowZone": {
        "percentArea": 33,
        "meanNDVI": 0.52
      },
      "midZone": {
        "percentArea": 33,
        "meanNDVI": 0.65
      },
      "highZone": {
        "percentArea": 34,
        "meanNDVI": 0.78
      }
    }
  },
  "observationDate": "2024-01-19T00:00:00Z",
  "daysOld": 1
}
```

**Status Codes:**
- 200: Success
- 404: No maps available
- 500: Server error

---

### 6. POST /fields/{fieldId}/run - Trigger Batch Run

Manually triggers the daily batch pipeline for a specific field.

**Request Body (optional):**
```json
{
  "force": true,
  "includeHistoricalSatellite": false
}
```

**Response (200 OK):**
```json
{
  "batchJobId": "batch-2024-01-20T10:30:00Z",
  "fieldId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "initiated",
  "message": "Batch job triggered successfully",
  "estimatedDuration": "5-10 minutes"
}
```

**Status Codes:**
- 200: Batch triggered
- 400: Invalid field
- 500: Server error

---

## Error Responses

All error responses follow this format:

```json
{
  "error": "Error message here",
  "code": "ERROR_CODE",
  "timestamp": "2024-01-20T10:30:00Z"
}
```

Common error codes:
- `FIELD_NOT_FOUND`: Field doesn't exist
- `INVALID_GEOMETRY`: Invalid GeoJSON polygon
- `MISSING_FIELD`: Required field is missing
- `INVALID_DATE`: Date format is not ISO 8601
- `INTERNAL_SERVER_ERROR`: Unexpected server error

---

## Rate Limiting

Currently no rate limiting. For production, implement:
- 100 requests/minute per user
- 10 batch jobs/hour per field
- 1000 requests/hour per API key

---

## CORS Headers

All responses include CORS headers:
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

---

## Pagination (Future)

Future endpoints will support pagination:
```
?page=1&pageSize=20
```

Response will include:
```json
{
  "data": [...],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "total": 150
  }
}
```
