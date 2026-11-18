#!/usr/bin/env bash
# Deploys the gallery-backend development preview (S3 + DynamoDB + Lambda + API Gateway)
# and seeds base images. Run gallery-frontend/preview/deploy.sh afterwards to point the
# frontend at this API. Optionally export FACECHAIN_ENDPOINT_NAME to use a real FaceChain endpoint.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(dirname "$HERE")"
REPO="$(dirname "$BACKEND")"
cfg() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$HERE/deploy.config.json" "$1"; }
STACK="$(cfg stackName)"; FRONTEND_STACK="$(cfg frontendStackName)"; REGION="$(cfg region)"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ARTIFACTS="bgagent-dev-gallery-9685a0ff05aa-art-$ACCOUNT-$REGION"

# Frontend origin for CORS (falls back to localhost if the frontend preview isn't deployed yet)
ORIGIN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$FRONTEND_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='PreviewUrl'].OutputValue" --output text 2>/dev/null || true)"
[ -n "$ORIGIN" ] && [ "$ORIGIN" != "None" ] || ORIGIN="http://localhost:3000"

# Pillow layer (manylinux wheels for the python3.11 x86_64 Lambda runtime)
BUILD="$BACKEND/.preview-build"
if [ ! -d "$BUILD/pillow-layer/python/PIL" ]; then
  rm -rf "$BUILD/pillow-layer"
  pip3 install --quiet --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 \
    --implementation cp -t "$BUILD/pillow-layer/python" Pillow
fi

# Private artifact bucket for packaged Lambda code
if ! aws s3api head-bucket --bucket "$ARTIFACTS" --region "$REGION" 2>/dev/null; then
  aws s3api create-bucket --bucket "$ARTIFACTS" --region "$REGION" >/dev/null
  aws s3api put-public-access-block --bucket "$ARTIFACTS" --region "$REGION" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$ARTIFACTS" --region "$REGION" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
fi

aws cloudformation package --region "$REGION" --template-file "$HERE/template.yaml" \
  --s3-bucket "$ARTIFACTS" --s3-prefix backend --output-template-file "$BUILD/packaged.yaml" >/dev/null
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$BUILD/packaged.yaml" --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides "AllowedOrigin=$ORIGIN" "FaceChainEndpointName=${FACECHAIN_ENDPOINT_NAME:-}"

out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

# Make sure the latest method configuration is live on the stage
aws apigateway create-deployment --region "$REGION" --rest-api-id "$(out RestApiId)" --stage-name prod >/dev/null

uv run --quiet --no-project --with boto3 --with pillow python "$HERE/seed_base_resources.py" \
  "$REGION" "$(out DataBucketName)" "$(out BaseResourceTableName)" "$REPO/docs/images/sample.jpg"

echo "API endpoint (REACT_APP_API_ENDPOINT): $(out ApiEndpoint)"
echo "User agreement endpoint (REACT_APP_USER_AGREEMENT_ENDPOINT): $(out ApiUrl)"
