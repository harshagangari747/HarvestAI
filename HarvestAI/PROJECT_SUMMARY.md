# HarvestAI MVP - Project Summary

## Project Structure Overview

```
HarvestAI/
├── README.md                          # Main project overview
├── PROJECT_SUMMARY.md                 # This file
│
├── infrastructure/                    # AWS CloudFormation IaC
│   ├── main.yaml                      # Root stack orchestrator
│   ├── database.yaml                  # DynamoDB tables schema
│   ├── lambda.yaml                    # Lambda functions & IAM roles
│   └── networking.yaml                # API Gateway & EventBridge
│
├── backend/                           # Python Lambda functions
│   ├── requirements.txt               # Python dependencies
│   ├── Dockerfile                     # Lambda container image
│   └── lambda_functions/
│       ├── field_onboarding/
│       │   └── handler.py             # Field creation endpoint
│       ├── daily_batch/
│       │   └── handler.py             # Batch orchestration pipeline
│       └── shared/
│           └── metrics.py             # Geospatial metric utilities
│
├── frontend/                          # React.js web application
│   ├── package.json                   # NPM dependencies
│   ├── vite.config.js                 # Vite build config
│   ├── index.html                     # HTML entry point
│   ├── .env.example                   # Environment template
│   └── src/
│       ├── App.jsx                    # Main React component
│       ├── main.jsx                   # React DOM mount
│       ├── index.css                  # Global styles
│       ├── App.css                    # App styles
│       ├── api/
│       │   └── client.js              # Axios API client
│       ├── pages/
│       │   ├── LandingPage.jsx        # Home page
│       │   ├── LandingPage.css
│       │   ├── FieldSetup.jsx         # Field onboarding form
│       │   ├── FieldSetup.css
│       │   ├── FieldDashboard.jsx     # Main dashboard
│       │   └── FieldDashboard.css
│       └── components/
│           ├── Navigation.jsx          # Top nav bar
│           └── Navigation.css
│
└── docs/
    ├── DEPLOYMENT.md                  # Step-by-step AWS deployment guide
    └── API_CONTRACTS.md               # API endpoint documentation
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | React 18 + Vite | Web dashboard & field monitoring UI |
| Backend | AWS Lambda (Python 3.11) | API endpoints & batch processing |
| Database | DynamoDB | NoSQL storage for fields, observations, status |
| API | API Gateway | RESTful endpoint exposure |
| Batch | EventBridge + Lambda | Daily scheduled data ingestion |
| AI | Amazon Bedrock | LLM-powered recommendations |
| Storage | S3 | Satellite imagery & PNG previews |
| IaC | CloudFormation | Infrastructure as code |
| Container | Docker | Lambda container image |

## Key Deliverables (Phase 1)

### ✅ Infrastructure
- [x] CloudFormation templates (modular, nested stacks)
- [x] DynamoDB schema (6 tables: Fields, Observations, DailyStatus, Weather, ET, BatchLog)
- [x] Lambda execution IAM roles with least privilege
- [x] API Gateway endpoints (POST/GET /fields)
- [x] EventBridge scheduled batch trigger

### ✅ Backend
- [x] Field onboarding Lambda handler
- [x] Daily batch orchestration skeleton
- [x] Geospatial metrics utility library
- [x] Dockerfile for Lambda container
- [x] Error handling & logging

### ✅ Frontend
- [x] Landing page with feature highlights
- [x] Field setup wizard form
- [x] Field dashboard with daily metrics
- [x] Navigation component
- [x] API client (Axios)
- [x] Responsive CSS styling

### ✅ Documentation
- [x] README with quick-start guide
- [x] Deployment guide (step-by-step AWS CLI commands)
- [x] API contracts (all 6 endpoints defined)

---

## Deployment Steps

### Quick Start (5 minutes setup):

```bash
# 1. Store API keys in Secrets Manager
aws secretsmanager create-secret \
  --name harvestai/api-keys \
  --secret-string '{"openet_api_key":"YOUR_KEY",...}'

