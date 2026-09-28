#!/usr/bin/env bash
# =============================================================================
# HarvestAI — Secrets Manager Setup Script
#
# Stores all third-party API keys in a single AWS Secrets Manager secret.
# Run this BEFORE deploying the main CloudFormation stack.
#
# Usage:
#   chmod +x scripts/setup_secrets.sh
#   ./scripts/setup_secrets.sh
#
# The script will:
#   1. Prompt for each API key (input is hidden)
#   2. Create (or update) the secret in Secrets Manager
#   3. Print the secret ARN — copy it as APIKeySecretsArn when deploying main.yaml
#
# Required: AWS CLI v2 configured with valid credentials
#           aws sts get-caller-identity   ← verify this works first
# =============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_NAME="${PROJECT_NAME:-harvestai}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
REGION="${AWS_REGION:-us-east-1}"
SECRET_NAME="${PROJECT_NAME}/api-keys/${ENVIRONMENT}"

# ── Helpers ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

read_secret() {
    local prompt="$1"
    local varname="$2"
    local default="${3:-}"
    echo -n "${prompt}"
    read -rs val
    echo
    if [[ -z "$val" && -n "$default" ]]; then
        eval "$varname='$default'"
        warn "Using placeholder for this key — replace it later with: aws secretsmanager update-secret ..."
    else
        eval "$varname='$val'"
    fi
}

# ── Check AWS credentials ──────────────────────────────────────────────────────
info "Checking AWS credentials..."
CALLER=$(aws sts get-caller-identity --output json 2>/dev/null) \
    || error "AWS CLI not configured. Run: aws configure"

