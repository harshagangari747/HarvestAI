# HarvestAI — Precision Crop Monitoring Platform

> **AI-powered crop intelligence for corn farmers**  
> Real-time satellite imagery, weather data, and evapotranspiration monitoring with Claude AI-driven recommendations.

---

## 🎯 Problem Statement

Corn farmers lack real-time insights into crop health and water stress across their fields. Current solutions require:
- Manual field scouting (time-consuming, inconsistent)
- Separate tools for weather, soil, and satellite data (fragmented)
- Generic advice (not field-specific)

**HarvestAI solves this** by delivering a unified, daily dashboard that combines satellite data, weather, soil moisture, and AI recommendations—enabling data-driven decisions on irrigation, pest management, and timing.

---

## 💡 Solution Overview

HarvestAI is a **precision agriculture SaaS platform** that:

1. **Ingests Multi-Source Data Daily**
   - Satellite imagery (Sentinel-2 via EarthSearch STAC)
   - Weather forecasts & historical data (Open-Meteo)
   - Evapotranspiration estimates (OpenET)
   - Soil characteristics (USDA SSURGO)

2. **Computes Field-Specific Metrics**
   - Vegetation indices (NDVI, NDMI, NDRE) for crop vigor
   - Water deficit (ET vs. rainfall) for irrigation decisions
   - Spatial variability zones for targeted management
   - Phenology tracking (GDD, crop stage)

3. **Generates AI-Powered Recommendations**
   - Claude AI analyzes satellite & weather patterns
   - Detects anomalies (stress, disease, nutrient deficiency)
   - Suggests actions (spray timing, irrigation need, scouting zones)

4. **Visualizes on a Web Dashboard**
   - Field maps with satellite overlays
   - Time-series charts of metrics
   - Daily brief & alerts
   - Historical trends & comparisons

---

## 🏗️ Architecture

### High-Level System Design

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (React + Vite)                    │
│                    FieldDashboard / FieldSetup                   │
│                  (AWS Amplify or S3 + CloudFront)                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    API Gateway (REST)
                             │
                ┌────────────┴────────────┐
                │                         │
        ┌───────▼────────┐      ┌────────▼─────────┐
        │  GetFieldStatus │      │ FieldOnboarding  │
        │   Lambda (30s)  │      │   Lambda (60s)   │
        └────────┬────────┘      └────────┬─────────┘
                 │                        │
        ┌────────▼────────────────────────▼─────────┐
        │         DynamoDB Tables (6 tables)        │
        ├──────────────────────────────────────────┤
        │ • harvestai-fields        (Field metadata)│
        │ • harvestai-dailystatus   (Daily snapshot)│
        │ • harvestai-observations  (Satellite data)│
        │ • harvestai-weather       (90-day cache)  │
        │ • harvestai-et            (90-day cache)  │
        │ • harvestai-batchlog      (Audit trail)   │
        └──────────────────────────────────────────┘
                 ▲
                 │
        ┌────────┴──────────────┐
        │  DailyBatchFunction   │
        │  (EventBridge, 900s)  │
        └────────┬──────────────┘
                 │
    ┌────────────┼────────────┬──────────────┬──────────────┐
    │            │            │              │              │
    ▼            ▼            ▼              ▼              ▼
┌────────┐ ┌─────────┐ ┌───────────┐ ┌────────────┐ ┌──────────────┐
│ Open-  │ │EarthSearch│ │rio-tiler │ │ OpenET    │ │ Amazon       │
│Meteo   │ │STAC      │ │(S3 bands)│ │API        │ │ Bedrock      │
│Weather │ │Sentinel-2│ │Band math │ │ET deficit │ │ Claude Haiku │
│API     │ │L2A      │ │NDVI, NDMI│ │           │ │ (AI Brief)   │
└────────┘ └─────────┘ └───────────┘ └────────────┘ └──────────────┘
    │            │            │              │              │
    └────────────┼────────────┴──────────────┴──────────────┘
                 │
                 S3 (Satellite Previews, GeoTIFFs)
```

### Data Flow (Daily at 2 AM UTC)

```
EventBridge Trigger (Scheduled)
            │
            ▼
┌───────────────────────────────────────────────────────────┐
│       DailyBatchFunction (Container Image, 1024MB)        │
└───────────────────────────────────────────────────────────┘
            │
    ┌───────┼────────┬──────────┬────────────┐
    │       │        │          │            │
    ▼       ▼        ▼          ▼            ▼
