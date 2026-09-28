# HarvestAI - Corn Field Monitoring MVP

Real-time satellite + weather + ET monitoring with AI-driven recommendations for corn farmers.

## Tech Stack
- **Frontend:** React.js (hosted on Amplify)
- **Backend:** AWS Lambda (Python 3.11) + API Gateway
- **Database:** DynamoDB
- **Batch:** EventBridge + Lambda
- **AI:** Amazon Bedrock
- **IaC:** CloudFormation

## Project Structure
```
HarvestAI/
├── infrastructure/          # CloudFormation templates
│   ├── main.yaml           # Root stack
│   ├── networking.yaml     # API Gateway
│   ├── database.yaml       # DynamoDB tables
│   ├── lambda.yaml         # Lambda functions & IAM
│   └── parameters.json     # Deployment parameters
├── backend/
│   ├── lambda_functions/   # Python Lambda handlers
│   │   ├── field_onboarding/
│   │   ├── daily_batch/
│   │   ├── bedrock_brief/
│   │   └── shared/        # Common utilities
│   ├── requirements.txt
│   └── Dockerfile         # Container image for Lambda
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── api/
│   │   └── App.jsx
│   ├── package.json
│   └── .env.example
└── docs/
    ├── API_CONTRACTS.md
    └── ARCHITECTURE.md
```

## Quick Start

### Prerequisites
- AWS CLI v2 configured with credentials
- Docker (for Lambda container image builds)
- Node.js 18+ (for React frontend)
- Python 3.11+

### Phase 1: Deploy Infrastructure + Field Onboarding API

```bash
# 1. Deploy CloudFormation stack
aws cloudformation create-stack \
  --stack-name harvestai-mvp \
  --template-body file://infrastructure/main.yaml \
  --parameters ParameterKey=Environment,ParameterValue=dev \
  --capabilities CAPABILITY_NAMED_IAM

# 2. Wait for stack to complete
aws cloudformation wait stack-create-complete \
  --stack-name harvestai-mvp

# 3. Deploy Lambda container image
cd backend
aws ecr create-repository --repository-name harvestai-lambdas
# (then build & push)

# 4. Start React dev server
cd frontend
npm install
npm start
```

## API Endpoints (Phase 1)
- `POST /fields` - Create field
- `GET /fields/{fieldId}` - Get field metadata
- `GET /fields/{fieldId}/status/latest` - Get latest daily status

## Data Sources
- **Satellite:** Sentinel-2 L2A via EarthSearch STAC (AWS-hosted, no key)
- **Weather:** Open-Meteo API (no key)
- **ET:** OpenET (API key required)
- **Soil:** USDA NRCS SSURGO (no key)
- **AI:** Amazon Bedrock (Claude model)

## Deployment Checklist
- [ ] AWS account + credentials configured
- [ ] CloudFormation stack deployed
- [ ] Lambda container image built & pushed to ECR
- [ ] DynamoDB tables created
- [ ] API Gateway endpoints live
- [ ] React frontend deployed to Amplify
- [ ] EventBridge scheduler configured for daily batch
- [ ] Secrets Manager configured with API keys

## Development Notes
- All secrets stored in AWS Secrets Manager (never in code)
- Lambda functions run as container images for geospatial library support
- Frontend communicates via API Gateway (CORS enabled)
- DynamoDB uses on-demand billing for MVP flexibility

## Next Steps
1. Deploy Phase 1 infrastructure
2. Implement field onboarding API
3. Add weather ingestion
4. Integrate Sentinel-2 satellite data
5. Build batch orchestration
6. Add Bedrock recommendations
7. Polish React dashboard

---
Built with AWS for the HarvestAI MVP Hackathon.
