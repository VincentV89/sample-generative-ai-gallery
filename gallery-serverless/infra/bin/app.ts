#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { GalleryServerlessStack } from '../lib/gallery-serverless-stack';

// Development deployment configuration (see ../deploy.config.json).
// eslint-disable-next-line @typescript-eslint/no-var-requires
const deployConfig = require('../../deploy.config.json');

const app = new cdk.App();

const stackName: string = app.node.tryGetContext('stackName') ?? deployConfig.stackName;
const region: string = process.env.CDK_DEFAULT_REGION ?? deployConfig.region;

new GalleryServerlessStack(app, 'GalleryServerlessStack', {
  stackName,
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region },
  description: 'Serverless Generative AI Gallery (S3 + CloudFront + API Gateway + Lambda + DynamoDB + Amazon Bedrock)',
  textModelId: deployConfig.textModelId,
  textModelRegion: deployConfig.textModelRegion,
  imageModelId: deployConfig.imageModelId,
  imageModelRegion: deployConfig.imageModelRegion,
  photoModelId: deployConfig.photoModelId,
  photoModelRegion: deployConfig.photoModelRegion,
  faceSwap: deployConfig.faceSwap?.enabled ? {
    modelArtifactPath: deployConfig.faceSwap.modelArtifactPath,
    imageUri: deployConfig.faceSwap.imageUri,
    instanceType: deployConfig.faceSwap.instanceType,
  } : undefined,
});
