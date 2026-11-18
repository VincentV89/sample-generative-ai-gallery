#!/usr/bin/env bash
# Deploys the serverless gallery development preview.
# Stack name / region / models are read from deploy.config.json.
set -euo pipefail
cd "$(dirname "$0")"

STACK_NAME=$(node -p "require('./deploy.config.json').stackName")
REGION=${REGION:-$(node -p "require('./deploy.config.json').region")}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "Deploying ${STACK_NAME} to account ${ACCOUNT} / ${REGION}"

# Some runtimes provide credentials via a provider only the AWS CLI understands;
# hand the CLI's current session credentials to the CDK process (never printed).
if [[ -z "${AWS_ACCESS_KEY_ID:-}" && -z "${AWS_PROFILE:-}" ]]; then
  eval "$(aws configure export-credentials --format env 2>/dev/null || true)"
fi

export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION" CDK_DEFAULT_REGION="$REGION" CDK_DEFAULT_ACCOUNT="$ACCOUNT"

cd infra
npm install --no-audit --no-fund
npx tsc
npx cdk deploy --all --require-approval never --outputs-file ../cdk-outputs.json

URL=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='GalleryUrl'].OutputValue" --output text)
echo "Gallery URL: ${URL}"