# 2. Deploy CloudFormation
aws cloudformation create-stack \
  --stack-name harvestai-mvp-dev \
  --template-body file://infrastructure/main.yaml \
  --parameters ParameterKey=APIKeySecretsArn,ParameterValue=<ARN> \
  --capabilities CAPABILITY_NAMED_IAM

# 3. Build Lambda container
cd backend
docker build -t harvestai-lambdas:latest .
# Push to ECR...

# 4. Build frontend
cd frontend
npm install && npm run build

# 5. Deploy to Amplify or S3
```

See `docs/DEPLOYMENT.md` for full instructions.

---

## DynamoDB Schema

### Fields Table
- **PK**: `fieldId` (String)
- **SK**: `userId` (String)
- **Attributes**: geometry, plantingDate, hybridRM, targetGDD, irrigationType, soilTest, soilContext, createdAt, status
- **GSI**: UserIdIndex (for listing user's fields)

### Observations Table
- **PK**: `fieldId`
- **SK**: `observationDate` (ISO 8601)
- **Attributes**: satellite data (NDVI, NDMI, NDRE), validPixelFraction, cloudCover
- **TTL**: 90 days (auto-expire old observations)

### DailyStatus Table
- **PK**: `fieldId`
- **SK**: `statusDate` (ISO 8601)
- **Attributes**: weather, satellite, ET, metrics, aiBrief, batchJobId, processedAt
- **Attributes**: health score, stress indicators, predicted maturity

### Weather History, ET History, BatchJobLog Tables
- Similar structure for caching and audit trail

---

## API Endpoints (Phase 1)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | /fields | Create field |
| GET | /fields/{fieldId} | Get field metadata |
| GET | /fields/{fieldId}/status/latest | Get latest daily status |
| GET | /fields/{fieldId}/timeseries | Get historical time series |
| GET | /fields/{fieldId}/maps/latest | Get map layers & zone stats |
| POST | /fields/{fieldId}/run | Trigger batch manually |

All endpoints return JSON. See `docs/API_CONTRACTS.md` for detailed payloads.

---

## Data Ingestion Pipeline (Phase 2+)

```
Daily Schedule (2 AM UTC via EventBridge)
│
├─ Weather Ingestion (Open-Meteo)
│  └─ Compute GDD, water balance
│
├─ Satellite Ingestion (Sentinel-2 EarthSearch STAC)
│  ├─ STAC search for latest clear image
│  ├─ Download B04, B08, B11, B05, SCL bands
│  ├─ Compute NDVI, NDMI, NDRE, CIre
│  └─ Generate PNG previews → S3
│
├─ ET Ingestion (OpenET)
│  └─ Accumulate water deficit
│
├─ Derived Metrics
│  ├─ Health score (vigor + moisture + stress)
│  ├─ Spatial variability zones
│  ├─ Phenology signals
│  └─ Risk indicators
│
├─ AI Recommendations (Bedrock)
│  ├─ Generate daily brief
│  ├─ Identify top risks
│  ├─ Suggest actions
│  └─ Scouting checklist
│
└─ Store DailyStatus → DynamoDB
```

---

## Next Steps (Phase 2)

1. **Weather Ingestion**
   - Integrate Open-Meteo API in `daily_batch/handler.py`
   - Implement GDD calculation (base 50°F, cap 86°F)
   - Cache daily weather in DynamoDB

2. **Satellite Ingestion**
   - Implement STAC search against EarthSearch
   - Download Sentinel-2 bands via `rio-tiler`
   - Compute indices using `shared/metrics.py`
   - Generate NDVI/NDMI/NDRE PNG previews

3. **ET & Water Stress**
   - Call OpenET API for field polygon
   - Implement water balance (ET vs Rain)
   - Store deficit time series

4. **Bedrock Integration**
   - Structure prompt JSON with field context
   - Invoke Claude model with Bedrock SDK
   - Parse JSON response for brief/risks/actions

5. **Frontend Enhancements**
   - Add Leaflet map for polygon drawing
   - Add Recharts for time series visualization
   - Integrate Mapbox for satellite layer display

6. **Testing & Hardening**
   - Write unit tests for metrics
   - Add error handling for API failures
   - Implement retry logic for external APIs
   - Setup CloudWatch alarms

---

## Configuration & Secrets

All sensitive data stored in AWS Secrets Manager:

```json
{
  "openet_api_key": "...",
  "nrel_api_key": "...",
  "earthdata_username": "...",
  "earthdata_password": "..."
}
```

Lambda has IAM permission to read this secret. Frontend never stores keys.

---

## Monitoring & Logging

- **CloudWatch Logs**: All Lambda functions write to `/aws/lambda/harvestai-*`
- **CloudWatch Metrics**: Custom metrics for batch duration, field count, errors
- **X-Ray**: (Optional) Distributed tracing for Lambda → DynamoDB calls
- **Alarms**: Alert on batch failures, DynamoDB throttling, Lambda errors

```bash
# View logs
aws logs tail /aws/lambda/harvestai-daily-batch-dev --follow

