# HarvestAI Deployment Guide

## Prerequisites

- AWS Account with appropriate IAM permissions
- AWS CLI v2 configured with credentials
- Docker installed (for Lambda container images)
- Node.js 18+ (for React frontend)
- Python 3.11+ (for backend development)

## AWS CLI Setup

```bash
# Configure AWS credentials
aws configure

# Verify credentials
aws sts get-caller-identity
```

## Phase 1: Infrastructure Deployment

### 1. Create S3 Bucket for CloudFormation Templates

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
TEMPLATE_BUCKET="harvestai-templates-${ACCOUNT_ID}-${REGION}"

aws s3 mb s3://${TEMPLATE_BUCKET} --region ${REGION}
aws s3 cp infrastructure/database.yaml s3://${TEMPLATE_BUCKET}/
aws s3 cp infrastructure/lambda.yaml s3://${TEMPLATE_BUCKET}/
aws s3 cp infrastructure/networking.yaml s3://${TEMPLATE_BUCKET}/
```

### 2. Create Secrets for API Keys

Store your API keys in AWS Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name harvestai/api-keys \
  --secret-string '{
    "openet_api_key": "YOUR_OPENET_KEY",
    "nrel_api_key": "YOUR_NREL_KEY",
    "earthdata_username": "YOUR_USERNAME",
    "earthdata_password": "YOUR_PASSWORD"
  }' \
  --region ${REGION}

# Get the ARN for CloudFormation
SECRETS_ARN=$(aws secretsmanager describe-secret \
  --secret-id harvestai/api-keys \
  --query SecretMetadata.ARN \
  --output text)
```

### 3. Deploy Main CloudFormation Stack

```bash
aws cloudformation create-stack \
  --stack-name harvestai-mvp-dev \
  --template-body file://infrastructure/main.yaml \
  --parameters \
    ParameterKey=Environment,ParameterValue=dev \
    ParameterKey=ProjectName,ParameterValue=harvestai \
    ParameterKey=APIKeySecretsArn,ParameterValue=${SECRETS_ARN} \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ${REGION}

# Wait for stack creation
aws cloudformation wait stack-create-complete \
  --stack-name harvestai-mvp-dev \
  --region ${REGION}

# Check stack status
aws cloudformation describe-stacks \
  --stack-name harvestai-mvp-dev \
  --query 'Stacks[0].StackStatus' \
  --region ${REGION}
```

### 4. Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name harvestai-mvp-dev \
  --query 'Stacks[0].Outputs' \
  --region ${REGION}
```

## Phase 2: Lambda Function Deployment

### 1. Build Lambda Container Image

```bash
cd backend

# Create ECR repository
aws ecr create-repository \
  --repository-name harvestai-lambdas \
  --region ${REGION}

# Get ECR login token
aws ecr get-login-password --region ${REGION} | \
  docker login --username AWS --password-stdin \
  ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

# Build and tag image
docker build \
  -t harvestai-lambdas:latest \
  -t ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/harvestai-lambdas:latest \
  .

# Push to ECR
docker push ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/harvestai-lambdas:latest
```

### 2. Update Lambda Functions with Container Image

After deploying the CloudFormation stack, update Lambda functions to use the container image:

```bash
# Get Lambda function name from stack outputs
LAMBDA_FUNCTION=$(aws cloudformation describe-stack-resource \
  --stack-name harvestai-mvp-dev \
  --logical-resource-id DailyBatchFunction \
  --query 'StackResourceDetail.PhysicalResourceId' \
  --output text)

# Update function code
aws lambda update-function-code \
  --function-name ${LAMBDA_FUNCTION} \
  --image-uri ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/harvestai-lambdas:latest
```

## Phase 3: Frontend Deployment

### 1. Setup Frontend Environment

```bash
cd frontend

# Copy environment template
cp .env.example .env.local

# Get API Gateway endpoint from CloudFormation
API_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name harvestai-mvp-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`APIEndpoint`].OutputValue' \
  --output text \
  --region ${REGION})

# Update .env.local with API endpoint
echo "VITE_API_ENDPOINT=${API_ENDPOINT}" > .env.local
```

### 2. Build Frontend

```bash
npm install
npm run build
```

### 3. Deploy to Amplify (Optional)

```bash
# Initialize Amplify
amplify init

# Add hosting
amplify add hosting

# Publish
amplify publish
```

Or deploy manually to S3 + CloudFront:

```bash
# Create S3 bucket for frontend
FRONTEND_BUCKET="harvestai-frontend-${ACCOUNT_ID}-${REGION}"
aws s3 mb s3://${FRONTEND_BUCKET} --region ${REGION}

# Upload built files
aws s3 sync dist/ s3://${FRONTEND_BUCKET}/ \
  --delete \
  --cache-control "max-age=31536000,public" \
  --exclude "index.html"

aws s3 cp dist/index.html s3://${FRONTEND_BUCKET}/ \
  --cache-control "no-cache" \
  --content-type "text/html"
```

## Testing the Deployment

### 1. Test Field Creation API

```bash
API_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name harvestai-mvp-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`APIEndpoint`].OutputValue' \
  --output text)

curl -X POST ${API_ENDPOINT}/fields \
  -H "Content-Type: application/json" \
  -d '{
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[-93.5, 41.5], [-93.4, 41.5], [-93.4, 41.6], [-93.5, 41.6], [-93.5, 41.5]]]
    },
    "plantingDate": "2024-05-01T00:00:00Z",
    "hybridRM": 105,
    "irrigationType": "rainfed",
    "soilTest": {
      "pH": 6.5,
      "organicMatter": 3.2
    }
  }'
```

### 2. Test Batch Trigger

```bash
# Trigger batch manually
curl -X POST ${API_ENDPOINT}/fields/{fieldId}/run
```

### 3. Monitor CloudWatch Logs

```bash
aws logs tail /aws/lambda/harvestai-daily-batch-dev --follow
```

## Monitoring & Troubleshooting

### CloudWatch Logs

```bash
# View Lambda logs
aws logs tail /aws/lambda/harvestai-field-onboarding-dev --follow
aws logs tail /aws/lambda/harvestai-daily-batch-dev --follow

# View API Gateway logs
aws logs tail /aws/apigateway/harvestai-api-dev --follow
```

### DynamoDB

```bash
# List DynamoDB tables
aws dynamodb list-tables

# Scan fields table
aws dynamodb scan --table-name harvestai-fields-dev
```

### Lambda Metrics

```bash
# Get Lambda metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Duration \
  --dimensions Name=FunctionName,Value=harvestai-daily-batch-dev \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average
```

## Cost Optimization Tips

1. **Lambda**: Set appropriate timeout and memory limits
2. **DynamoDB**: Use on-demand billing for MVP; switch to provisioned for production
3. **S3**: Enable lifecycle policies to archive old satellite data
4. **CloudWatch Logs**: Set retention policies to reduce storage costs
5. **EventBridge**: Schedule batch jobs during off-peak hours if possible

## Cleanup (if needed)

```bash
# Delete CloudFormation stack (this will delete all resources)
aws cloudformation delete-stack --stack-name harvestai-mvp-dev

# Delete ECR repository
aws ecr delete-repository \
  --repository-name harvestai-lambdas \
  --force

# Delete S3 buckets
aws s3 rb s3://${TEMPLATE_BUCKET} --force
aws s3 rb s3://${FRONTEND_BUCKET} --force

# Delete Secrets Manager secret
aws secretsmanager delete-secret \
  --secret-id harvestai/api-keys \
  --force-delete-without-recovery
```

---

For more information, see the main [README.md](../README.md) and API contracts documentation.