┌──────┐ ┌──────┐ ┌──────────┐ ┌────────┐ ┌────────┐
│READ  │ │COMPUTE│ │WRITE    │ │STORE   │ │GENERATE│
│Data  │ │Metrics│ │Results  │ │Previews│ │Brief   │
├──────┤ ├──────┤ ├──────────┤ ├────────┤ ├────────┤
│Fields│ │NDVI  │ │dailystatus
        │weather│
        │obsrvns│ │      S3    │ │Bedrock│
│Weather│ │NDMI  │ │        │ │  →     │
│ET     │ │NDRE  │ │  Zones  │ │ Claude │
└──────┘ │Vigor │ │Metrics  │ └────────┘ └────────┘
         │Stress│ │     │
         │CIre  │ │     ▼
         └──────┘ │DynamoDB
                  │(6 tables)
                  └──────────┘
```

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

## 🔧 Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Frontend** | React 18 + Vite | Modern, fast, optimal UX |
| **API** | AWS API Gateway | Serverless, auto-scaling, CORS support |
| **Compute** | AWS Lambda (Python 3.11) | Serverless, cost-effective, tight AWS integration |
| **Database** | DynamoDB | NoSQL, on-demand scaling, sub-millisecond latency |
| **Batch** | EventBridge + Lambda | Serverless orchestration, no infrastructure to manage |
| **AI** | Amazon Bedrock + Claude | Managed LLM, no model ops overhead |
| **Storage** | S3 | Satellite previews, GeoTIFFs, audit logs |
| **IaC** | CloudFormation | Repeatable infrastructure, version control |
| **Container** | Docker | Lambda container image for geospatial libraries |

---

## 📊 Key Entities & Functions

### Lambda Functions

1. **FieldOnboardingFunction** (60s, 256MB)
   - API: `POST /fields`
   - Seeds field record in DynamoDB
   - Computes initial GDD + weather summary
   - Triggers initial observation fetch

2. **DailyBatchFunction** (900s, 1024MB, Container)
   - Triggered by EventBridge schedule (2 AM UTC)
   - Reads all 6 DynamoDB tables
   - Calls 5 external APIs (Open-Meteo, STAC, rio-tiler, OpenET, Bedrock)
   - Computes geospatial metrics
   - Writes back to all 6 tables
   - Stores satellite previews in S3

3. **GetFieldStatusFunction** (30s, 256MB)
   - API: `GET /fields/{fieldId}/status/latest`
   - Queries `harvestai-dailystatus-dev` (latest record)
   - Returns JSON for frontend dashboard
   - Called every 60s by frontend

### External APIs

| API | Purpose | Rate Limit | Cost |
|-----|---------|-----------|------|
| **Open-Meteo** | Weather forecast & archive | Free | Free |
| **EarthSearch STAC** | Sentinel-2 L2A search | Unlimited | Free (AWS-hosted) |
| **rio-tiler** | S3 band reading via HTTP range | Unlimited | Free |
| **OpenET** | Evapotranspiration estimates | API key required | Commercial |
| **Amazon Bedrock** | Claude Haiku (text brief + vision) | On-demand | Pay-per-token |

---

## 🚀 Quick Start

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
# Deploy to Amplify or S3 + CloudFront
```

See **[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)** for detailed instructions.

---

## 📖 API Endpoints

| Method | Endpoint | Purpose | Response |
|--------|----------|---------|----------|
| POST | `/fields` | Create field | `{ fieldId, geometry, plantingDate }` |
| GET | `/fields/{fieldId}` | Get field metadata | `{ fieldId, userId, geometry, ... }` |
| GET | `/fields/{fieldId}/status/latest` | Latest daily snapshot | `{ statusDate, weather, satellite, ET, aiBrief }` |
| GET | `/fields/{fieldId}/timeseries` | Historical metrics | `[{ date, ndvi, ndmi, stress }, ...]` |
| GET | `/fields/{fieldId}/maps/latest` | Map layers & zones | `{ satellite_url, zones, stats }` |
| POST | `/fields/{fieldId}/run` | Trigger batch manually | `{ batchJobId, status }` |

Full contracts: **[docs/API_CONTRACTS.md](./docs/API_CONTRACTS.md)**

---

## 📁 Project Structure