# Get metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=harvestai-daily-batch-dev \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average
```

---

## Cost Estimates (Monthly, US-EAST-1)

| Component | Estimate | Notes |
|-----------|----------|-------|
| Lambda | $2-5 | ~86k invocations/month (daily batch + API) |
| DynamoDB | $5-15 | On-demand billing |
| S3 | $1-3 | Satellite previews + logs |
| API Gateway | $3-5 | ~1M requests |
| Data Transfer | $0-2 | Minimal outbound |
| **Total** | **$11-30** | |

---

## Security Considerations

1. **API Gateway**: Currently open (no authentication)
   - Add Cognito authorizer for production
   - Implement API keys per user

2. **DynamoDB**: On-demand billing + TTL on old observations
   - Fine-grained IAM for Lambda execution

3. **S3**: Private bucket, no public access
   - Lambda has read/write permissions
   - Frontend gets signed URLs via API

4. **Lambda**: Container image runs in VPC-isolated environment
   - No internet access (uses NAT if needed)
   - No ability to read other fields' data

5. **Secrets**: Stored in AWS Secrets Manager (encrypted at rest)
   - Lambda retrieves only when needed
   - Keys never logged or exposed

---

## Acceptance Criteria (MVP "Done")

- [x] Public URL loads (Amplify or S3 + CloudFront)
- [x] Farmer can create a field (polygon + planting date + hybrid)
- [x] Field appears in dashboard with onboarding data
- [x] Daily status visible (placeholder metrics)
- [x] Batch job runs on schedule (EventBridge → Lambda)
- [x] CloudWatch logs show execution
- [x] README includes deployment steps + architecture
- [ ] **(Next)** Live satellite data flowing in
- [ ] **(Next)** Weather + GDD calculations working
- [ ] **(Next)** AI brief generating from Bedrock
- [ ] **(Next)** Dashboard showing real metrics

---

## Development Notes

- **Frontend**: React 18 + Vite (fast dev server, optimized build)
- **Backend**: Python 3.11 + boto3 (AWS SDK)
- **Geospatial**: rasterio + numpy for band processing
- **Containerization**: Docker build optimized for Lambda layer size (<1GB)
- **IaC**: CloudFormation (YAML) with nested stacks for modularity

---

## Contributors & Support

Built for HarvestAI MVP Hackathon on AWS.

For questions:
- See `README.md` for overview
- See `docs/DEPLOYMENT.md` for step-by-step deployment
- See `docs/API_CONTRACTS.md` for API details
- Check CloudWatch Logs for runtime errors

---

**Status**: Phase 1 Complete ✅ | Ready for Phase 2 Data Ingestion 🚀
