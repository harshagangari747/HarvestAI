# Spec: Corn Field Monitoring MVP (Satellite + Weather + ET + AI Recommendations)
Version: 1.0  
Target: Hackathon shippable MVP on AWS (public URL)  
Region: United States  
Primary user: Farmer monitoring a corn field from planting → harvest  
Core loop: Onboard field → daily batch runs → dashboard updates → AI actions + outlook

---

## 1) Problem Statement
Corn production is highly dynamic and strongly affected by weather variability, water stress, nutrient limitations, and field spatial variability. Farmers typically lack a unified, easy-to-use, daily view that combines:
- satellite-based crop condition,
- weather + short-term forecast,
- evapotranspiration (ET) and water balance,
- soil context,
- and actionable next steps.

Without proactive monitoring, stress can go unnoticed until yield potential is already lost.

---

## 2) Solution Overview
Build a web application that:
1. Lets a farmer onboard a field (polygon + planting date + hybrid maturity + irrigation + soil test results).
2. Runs a daily batch pipeline that:
   - retrieves new satellite data (Sentinel-2; optional Sentinel-1),
   - retrieves ET (OpenET) and weather + solar radiation (Open-Meteo / NOAA, optional NSRDB),
   - retrieves soil context (SSURGO),
   - computes crop condition indices, stress indicators, phenology signals, and maturity/harvest window estimates,
   - generates an AI daily brief and recommended actions (Amazon Bedrock).
3. Shows a dashboard with:
   - latest map layers (NDVI/NDMI/NDRE) and within-field variability zones,
   - time series of indices and scores,
   - daily crop status with confidence,
   - 30-day outlook (risk windows),
   - predicted maturity/harvest readiness window,
   - downloadable/shareable report.

**Important modeling principle (MVP honesty):**
- Satellite observations are not guaranteed daily due to revisit and clouds.
- The app produces a **Daily Status** by combining:
  - last clear satellite observation (when available),
  - weather/ET-driven daily updates in between,
  - confidence indicator + “Last clear satellite date”.

---

## 3) End Goal (What “Done” Looks Like)
### Required MVP outcomes
- Public web app URL reachable by judges.
- Farmer can:
  - create a field,
  - view latest satellite-derived crop condition,
  - see daily updated status + AI recommendations,
  - see 30-day outlook + predicted maturity window.
- Daily batch job runs automatically and updates results.
- Evidence of development process + coding agent helping ship (screenshots/logs).

### Output metrics (minimum)
- NDVI, NDMI, NDRE/CIred-edge (field stats + maps)
- ET (daily or recent)
- Weather summary + 2-day forecast (plus 7/30 day outlook recommended)
- GDD accumulation + stage estimate
- Health/Stature score (0–100) + confidence
- Predicted physiological maturity window (R6 range)
- Risk indicators: water stress, heat stress, saturation/flood risk (if implemented)
- AI: summary + top risks + recommended actions + scouting checklist

---

## 4) Methodology (High-Level)
### 4.1 Inputs from Farmer (Field Onboarding)
Farmer provides:
- Field boundary (polygon / coordinates)
- Planting date
- Area (or computed from polygon)
- Irrigation details (rainfed / irrigated; optional irrigation events)
- Corn seed variant / hybrid maturity:
  - Relative Maturity (RM) OR
  - target GDD to maturity (preferred if known)
- Soil test results (manual entry):
  - pH, OM, P, K, optional micros

### 4.2 Data Collected Daily (Batch)
- Satellite (Sentinel-2 L2A): reflectance bands + SCL for masking
- ET (OpenET): ET and/or anomaly (US)
- Weather + solar radiation: daily observed + forecast (Open-Meteo or NOAA)
- Static soil: SSURGO for texture/drainage context (one-time or cached)
- Optional:
  - Sentinel-1 SAR for flood/saturation mapping
  - Landsat thermal for LST (advanced; optional stretch)

### 4.3 Derived Computations
- Vegetation indices: NDVI, NDMI, NDRE/CIred-edge
- Phenology signals: green-up/peak/senescence trends from time series
- Spatial variability: low/med/high vigor zones and variability score
- Water balance stress: ET vs rainfall (+ irrigation if logged)
- Heat stress forecast windows: Tmax threshold counts near sensitive stages
- Maturity estimation: GDD-based predicted R6 (physiological maturity) range
- Daily Health/Stature score + confidence
- Risk scores (MVP “indicators”, not absolute truth): failure risk, quality risk

