# HarvestAI - Precision Crop Monitoring Platform

Precision agriculture platform for corn farmers. Real-time satellite imagery, weather data, and evapotranspiration monitoring with Claude AI-driven recommendations.

---

## Problem Statement

Corn farmers lack real-time insights into crop health and water stress across their fields. Current solutions require manual field scouting (time-consuming, inconsistent), separate tools for weather and satellite data (fragmented), and provide only generic advice (not field-specific).

HarvestAI solves this by delivering a unified, daily dashboard that combines satellite data, weather, soil moisture, and AI recommendations - enabling data-driven decisions on irrigation, pest management, and timing.

---

## Solution Overview

HarvestAI is a precision agriculture SaaS platform that:

1. Ingests Multi-Source Data Daily
   - Satellite imagery (Sentinel-2 via EarthSearch STAC)
   - Weather forecasts and historical data (Open-Meteo)
   - Evapotranspiration estimates (OpenET)
   - Soil characteristics (USDA SSURGO)

2. Computes Field-Specific Metrics
   - Vegetation indices (NDVI, NDMI, NDRE) for crop vigor
   - Water deficit (ET vs. rainfall) for irrigation decisions
   - Spatial variability zones for targeted management
   - Phenology tracking (GDD, crop stage)

3. Generates AI-Powered Recommendations
   - Claude AI analyzes satellite and weather patterns
   - Detects anomalies (stress, disease, nutrient deficiency)
   - Suggests actions (spray timing, irrigation need, scouting zones)

4. Visualizes on a Web Dashboard
   - Field maps with satellite overlays
   - Time-series charts of metrics
   - Daily brief and alerts
   - Historical trends and comparisons

---

## Architecture

![HarvestAI System Architecture](./docs/architecture-diagram.png)

The system integrates multiple data sources through AWS Lambda functions, DynamoDB for persistent storage, and Claude AI for intelligent recommendations. External APIs (EarthSearch STAC, Open-Meteo, OpenET) feed data into the daily batch processor, which computes metrics and stores results in DynamoDB for retrieval via the frontend.

### Database Schema

| Table | Primary Key | Purpose |
|-------|-------------|---------|
| **harvestai-fields-dev** | `fieldId + userId` | Field metadata (geometry, planting date, hybrid, etc.) |
| **harvestai-observations-dev** | `fieldId + observationDate` | Satellite image metadata (NDVI, cloud cover, valid pixels) |
| **harvestai-dailystatus-dev** | `fieldId + statusDate` | Daily consolidated snapshot (weather, ET, indices, AI brief) |
| **harvestai-weather-dev** | `fieldId + weatherDate` | 90-day cached weather history |
| **harvestai-et-dev** | `fieldId + etDate` | 90-day cached ET & water deficit |
| **harvestai-batchlog-dev** | `batchJobId + startTime` | Audit trail of batch runs |

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | React 18 and Vite | Modern, fast, optimal UX |
| API | AWS API Gateway | Serverless, auto-scaling, CORS support |
| Compute | AWS Lambda (Python 3.11) | Serverless, cost-effective, tight AWS integration |
| Database | DynamoDB | NoSQL, on-demand scaling, sub-millisecond latency |
| Batch | EventBridge and Lambda | Serverless orchestration, no infrastructure to manage |
| AI | Amazon Bedrock and Claude | Managed LLM, no model ops overhead |
| Storage | S3 | Satellite previews, GeoTIFFs, audit logs |
| IaC | CloudFormation | Repeatable infrastructure, version control |
| Container | Docker | Lambda container image for geospatial libraries |

---

## Key Entities and Functions

### Lambda Functions

1. FieldOnboardingFunction (60s, 256MB)
   - API: POST /fields
   - Seeds field record in DynamoDB
   - Computes initial GDD and weather summary
   - Triggers initial observation fetch

2. DailyBatchFunction (900s, 1024MB, Container)
   - Triggered by EventBridge schedule (2 AM UTC)
   - Reads all 6 DynamoDB tables
   - Calls 5 external APIs (Open-Meteo, STAC, rio-tiler, OpenET, Bedrock)
   - Computes geospatial metrics
   - Writes back to all 6 tables
   - Stores satellite previews in S3

3. GetFieldStatusFunction (30s, 256MB)
   - API: GET /fields/{fieldId}/status/latest
   - Queries harvestai-dailystatus-dev (latest record)
   - Returns JSON for frontend dashboard
   - Called every 60s by frontend

### External APIs

| API | Purpose | Rate Limit | Cost |
|-----|---------|-----------|------|
| Open-Meteo | Weather forecast and archive | Free | Free |
| EarthSearch STAC | Sentinel-2 L2A search | Unlimited | Free (AWS-hosted) |
| rio-tiler | S3 band reading via HTTP range | Unlimited | Free |
| OpenET | Evapotranspiration estimates | API key required | Commercial |
| Amazon Bedrock | Claude Haiku (text brief and vision) | On-demand | Pay-per-token |

---

## Quick Start

### Prerequisites
- AWS CLI v2 (configured with credentials)
- Docker (for Lambda builds)
- Node.js 18+ (frontend)
- Python 3.11+ (backend development)

### Deploy in 5 Steps

