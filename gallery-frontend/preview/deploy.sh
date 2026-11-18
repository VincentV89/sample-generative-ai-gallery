#!/usr/bin/env bash
# Deploys the gallery-frontend development preview (S3 + CloudFront OAC + Cognito).
# Usage: ./deploy.sh
# API endpoints come from the gallery-backend preview stack (../../gallery-backend/preview) when it exists;
# exporting REACT_APP_API_ENDPOINT / REACT_APP_USER_AGREEMENT_ENDPOINT overrides them.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$(dirname "$HERE")"
STACK="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["stackName"])' "$HERE/deploy.config.json")"
REGION="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["region"])' "$HERE/deploy.config.json")"

aws sts get-caller-identity --query Account --output text >/dev/null

aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file "$HERE/template.yaml" --no-fail-on-empty-changeset

out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET="$(out BucketName)"; DIST="$(out DistributionId)"; URL="$(out PreviewUrl)"

BACKEND_STACK="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["stackName"])' "$(dirname "$FRONTEND")/gallery-backend/preview/deploy.config.json")"
bout() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$BACKEND_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text 2>/dev/null || true; }
export REACT_APP_API_ENDPOINT="${REACT_APP_API_ENDPOINT:-$(bout ApiEndpoint)}"
export REACT_APP_USER_AGREEMENT_ENDPOINT="${REACT_APP_USER_AGREEMENT_ENDPOINT:-$(bout ApiUrl)}"
echo "API endpoint: ${REACT_APP_API_ENDPOINT:-<none>}"

cd "$FRONTEND"
[ -d node_modules ] || npm install --no-audit --no-fund
REACT_APP_COGNITO_USER_POOL_ID="$(out UserPoolId)" \
REACT_APP_COGNITO_CLIENT_ID="$(out UserPoolClientId)" \
CI=false npx react-scripts build

aws s3 sync build/ "s3://$BUCKET/" --region "$REGION" --delete \
  --exclude index.html --cache-control "public,max-age=31536000,immutable"
aws s3 cp build/index.html "s3://$BUCKET/index.html" --region "$REGION" \
  --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" >/dev/null

echo "Preview URL: $URL"