### 4.4 AI Recommendations
Use Amazon Bedrock LLM to transform computed metrics into:
- a daily brief,
- 3–6 actionable next steps,
- scouting checklist to confirm likely causes,
- confidence rationale.

---

## 5) Data Collection Resources (US) + How to Use Them
> Store all secrets/keys in AWS Secrets Manager or environment variables. Never commit keys.

### 5.1 Sentinel-2 L2A (Primary optical satellite)
**EarthSearch STAC (AWS-hosted, no key)**
- Endpoint: https://earth-search.aws.element84.com/v1
- Collection: `sentinel-2-l2a`
- Usage:
  1) STAC search by field polygon + date range + cloud filter
  2) select best item(s) (lowest cloud; highest valid pixel coverage)
  3) read band assets as COGs and compute indices
- Notes:
  - Use SCL to cloud-mask.
  - Revisit ~5 days; clouds may reduce usable frequency.

### 5.2 ET for US (Recommended)
**OpenET (API key)**
- Developers: https://openetdata.org/developers
- Usage:
  - Query ET time series for geometry (field polygon) and date range.
  - Cache results; only refresh incremental days daily.
- Output:
  - ET (mm/day or inches/day), sometimes anomaly depending on endpoint/model.

### 5.3 Weather + Forecast + Radiation
**Open-Meteo (no key; easiest for MVP)**
- Docs: https://open-meteo.com/en/docs
- Usage:
  - Query by centroid lat/lon.
  - Pull daily: Tmin/Tmax, precipitation, optional radiation, wind/humidity.

**NOAA/NWS API (no key; optional)**
- Docs: https://www.weather.gov/documentation/services-web-api
- Usage:
  - Use grid endpoints for official forecast, hazards.

**NREL NSRDB (API key; optional for high-quality solar radiation)**
- Signup: https://developer.nrel.gov/signup/
- Docs: https://developer.nrel.gov/docs/solar/nsrdb/
- Usage:
  - Query solar radiation for lat/lon + date range.

### 5.4 Soil Texture / Drainage (US best option)
**USDA NRCS Soil Data Access (SSURGO SDA) (no key)**
- Portal: https://sdmdataaccess.nrcs.usda.gov/
- REST endpoint: https://sdmdataaccess.nrcs.usda.gov/Tabular/post.rest
- Usage:
  - POST SQL queries to fetch soil properties for the field polygon or its map units.
- Store:
  - dominant texture class
  - drainage class
  - available water capacity proxy if accessible

### 5.5 Optional / Stretch Data
**NASA Earthdata login** (for Sentinel-1 via ASF, SMAP, MODIS, GPM)
- Signup: https://urs.earthdata.nasa.gov/users/new
- ASF portal: https://search.asf.alaska.edu/
- ASF docs: https://docs.asf.alaska.edu/

**USDA NASS QuickStats (optional benchmarking; API key)**
- Key + docs: https://quickstats.nass.usda.gov/api
- Use: county-level corn yield baselines.

---

## 6) System Architecture (AWS MVP)
### 6.1 Components
- Frontend: React/Next.js hosted on **AWS Amplify Hosting** (public URL).
- Backend API: **API Gateway** + **AWS Lambda** (Python).
- Batch scheduler: **EventBridge Scheduler** triggers daily Lambda/ECS task.
- Storage:
  - **DynamoDB** (Field metadata, Observations, DailyStatus)
  - **S3** (PNG previews, generated reports, cached artifacts)
- AI: **Amazon Bedrock** for daily narrative and recommendations.
- Monitoring: CloudWatch Logs, metrics, alarms.

### 6.2 Why Lambda container image
Raster processing needs geospatial libs:
- `rasterio`, `rio-tiler`, `numpy`, `shapely`, `pyproj`
Use Lambda container image for dependencies.

---

## 7) Data Ingestion & Processing (Step-by-Step)
### 7.1 Onboarding (One-Time / Rare)
1) User submits field polygon + inputs.
2) Compute:
   - centroid, area
3) Fetch soil context from SSURGO SDA and store in `Fields`.
4) (Optional) Fetch county baseline yield (NASS QuickStats) and store.