ACCOUNT_ID=$(echo "$CALLER" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
success "Authenticated as account $ACCOUNT_ID in region $REGION"
echo

# ── Banner ─────────────────────────────────────────────────────────────────────
echo "============================================================"
echo "  HarvestAI Secrets Setup"
echo "  Secret: $SECRET_NAME"
echo "  Region: $REGION"
echo "============================================================"
echo
echo "Enter each API key when prompted. Input is hidden."
echo "Press Enter to skip optional keys (stored as PLACEHOLDER)."
echo

# ── Collect API keys ───────────────────────────────────────────────────────────

# 1. OpenET — REQUIRED for ET data
echo -e "${YELLOW}1/5  OpenET API Key${NC}"
echo "     Get yours at: https://openetdata.org/developers"
read_secret "     OpenET API key (required): " OPENET_KEY ""

# 2. NREL NSRDB — OPTIONAL for high-quality solar radiation
echo
echo -e "${YELLOW}2/5  NREL NSRDB API Key${NC} (optional — used for solar radiation)"
echo "     Get yours at: https://developer.nrel.gov/signup/"
read_secret "     NREL API key (press Enter to skip): " NREL_KEY "PLACEHOLDER"

# 3. NASA Earthdata username — OPTIONAL for Sentinel-1 / SMAP
echo
echo -e "${YELLOW}3/5  NASA Earthdata Username${NC} (optional — for Sentinel-1 via ASF)"
echo "     Register at: https://urs.earthdata.nasa.gov/users/new"
read_secret "     Earthdata username (press Enter to skip): " EARTHDATA_USER "PLACEHOLDER"

# 4. NASA Earthdata password
if [[ "$EARTHDATA_USER" != "PLACEHOLDER" ]]; then
    echo
    read_secret "     Earthdata password: " EARTHDATA_PASS ""
else
    EARTHDATA_PASS="PLACEHOLDER"
fi

# 5. USDA NASS QuickStats — OPTIONAL for county yield benchmarks
echo
echo -e "${YELLOW}5/5  USDA NASS QuickStats API Key${NC} (optional — for yield benchmarks)"
echo "     Get yours at: https://quickstats.nass.usda.gov/api"
read_secret "     NASS API key (press Enter to skip): " NASS_KEY "PLACEHOLDER"

# ── Build secret JSON ──────────────────────────────────────────────────────────
SECRET_JSON=$(python3 -c "
import json, sys
keys = {
    'openet_api_key':      sys.argv[1],
    'nrel_api_key':        sys.argv[2],
    'earthdata_username':  sys.argv[3],
    'earthdata_password':  sys.argv[4],
    'nass_api_key':        sys.argv[5],
}
print(json.dumps(keys))
" "$OPENET_KEY" "$NREL_KEY" "$EARTHDATA_USER" "$EARTHDATA_PASS" "$NASS_KEY")

echo
info "Storing secret in Secrets Manager..."

# ── Create or update the secret ────────────────────────────────────────────────
EXISTING_ARN=$(aws secretsmanager describe-secret \
    --secret-id "$SECRET_NAME" \
    --region "$REGION" \
    --query 'ARN' \
    --output text 2>/dev/null || echo "")

if [[ -n "$EXISTING_ARN" && "$EXISTING_ARN" != "None" ]]; then
    warn "Secret already exists — updating existing secret values."
    aws secretsmanager update-secret \
        --secret-id "$SECRET_NAME" \
        --secret-string "$SECRET_JSON" \
        --region "$REGION" \
        --output json > /dev/null
    SECRET_ARN="$EXISTING_ARN"
    success "Secret updated: $SECRET_ARN"
else
    OUTPUT=$(aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "HarvestAI third-party API keys for ${ENVIRONMENT}" \
        --secret-string "$SECRET_JSON" \
        --region "$REGION" \
        --output json)
    SECRET_ARN=$(echo "$OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['ARN'])")
    success "Secret created: $SECRET_ARN"
fi

# ── Print final instructions ───────────────────────────────────────────────────
echo
echo "============================================================"
echo -e "${GREEN}  ✓ Secrets stored successfully!${NC}"
echo "============================================================"
echo
echo "Secret ARN:"
echo -e "  ${CYAN}${SECRET_ARN}${NC}"
echo
echo "Next step — deploy the main CloudFormation stack:"
echo
echo "  # 1. Upload nested templates to S3"
echo "  ACCOUNT_ID=\$(aws sts get-caller-identity --query Account --output text)"
echo "  BUCKET=\"${PROJECT_NAME}-cfn-templates-\${ACCOUNT_ID}-${ENVIRONMENT}\""
echo "  aws s3 mb s3://\${BUCKET} --region ${REGION}"
echo "  aws s3 cp infrastructure/database.yaml   s3://\${BUCKET}/"
echo "  aws s3 cp infrastructure/lambda.yaml      s3://\${BUCKET}/"
echo "  aws s3 cp infrastructure/networking.yaml  s3://\${BUCKET}/"
echo
echo "  # 2. Deploy main stack"
echo "  aws cloudformation create-stack \\"
echo "    --stack-name ${PROJECT_NAME}-mvp-${ENVIRONMENT} \\"
echo "    --template-body file://infrastructure/main.yaml \\"
echo "    --parameters \\"
echo "      ParameterKey=Environment,ParameterValue=${ENVIRONMENT} \\"
echo "      ParameterKey=ProjectName,ParameterValue=${PROJECT_NAME} \\"
echo -e "      ParameterKey=APIKeySecretsArn,ParameterValue=${CYAN}${SECRET_ARN}${NC} \\"
echo "    --capabilities CAPABILITY_NAMED_IAM \\"
echo "    --region ${REGION}"
echo
echo "  # 3. Watch progress"
echo "  aws cloudformation wait stack-create-complete \\"
echo "    --stack-name ${PROJECT_NAME}-mvp-${ENVIRONMENT} \\"
echo "    --region ${REGION}"
echo
echo "  # 4. Get API endpoint"
echo "  aws cloudformation describe-stacks \\"
echo "    --stack-name ${PROJECT_NAME}-mvp-${ENVIRONMENT} \\"
echo "    --query 'Stacks[0].Outputs[?OutputKey==\`APIEndpoint\`].OutputValue' \\"
echo "    --output text --region ${REGION}"
echo
echo "============================================================"

# ── Save ARN to .env.deploy for convenience ────────────────────────────────────
cat > .env.deploy <<EOF
# Auto-generated by scripts/setup_secrets.sh — DO NOT COMMIT
PROJECT_NAME=${PROJECT_NAME}
ENVIRONMENT=${ENVIRONMENT}
REGION=${REGION}
SECRETS_ARN=${SECRET_ARN}
ACCOUNT_ID=${ACCOUNT_ID}
EOF
success ".env.deploy written with deployment variables (gitignored)"