```bash
# 1. Clone and enter directory
git clone https://github.com/harshagangari747/HarvestAI.git
cd HarvestAI

# 2. Store secrets in AWS Secrets Manager
aws secretsmanager create-secret \
  --name harvestai/api-keys \
  --secret-string '{
    "openet_api_key": "YOUR_KEY",
    "bedrock_model_id": "anthropic.claude-3-5-haiku-20241022-v1:0"
  }'

# 3. Deploy CloudFormation stack
aws cloudformation create-stack \
  --stack-name harvestai-mvp-dev \
  --template-body file://infrastructure/main.yaml \
  --parameters ParameterKey=Environment,ParameterValue=dev \
  --capabilities CAPABILITY_NAMED_IAM

aws cloudformation wait stack-create-complete \
  --stack-name harvestai-mvp-dev

# 4. Build and deploy Lambda container
cd backend && docker build -t harvestai-lambdas:latest .
# Push to ECR (see docs/DEPLOYMENT.md for details)

# 5. Deploy frontend
cd frontend && npm install && npm run build
# Deploy to Amplify or S3 with CloudFront
```

See docs/DEPLOYMENT.md for detailed instructions.

---

## API Endpoints

| Method | Endpoint | Purpose | Response |
|--------|----------|---------|----------|
| POST | /fields | Create field | fieldId, geometry, plantingDate |
| GET | /fields/{fieldId} | Get field metadata | fieldId, userId, geometry, ... |
| GET | /fields/{fieldId}/status/latest | Latest daily snapshot | statusDate, weather, satellite, ET, aiBrief |
| GET | /fields/{fieldId}/timeseries | Historical metrics | [{ date, ndvi, ndmi, stress }, ...] |
| GET | /fields/{fieldId}/maps/latest | Map layers and zones | satellite_url, zones, stats |
| POST | /fields/{fieldId}/run | Trigger batch manually | batchJobId, status |

Full contracts: docs/API_CONTRACTS.md

---

## Project Structure

```
HarvestAI/
├── README.md                          # This file
├── infrastructure/                    # CloudFormation IaC
│   ├── main.yaml                      # Root stack
│   ├── database.yaml                  # DynamoDB tables
│   ├── lambda.yaml                    # Lambda and IAM roles
│   └── networking.yaml                # API Gateway and EventBridge
│
├── backend/                           # Python Lambda functions
│   ├── requirements.txt               # Dependencies
│   ├── Dockerfile                     # Lambda container image
│   └── lambda_functions/
│       ├── field_onboarding/handler.py    # POST /fields
│       ├── daily_batch/handler.py         # Batch orchestration
│       ├── ingestion/
│       │   ├── weather.py                 # Open-Meteo integration
│       │   ├── satellite.py               # STAC and rio-tiler
│       │   ├── et.py                      # OpenET integration
│       │   ├── soil.py                    # Soil characteristics
│       │   └── bedrock_brief.py           # Claude AI brief
│       └── shared/
│           ├── metrics.py                 # NDVI, NDMI, NDRE, CIre
│           └── __init__.py
│
├── frontend/                          # React and Vite web app
│   ├── package.json
│   ├── vite.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── LandingPage.jsx        # Home and feature overview
│   │   │   ├── FieldSetup.jsx         # Onboarding form
│   │   │   └── FieldDashboard.jsx     # Main monitoring dashboard
│   │   ├── components/
│   │   │   └── Navigation.jsx
│   │   └── api/
│   │       └── client.js              # Axios client
│   └── .env.example
│
├── docs/                              # Documentation
│   ├── DEPLOYMENT.md                  # Step-by-step AWS setup
│   └── API_CONTRACTS.md               # Detailed API specs
│
└── .github/                           # GitHub configuration
    ├── workflows/security.yml         # CI/CD security checks
    └── ISSUE_TEMPLATE/
```

---

## Security and Compliance

- Secrets Management - API keys stored in AWS Secrets Manager, never in code
- IAM Least Privilege - Lambda functions have minimal required permissions
- Network Isolation - Lambda runs in VPC (no public internet access)
- Encryption - DynamoDB encrypted at rest, HTTPS for all APIs
- Audit Logging - CloudWatch Logs and EventBridge audit trail
- Pre-Commit Hooks - Secrets detection before code push
- Code Scanning - Automated security and dependency checks (GitHub Actions)

---

## Cost Estimation (Monthly, US-WEST-2)

| Component | Estimate | Notes |
|-----------|----------|-------|
| Lambda | $2-5 | ~86k invocations (daily batch + APIs) |
| DynamoDB | $5-15 | On-demand billing, TTL cleanup |
| S3 | $1-3 | Satellite previews and logs |
| API Gateway | $3-5 | ~1M requests per month |
| Data Transfer | $0-2 | Minimal outbound |
| Bedrock | $0.50-3 | Claude Haiku pricing (~100k tokens per day) |
| Total | $11.50-33 | Scales linearly with fields |

---

## Documentation

- README.md - Project overview (this file)
- docs/DEPLOYMENT.md - Step-by-step AWS setup
- docs/API_CONTRACTS.md - API endpoint details
- PROJECT_SUMMARY.md - Detailed architecture

---

## Support

- Issues - Use GitHub Issues for bug reports and feature requests
- Questions - Check documentation first, then open a Discussion
- Bugs - Report with reproduction steps and CloudWatch logs

---

## License

HarvestAI is open source. See LICENSE file for terms.

---

Built for the HarvestAI MVP Hackathon on AWS.
Powered by AWS Lambda, DynamoDB, Bedrock, and the geospatial open-source community.