### 7.2 Daily Batch (Runs Every Day)
For each `fieldId`:
1) Weather ingest:
   - Pull daily observed and next 2 days (and preferably 30-day outlook)
   - Compute GDD daily and cumulative since planting
2) ET ingest:
   - Pull latest ET values from OpenET (incremental)
3) Satellite ingest:
   - STAC search for Sentinel-2 since last clear observation
   - If new clear scene found:
     - download needed bands (B04, B08, B11, B05/B06/B07, SCL)
     - clip to polygon
     - mask clouds/shadows
     - compute NDVI/NDMI/NDRE/CIre rasters
     - compute field stats and zone stats
     - store Observation + create PNG preview(s) saved to S3
4) Derived daily status:
   - Update stress indicators
   - Update health score + confidence
   - Update maturity forecast window
   - Update risk scores
5) AI generation:
   - Create structured prompt input JSON
   - Bedrock returns JSON: summary, risks, actions, scouting checklist
6) Store DailyStatus for today.

---

## 8) Calculations (MVP Definitions)
### 8.1 Cloud/Quality Confidence
- `valid_pixel_fraction = valid_pixels / total_pixels`
- Observation quality:
  - High: >= 0.7
  - Medium: 0.4–0.7
  - Low: < 0.4
- Daily confidence decays with days since last clear image:
  - `confidence = High` if last_clear_age <= 5 days
  - Medium if 6–12 days
  - Low if > 12 days

### 8.2 Vegetation Indices (Sentinel-2)
Using reflectance bands:
- NDVI:
  - Red = B04, NIR = B08  
  - NDVI = (B08 − B04) / (B08 + B04)

- NDMI (moisture proxy):
  - SWIR = B11 (or B12), NIR = B08  
  - NDMI = (B08 − B11) / (B08 + B11)

- NDRE (chlorophyll proxy):
  - RE = B05 (or B06/B07), NIR = B08  
  - NDRE = (B08 − B05) / (B08 + B05)

- CI red-edge:
  - CIre = (B08 / B05) − 1

Field stats to store per observation:
- mean, median, p10, p90
- variability proxy: `cv = std / (mean + eps)`

### 8.3 Phenology (from NDVI/NDRE time series)
- Smooth series: rolling median over last 3–5 observations.
- Peak canopy date: date of max smoothed NDVI.
- Senescence signal: sustained negative slope after peak.

MVP slope:
- `ndvi_slope = (ndvi_last - ndvi_prev) / days_between`

### 8.4 Spatial Variability Zones
On latest clear NDVI raster:
- Low zone: NDVI < P33
- Mid: P33–P66
- High: > P66

Store:
- % area in each zone, mean NDVI per zone

### 8.5 GDD and Maturity Forecast
Corn GDD (base 50°F, cap 86°F):
- TmaxCapped = min(Tmax, 86)
- TminCapped = max(Tmin, 50)
- GDD = ((TmaxCapped + TminCapped)/2) − 50

Cumulative:
- `GDD_to_date = sum(GDD from plantingDate to today)`

Maturity target:
- Either farmer supplies `targetGDDMaturity`,
- or map hybrid RM → approx target GDD (table-based; MVP can implement a simple mapping or require input).

Predicted physiological maturity (R6):
- Find future date where `GDD_to_date + sum(forecastGDD) >= targetGDDMaturity`
- Output a date range using:
  - warm/normal/cool scenario (MVP) OR forecast ensemble (advanced)

### 8.6 Water Stress Indicators
Option A (preferred if OpenET works):
- Water deficit accumulator:
  - deficit[t] = deficit[t-1] + ET[t] − (Rain[t] + Irrigation[t])
- Normalize to 0–1 stress score using a capped scale or logistic.

Option B (fallback):
- Use ET0 proxy from weather and same equation.

### 8.7 Heat Stress Indicators
- `heatStressDaysNext7 = count(Tmax_forecast > 95°F over next 7 days)`
- Flag if near sensitive stage:
  - If stage estimate indicates approaching tassel/silk window, elevate severity.

### 8.8 Health/Stature Score (0–100) (MVP)
Compute a weighted score (tunable constants):
- vigor component from NDVI level and trend
- moisture component from NDMI and deficit
- heat penalty from heat stress days
- confidence penalty from days since last clear satellite

Example (conceptual):
- Score = clamp(0,100,
  60*f(NDVI) + 25*f(NDMI) + 15*f(-stress) - confidencePenalty
)

