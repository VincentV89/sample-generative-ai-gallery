#!/usr/bin/env bash
# Deploys the FaceChain GPU endpoint for the gallery development preview:
#   1. zips byoc/facechain and uploads it to the private artifact bucket
#   2. deploys the facechain stack (ECR repo + CodeBuild project) without the endpoint
#   3. builds/pushes the image with CodeBuild (skipped when the source is unchanged)
#   4. redeploys the stack with ImageTag set -> SageMaker model, endpoint config, endpoint
#   5. redeploys the backend preview with FACECHAIN_ENDPOINT_NAME so face-swap calls the endpoint
# Run after preview/deploy.sh (the data bucket and artifact bucket must exist).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$(dirname "$HERE")"
cfg() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$HERE/deploy.config.json" "$1"; }
STACK="$(cfg stackName)"; FC_STACK="$(cfg facechainStackName)"; REGION="$(cfg region)"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ARTIFACTS="bgagent-dev-gallery-9685a0ff05aa-art-$ACCOUNT-$REGION"
DATA_BUCKET="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" --output text)"

# 1. Build context, tagged by its content hash so unchanged sources reuse the existing image
BUILD="$BACKEND/.preview-build"; mkdir -p "$BUILD"
rm -f "$BUILD/facechain-source.zip"
(cd "$BACKEND/byoc/facechain" && chmod +x src/serve && zip -qrX "$BUILD/facechain-source.zip" Dockerfile src)
TAG="src-$(cd "$BACKEND/byoc/facechain" && find Dockerfile src -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)"
aws s3 cp --quiet --region "$REGION" "$BUILD/facechain-source.zip" "s3://$ARTIFACTS/facechain/source.zip"

deploy_fc() {
  aws cloudformation deploy --region "$REGION" --stack-name "$FC_STACK" \
    --template-file "$HERE/facechain.yaml" --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides "DataBucketName=$DATA_BUCKET" "SourceBucketName=$ARTIFACTS" "ImageTag=$1"
}
fc_out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$FC_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

# 2. Repository + build project (keep the currently deployed image tag, if any)
CURRENT_TAG="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$FC_STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='ImageTag'].ParameterValue" --output text 2>/dev/null || true)"
[ "$CURRENT_TAG" != "None" ] || CURRENT_TAG=""
deploy_fc "$CURRENT_TAG"
REPO_NAME="$(fc_out RepositoryUri | cut -d/ -f2)"

# 3. Image build
if aws ecr describe-images --region "$REGION" --repository-name "$REPO_NAME" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
  echo "Image $TAG already built"
else
  BUILD_ID="$(aws codebuild start-build --region "$REGION" --project-name "$(fc_out BuildProjectName)" \
    --environment-variables-override "name=IMAGE_TAG_OUT,value=$TAG,type=PLAINTEXT" --query build.id --output text)"
  echo "Building FaceChain image ($BUILD_ID), this takes ~30-60 minutes..."
  while :; do
    STATUS="$(aws codebuild batch-get-builds --region "$REGION" --ids "$BUILD_ID" --query 'builds[0].buildStatus' --output text)"
    [ "$STATUS" = "IN_PROGRESS" ] || break
    sleep 60
  done
  [ "$STATUS" = "SUCCEEDED" ] || { echo "CodeBuild $BUILD_ID finished with $STATUS" >&2; exit 1; }
fi

# 4. SageMaker endpoint (CloudFormation waits until it is InService)
deploy_fc "$TAG"
ENDPOINT="$(fc_out EndpointName)"
echo "FaceChain endpoint: $ENDPOINT"

# 5. Point the backend face-swap Lambda at the endpoint
FACECHAIN_ENDPOINT_NAME="$ENDPOINT" "$HERE/deploy.sh"
