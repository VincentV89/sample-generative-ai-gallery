# Gallery Backend

This project uses AWS CDK to construct the gallery backend infrastructure for an image processing application.

## Project Structure

```
.
├── app.py                  # Main CDK application entry point
├── byoc                    # Bring Your Own Container resources
│   └── facechain           # FaceChain model container resources
├── lambda                  # Lambda function source code
│   ├── apis                # API handler functions
│   ├── facechain_codebuild # FaceChain build functions
│   └── image-processing    # Image processing functions
└── stacks                  # CDK stack definitions
    ├── apigateway          # API Gateway stack
    ├── byoc                # BYOC stack
    ├── cognito             # Cognito user authentication stack
    ├── ddb                 # DynamoDB tables stack
    ├── facechain           # FaceChain model stack
    ├── lambdas             # Lambda functions stack
    └── s3                  # S3 bucket stack
```

## Stacks

The project consists of the following stacks:

### 1. BYOC (Bring Your Own Container) Stacks
- Infrastructure for container management and deployment
- Key components:
  - FaceChain ECR Stack: Container registry for FaceChain model
  - FaceChain CodeBuild Stack: Build pipeline for FaceChain container

### 2. FaceChain Stacks
- Infrastructure for FaceChain model deployment and management
- Key components:
  - SageMaker Endpoint Stack: Model deployment endpoint
  - CodeBuild Trigger Stack: Automated build triggers
  - CodeBuild Status Checker Stack: Build status monitoring

### 3. API Gateway Stacks
- REST API endpoint management and configuration
- Key components:
  - Image Upload API (/apis/images/upload)
  - Image Retrieval API (/apis/images/{userId})
  - User Agreement API (/agree)
  - CORS configuration and permission management
  - Lambda integration

### 4. Cognito Stacks
- User authentication and authorization management
- Key components:
  - User Pool configuration
  - Client application settings
  - Domain configuration

### 5. DynamoDB Stacks
- Data storage management
- Key tables:
  - Process Table: Image processing status management
  - Display Table: Image display information management
  - Display History Table: Image display history tracking
  - Base Resource Table: Base resource information storage
  - User Agreement Table: User consent information management

### 6. Lambda Stacks
- Serverless function management
- Key functions:
  - Image Processing Lambdas:
    - Face Crop Lambda: Face image cropping processing
    - Face Swap Lambda: Face swapping processing
    - Face Swap Completion Lambda: Face swap completion handling
  - S3 event-based automated processing configuration

### 7. S3 Stacks
- Object storage management
- Key features:
  - Image storage configuration
  - CORS settings
  - Bucket policy management
  - Event notification setup

## Deployment Prerequisites

Before deploying this application:

1. Configure the `s3_base_bucket_name` in your `cdk.context.json` file:
   ```json
   {
     "s3_base_bucket_name": "your-unique-bucket-name"
   }
   ```

2. It is recommended to deploy this application in the **us-west-2** region for optimal performance and compatibility.

## Useful commands

 * `cdk ls`          list all stacks in the app
 * `cdk synth`       emits the synthesized CloudFormation template
 * `cdk deploy`      deploy this stack to your default AWS account/region
 * `cdk diff`        compare deployed stack with current state
 * `cdk docs`        open CDK documentation

## How to deploy

This project is set up like a standard Python project. The initialization
process also creates a virtualenv within this project, stored under the `.venv`
directory.  To create the virtualenv it assumes that there is a `python3`
(or `python` for Windows) executable in your path with access to the `venv`
package. If for any reason the automatic creation of the virtualenv fails,
you can create the virtualenv manually.

To manually create a virtualenv on MacOS and Linux:

```
$ python3 -m venv .venv
```

After the init process completes and the virtualenv is created, you can use the following
step to activate your virtualenv.

```
$ source .venv/bin/activate
```

If you are a Windows platform, you would activate the virtualenv like this:

```
% .venv\Scripts\activate.bat
```

Once the virtualenv is activated, you can install the required dependencies.

```
$ pip install -r requirements.txt
```

At this point you can now synthesize the CloudFormation template for this code.

```
$ cdk synth
```

To add additional dependencies, for example other CDK libraries, just add
them to your `setup.py` file and rerun the `pip install -r requirements.txt`
command.

## Development preview

`preview/` deploys a self-contained development copy of the backend with plain CloudFormation
(no CDK bootstrap needed):

- `template.yaml` – private S3 data bucket (with S3 → Lambda notifications), DynamoDB tables, the
  upload/get-image/user-agreement Lambdas behind API Gateway (`/apis/images/upload`,
  `/apis/images/{userId}`, `/agree`), and the face-crop → face-swap → completion pipeline
- `deploy.config.json` – stack name and region (`us-east-1`)
- `deploy.sh` – builds a Pillow layer, packages the Lambdas, deploys the stack and seeds base
  images (sliced from `docs/images/sample.jpg`) for the `ancient_rome` theme and every skin tone
- `seed_base_resources.py` – the seeding script used by `deploy.sh`

```bash
./gallery-backend/preview/deploy.sh      # backend first
./gallery-frontend/preview/deploy.sh     # frontend picks up the API endpoints from the backend stack
```

### FaceChain GPU endpoint

`preview/facechain.yaml` + `preview/deploy_facechain.sh` deploy the real face swap model
(mirroring `stacks/byoc` and `stacks/facechain`):

- an ECR repository and a CodeBuild project that builds `byoc/facechain` (the ModelScope
  `damo/cv_unet_face_fusion_torch` weights are baked into the image at build time)
- a SageMaker real-time endpoint `bgagent-dev-gallery-9685a0ff05aa-facechain` on one `ml.g4dn.xlarge`

```bash
./gallery-backend/preview/deploy_facechain.sh   # after deploy.sh; ~45-75 min the first time
```

The script tags the image with a hash of `byoc/facechain`, so a rerun with unchanged sources skips
the build. It then redeploys the backend so the face-swap Lambda invokes the endpoint (`deploy.sh`
also picks the endpoint up automatically from the facechain stack). The endpoint reads the cropped
face and base image from the data bucket and writes `result-image/…`, which triggers the existing
completion Lambda and shows up on the display page.

End-to-end check (same API calls as the frontend; fails if the composite fallback was used):

```bash
uv run --no-project --with boto3 --with pillow python gallery-backend/preview/e2e_facechain.py \
  us-east-1 <ApiEndpoint> face.jpg <face-swap Lambda name> result.jpg
```

If no endpoint is deployed, or an invocation fails, the face-swap Lambda writes a Pillow composite
(the user's cropped face framed on the base portrait) so the upload → display flow still completes;
failures are logged as `ERROR: FaceChain endpoint …` in the face-swap Lambda logs.

The GPU endpoint bills per hour while it is InService. To stop the cost, delete only the endpoint
by deploying the facechain stack with an empty `ImageTag`:

```bash
aws cloudformation deploy --region us-east-1 \
  --stack-name bgagent-dev-vincentv89-sample-generative-ai-gallery-9685a0ff05aa-facechain \
  --template-file gallery-backend/preview/facechain.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides ImageTag= DataBucketName=<data bucket> SourceBucketName=<artifact bucket>
./gallery-backend/preview/deploy.sh   # back to the composite
```