### 8.9 Risk Scores (MVP “Indicators”)
- Failure risk (0–1): increases with very low NDVI, sharp NDVI drop, high deficit, flood flags.
- Quality risk (0–1): proxy from late-season wetness and stress + lodging risk proxies.
**UI Labeling:** “Risk indicator (model-based). Confirm with scouting.”

---

## 9) AI Recommendation Generation (Amazon Bedrock)
### 9.1 Inputs to LLM (structured JSON)
- Field: crop=corn, plantingDate, irrigationType, soil summary, soil test values
- Latest satellite date + NDVI/NDMI/NDRE stats + slopes
- ET summary + deficit trend
- Weather: past 7/14, next 2 days, next 30 days summary
- Stage estimate + predicted flowering/maturity window
- Confidence level

### 9.2 Output format (JSON enforced)
- summary (string)
- top_risks (array of strings)
- recommended_actions (array of strings)
- scouting_checklist (array of strings)
- confidence (high|medium|low) + confidence_reason

### 9.3 Guardrails
- Recommendations must be phrased as:
  - scouting + verification steps,
  - irrigation timing guidance (if irrigated),
  - “consider agronomist consultation” for fertilizer rates unless enough ground truth exists.

---

## 10) API Contracts (Backend)
### Required endpoints
- `POST /fields`
  - body: geometry (GeoJSON), plantingDate, hybridRM/targetGDD, irrigationType, soilTest fields
  - returns: fieldId

- `GET /fields/{fieldId}`
  - returns: metadata + soil context

- `GET /fields/{fieldId}/status/latest`
  - returns: today DailyStatus + last observation summary + confidence

- `GET /fields/{fieldId}/timeseries`
  - returns: arrays of dates, NDVI/NDMI/NDRE, HealthScore, deficit, GDD

- `GET /fields/{fieldId}/maps/latest`
  - returns: S3 URLs for latest NDVI/NDMI preview PNGs + zone stats

- `POST /fields/{fieldId}/run` (admin/manual trigger)
  - triggers batch for a single field (useful for demo)

---

## 11) UI Requirements (MVP Screens)
1) Landing + “Add Field”
2) Field setup wizard:
   - map polygon drawing/upload
   - planting date, hybrid maturity, irrigation, soil tests
3) Field dashboard:
   - Map: NDVI layer + zone overlay + last clear satellite date
   - Charts: NDVI/NDMI/HealthScore vs time
   - “Today’s Brief” panel: AI summary + actions
   - 30-day outlook: heat/water risk timeline
   - Harvest: predicted maturity window + “start checking grain moisture after X date”
4) (Optional) PDF export report.

---

## 12) Implementation Notes / Constraints
- Atmospheric gas composition (CO2/NOx) is not field-actionable at typical satellite resolution; not required for MVP conclusions.
- Cloud cover reduces optical satellite frequency; system must handle missing imagery gracefully.
- Keep computations explainable and conservative; label outputs as indicators, not guaranteed outcomes.

---

## 13) Deployment & Hackathon Compliance
- App must be live on AWS with a public URL (Amplify recommended).
- Provide proof of coding agent + AWS connection:
  - screenshots/video of agent (e.g., Amazon Q) aiding deployment/code
  - `aws sts get-caller-identity` output in README
  - deployment logs (Amplify/CDK/SAM)

---

## 14) Acceptance Criteria (Pass/Fail for MVP)
- [ ] Public URL loads and allows adding/viewing a field
- [ ] Daily status visible with:
  - NDVI/NDMI metrics and last clear satellite date
  - Weather + forecast summary
  - GDD + maturity estimate
  - AI brief + actions
- [ ] Batch job can be triggered (scheduled or manual) and updates stored results
- [ ] Basic monitoring logs visible (CloudWatch)
- [ ] README includes architecture + data sources + limitations + demo steps

---

## 15) Recommended Build Order
1) Field onboarding + DynamoDB schema
2) Open-Meteo weather ingestion + GDD + stage estimate
3) Sentinel-2 EarthSearch ingestion + NDVI/NDMI/NDRE calculations + S3 previews
4) OpenET integration + water deficit indicator
5) Daily batch orchestration (EventBridge)
6) Bedrock daily brief generation
7) UI polish + demo dataset preload + manual “Run Now” button