```
HarvestAI/
├── README.md                          # This file
├── CONTRIBUTING.md                    # Developer guidelines
│
├── infrastructure/                    # CloudFormation IaC
│   ├── main.yaml                      # Root stack
│   ├── database.yaml                  # DynamoDB tables
│   ├── lambda.yaml                    # Lambda + IAM roles
│   └── networking.yaml                # API Gateway + EventBridge
│
├── backend/                           # Python Lambda functions
│   ├── requirements.txt               # Dependencies
│   ├── Dockerfile                     # Lambda container image
│   └── lambda_functions/
│       ├── field_onboarding/handler.py    # POST /fields
│       ├── daily_batch/handler.py         # Batch orchestration
│       ├── ingestion/
│       │   ├── weather.py                 # Open-Meteo integration
│       │   ├── satellite.py               # STAC + rio-tiler
│       │   ├── et.py                      # OpenET integration
│       │   ├── soil.py                    # Soil characteristics
│       │   └── bedrock_brief.py           # Claude AI brief
│       └── shared/
│           ├── metrics.py                 # NDVI, NDMI, NDRE, CIre
│           └── __init__.py
│
├── frontend/                          # React + Vite web app
│   ├── package.json
│   ├── vite.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── LandingPage.jsx        # Home / Feature overview
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

## 🔐 Security & Compliance

- ✅ **Secrets Management**: API keys stored in AWS Secrets Manager, never in code
- ✅ **IAM Least Privilege**: Lambda functions have minimal required permissions
- ✅ **Network Isolation**: Lambda runs in VPC (no public internet access)
- ✅ **Encryption**: DynamoDB encrypted at rest, HTTPS for all APIs
- ✅ **Audit Logging**: CloudWatch Logs + EventBridge audit trail
- ✅ **Pre-Commit Hooks**: Secrets detection before code push
- ✅ **Code Scanning**: Automated security & dependency checks (GitHub Actions)

---

## 💰 Cost Estimation (Monthly, US-EAST-1)

| Component | Estimate | Notes |
|-----------|----------|-------|
| **Lambda** | $2–5 | ~86k invocations (daily batch + APIs) |
| **DynamoDB** | $5–15 | On-demand billing, TTL cleanup |
| **S3** | $1–3 | Satellite previews + logs |
| **API Gateway** | $3–5 | ~1M requests/month |
| **Data Transfer** | $0–2 | Minimal outbound |
| **Bedrock** | $0.50–3 | Claude Haiku pricing (~100k tokens/day) |
| **Total** | **$11.50–33** | Scales linearly with fields |

---

## 📈 Roadmap

### ✅ Phase 1: MVP (Completed)
- Infrastructure (CloudFormation, DynamoDB, Lambda)
- Field onboarding API
- Frontend dashboard skeleton
- Documentation

### 🚀 Phase 2: Data Ingestion (In Progress)
- Weather data (Open-Meteo)
- Satellite ingestion (Sentinel-2 STAC)
- Evapotranspiration (OpenET)
- Metric computation (NDVI, NDMI, NDRE)

### 🎯 Phase 3: AI & Insights (Next)
- Bedrock integration (Claude AI brief)
- Anomaly detection (stress, disease signals)
- Recommendations (irrigation timing, scouting zones)
- Multi-year trend analysis

### 🌐 Phase 4: Scale & Polish (Future)
- Authentication (Cognito)
- Mobile app (React Native)
- Advanced visualizations (Mapbox, Recharts)
- Multi-tenant SaaS deployment
- Customer support & onboarding

---

## 🤝 Contributing

See **[CONTRIBUTING.md](./CONTRIBUTING.md)** for:
- Development environment setup
- Code standards (Python, JavaScript, YAML)
- Testing & validation
- Git workflow (fork → branch → PR → review → merge)
- Security considerations

---

## 📚 Documentation

- **[README.md](./README.md)** — Project overview (this file)
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** — Developer guidelines
- **[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)** — Step-by-step AWS setup
- **[docs/API_CONTRACTS.md](./docs/API_CONTRACTS.md)** — API endpoint details
- **[PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md)** — Detailed architecture & phase plan

---

## 🆘 Support

- 📧 **Issues**: Use GitHub Issues (see templates in [.github/ISSUE_TEMPLATE](./.github/ISSUE_TEMPLATE))
- 📖 **Questions**: Check documentation first, then open a Discussion
- 🐛 **Bugs**: Report with reproduction steps and CloudWatch logs

---

## 📄 License

HarvestAI is open source. See LICENSE file for terms.

---

## 🙏 Acknowledgments

Built for the **HarvestAI MVP Hackathon** on AWS.  
Powered by AWS Lambda, DynamoDB, Bedrock, and the geospatial open-source community.

---

**Status**: Phase 1 Complete ✅ | Phase 2 Data Ingestion 🚀 | Ready for Contributors 👥
