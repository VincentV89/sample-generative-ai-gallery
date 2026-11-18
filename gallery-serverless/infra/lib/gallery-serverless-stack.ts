import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';

export interface GalleryServerlessStackProps extends cdk.StackProps {
  /** Bedrock text model / inference profile used as the "art director" (e.g. global.anthropic.claude-opus-5-5). */
  readonly textModelId: string;
  readonly textModelRegion: string;
  /** Bedrock image model used as the "painter" (e.g. stability.stable-image-ultra-v1:1). */
  readonly imageModelId: string;
  readonly imageModelRegion: string;
  /** Bedrock photo-to-portrait model / inference profile (e.g. us.stability.stable-image-control-structure-v1:0). */
  readonly photoModelId: string;
  readonly photoModelRegion: string;
}

export class GalleryServerlessStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: GalleryServerlessStackProps) {
    super(scope, id, props);

    // ---------- Storage ----------
    const bucketDefaults: s3.BucketProps = {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // development preview
      autoDeleteObjects: true,
    };

    // Bucket names include account + region so they are globally unique.
    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      ...bucketDefaults,
      bucketName: `genai-gallery-site-${this.account}-${this.region}`,
    });
    const imageBucket = new s3.Bucket(this, 'ImageBucket', {
      ...bucketDefaults,
      bucketName: `genai-gallery-images-${this.account}-${this.region}`,
      // Visitor photos (uploads/) are private (not routed by CloudFront) and deleted by the
      // worker once a job finishes; this rule is the backstop.
      lifecycleRules: [{ id: 'ExpireVisitorUploads', prefix: 'uploads/', expiration: cdk.Duration.days(1) }],
    });

    const table = new dynamodb.Table(this, 'PortraitTable', {
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'ttl',
    });
    // Completed portraits are indexed for the public gallery wall (newest first).
    table.addGlobalSecondaryIndex({
      indexName: 'gallery',
      partitionKey: { name: 'galleryPk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
    });

    // ---------- Compute ----------
    const code = lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'lambda'));
    const commonEnv = {
      TABLE_NAME: table.tableName,
      IMAGE_BUCKET: imageBucket.bucketName,
      TEXT_MODEL_ID: props.textModelId,
      TEXT_MODEL_REGION: props.textModelRegion,
      IMAGE_MODEL_ID: props.imageModelId,
      IMAGE_MODEL_REGION: props.imageModelRegion,
      PHOTO_MODEL_ID: props.photoModelId,
      PHOTO_MODEL_REGION: props.photoModelRegion,
    };

    const worker = new lambda.Function(this, 'WorkerFunction', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'worker.handler',
      code,
      memorySize: 512,
      timeout: cdk.Duration.minutes(3),
      // Cost guard-rail for a public demo: at most N portraits painted at once.
      reservedConcurrentExecutions: 5,
      environment: commonEnv,
      logGroup: new logs.LogGroup(this, 'WorkerLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });
    worker.configureAsyncInvoke({ retryAttempts: 0, maxEventAge: cdk.Duration.minutes(10) });

    const api = new lambda.Function(this, 'ApiFunction', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'api.handler',
      code,
      memorySize: 512,
      timeout: cdk.Duration.seconds(15),
      environment: { ...commonEnv, WORKER_FUNCTION_NAME: worker.functionName },
      logGroup: new logs.LogGroup(this, 'ApiLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    table.grantReadWriteData(api);
    table.grantReadWriteData(worker);
    imageBucket.grantPut(worker, 'gallery/*');
    imageBucket.grantRead(worker, 'uploads/*');
    imageBucket.grantDelete(worker, 'uploads/*');
    imageBucket.grantPut(api, 'uploads/*');
    worker.grantInvoke(api);

    // Bedrock access: cross-region (global) inference profile for Claude + Stability image model.
    const textFoundationModel = props.textModelId.replace(/^(global|us|eu|apac)\./, '');
    const photoFoundationModel = props.photoModelId.replace(/^(global|us|eu|apac)\./, '');
    worker.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: [
        `arn:aws:bedrock:*:${this.account}:inference-profile/${props.textModelId}`,
        `arn:aws:bedrock:*::foundation-model/${textFoundationModel}`,
        `arn:aws:bedrock:::foundation-model/${textFoundationModel}`,
        `arn:aws:bedrock:${props.imageModelRegion}::foundation-model/${props.imageModelId}`,
        // Photo model: cross-region inference profile routes to any US region.
        `arn:aws:bedrock:${props.photoModelRegion}:${this.account}:inference-profile/${props.photoModelId}`,
        `arn:aws:bedrock:*::foundation-model/${photoFoundationModel}`,
      ],
    }));

    // ---------- API ----------
    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: `${this.stackName}-api`,
      createDefaultStage: false,
    });
    new apigwv2.HttpStage(this, 'DefaultStage', {
      httpApi,
      stageName: '$default',
      autoDeploy: true,
      // Throttle the public API to keep Bedrock spend predictable.
      throttle: { rateLimit: 5, burstLimit: 10 },
    });
    const integration = new HttpLambdaIntegration('ApiIntegration', api);
    httpApi.addRoutes({ path: '/api/options', methods: [apigwv2.HttpMethod.GET], integration });
    httpApi.addRoutes({ path: '/api/gallery', methods: [apigwv2.HttpMethod.GET], integration });
    httpApi.addRoutes({ path: '/api/portraits', methods: [apigwv2.HttpMethod.POST], integration });
    httpApi.addRoutes({ path: '/api/portraits/{id}', methods: [apigwv2.HttpMethod.GET], integration });

    // ---------- CDN ----------
    const apiDomain = cdk.Fn.select(2, cdk.Fn.split('/', httpApi.apiEndpoint));
    const securityHeaders = new cloudfront.ResponseHeadersPolicy(this, 'SecurityHeaders', {
      securityHeadersBehavior: {
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: cloudfront.HeadersFrameOption.DENY, override: true },
        referrerPolicy: { referrerPolicy: cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN, override: true },
        strictTransportSecurity: { accessControlMaxAge: cdk.Duration.days(365), includeSubdomains: true, override: true },
        contentSecurityPolicy: {
          contentSecurityPolicy: "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
          override: true,
        },
      },
    });

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `${this.stackName} gen AI gallery`,
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        responseHeadersPolicy: securityHeaders,
        compress: true,
      },
      additionalBehaviors: {
        '/gallery/*': {
          origin: origins.S3BucketOrigin.withOriginAccessControl(imageBucket),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          responseHeadersPolicy: securityHeaders,
        },
        '/api/*': {
          origin: new origins.HttpOrigin(apiDomain, { readTimeout: cdk.Duration.seconds(30) }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
          responseHeadersPolicy: securityHeaders,
        },
      },
    });

    new s3deploy.BucketDeployment(this, 'DeploySite', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '..', '..', 'web'))],
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ['/*'],
      memoryLimit: 256,
    });

    new cdk.CfnOutput(this, 'GalleryUrl', { value: `https://${distribution.distributionDomainName}` });
    new cdk.CfnOutput(this, 'DistributionId', { value: distribution.distributionId });
    new cdk.CfnOutput(this, 'ApiEndpoint', { value: httpApi.apiEndpoint });
    new cdk.CfnOutput(this, 'ImageBucketName', { value: imageBucket.bucketName });
    new cdk.CfnOutput(this, 'SiteBucketName', { value: siteBucket.bucketName });
  }
}
