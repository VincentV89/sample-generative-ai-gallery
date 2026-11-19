# Gallery Serverless: Time-Travel Portrait Studio

A fully serverless version of the generative AI gallery, built for events:

- **Gallery display** (`#/display`): a full-screen kiosk page for a (portrait) screen. It cycles through the newest portraits with their title and story, shows new arrivals as soon as they are finished, and has a **QR code** that opens the create page.
- **Create page** (`#/create`, the default page, mobile-first): visitors **take a selfie or upload a picture**, then choose an era, a role, an art style and a likeness level, and can add an optional twist. They must agree to the consent box before a photo is used.

How a portrait is made:

1. In the browser, the photo is cropped to 2:3, resized to about 1 MP and re-encoded as JPEG, which also strips EXIF and location data.
2. **Claude Opus 5.5** (`global.anthropic.claude-opus-5-5`) acts as the *art director*. It looks at the photo and describes the sitter's visible features (hair, glasses, expression, pose) without identifying them. It then invents the character, backstory, title, caption and palette, and writes the image prompt. It also screens unsafe photos and ideas, including prompt-injection attempts.
3. The *painter*: **Stable Image Ultra** (`stability.stable-image-ultra-v1:1`, from `us-west-2`) paints the character from Claude's prompt.
4. The *face swap* (photo only): **[AlphaFace](https://github.com/andrewyu90/Alphaface_Official)** runs on an **Amazon SageMaker real-time endpoint** (`ml.g4dn.xlarge`, PyTorch DLC). It places the visitor's face into the painting. AlphaFace is a real-time GAN face swapper that handles different head poses (Yu et al., 2026, [arXiv:2601.16429](https://arxiv.org/abs/2601.16429), MIT). The endpoint:
   1. detects faces with OpenCV YuNet,
   2. FFHQ-aligns the faces from 5 landmarks,
   3. swaps the 256 px face crop (ArcFace R50 identity),
   4. gently colour-matches the face to the painting and composites it with a landmark-fitted mask, an opaque centre, and separate lighting/detail blending at the edges.

   The likeness setting (Artistic / Balanced / Faithful) maps to a swap blend of 0.85 / 0.98 / 1.0. Faithful is the default. The art direction preserves hairstyle, facial hair, expression and pose from the source photo.
   - **Fallback:** if the endpoint finds no usable face (or is unavailable), the photo is repainted with **Stable Image Control Structure** (`us.stability.stable-image-control-structure-v1:0`, `control_strength` 0.45 / 0.6 / 0.75). Set `faceSwap.enabled: false` in `deploy.config.json` to skip SageMaker completely.
5. The portrait goes up on the gallery and the display. The visitor's original photo is deleted as soon as the job finishes, and an S3 lifecycle rule on `uploads/` (1 day) is the backstop.

## Architecture

```
Browser ──► CloudFront ──┬─ /*          ──► S3 (site, private, OAC)
                         ├─ /gallery/*  ──► S3 (images, private, OAC)
                         └─ /api/*      ──► API Gateway HTTP API ──► Lambda (api.py)
                                                                       │ async invoke
                                                                       ▼
                                   DynamoDB ◄── Lambda (worker.py) ──► Bedrock: Claude Opus 5.5
                                                         │             Bedrock: Stable Image Ultra
                                                         │             SageMaker: AlphaFace endpoint (face swap)
                                                         └──► S3 gallery/<id>.jpg
```

| Route | Description |
|---|---|
| `GET /api/options` | Eras, roles and styles (single source of truth in `lambda/catalog.py`) |
| `POST /api/portraits` | `{era, role, style, idea?, photo?, consent?, likeness?}` → `202 {id}` (queues the async worker). `photo` is a base64 JPEG/PNG (data URL allowed, max 4 MB decoded). It is stored privately under `uploads/` and requires `consent: true`. |
| `GET /api/portraits/{id}` | Status (`QUEUED`/`RUNNING`/`COMPLETE`/`FAILED`/`REJECTED`), stage and result |
| `GET /api/gallery?cursor=` | Newest completed portraits (paged) |

Cost and safety guard-rails for a public demo:
- API stage throttling (5 rps, burst 10).
- The worker's reserved concurrency is capped at 5.
- Input is validated against an allowlist, and the free-text idea is limited to 200 characters and treated as untrusted.
- Uploaded photos are checked by magic bytes (JPEG/PNG only) and size. They are kept under a private `uploads/` prefix that CloudFront never routes to, and are deleted after generation.
- Claude's rules require fictional, family-friendly characters, and Stability's own content filters also apply.
- Unfinished or rejected jobs expire through a DynamoDB TTL.

## Deploy

Prerequisites:
- Node.js 18+ and the AWS CLI v2.
- An account where CDK is bootstrapped in the target region.
- Bedrock model access to Claude Opus 5.5 (us-east-1, global profile), Stable Image Ultra (us-west-2) and Stable Image Control Structure (US cross-region profile, us-west-2).
- Python 3 and git (to build the AlphaFace model artifact), and SageMaker quota for one `ml.g4dn.xlarge` endpoint instance in the target region.

```bash
./deploy.sh            # reads deploy.config.json (stack name, region, model IDs, faceSwap)
```

When `faceSwap.enabled` is true, `deploy.sh` first runs `sagemaker/alphaface/build_model.sh`. That script downloads the AlphaFace demo checkpoint and the ArcFace R50 encoder from the Google Drive links in the official AlphaFace README, plus the YuNet detector. It pins the upstream code at commit `d41fbd4` and builds `sagemaker/alphaface/build/model.tar.gz` (~650 MB, cached and git-ignored). CDK uploads the archive as an asset and creates the SageMaker model, endpoint config and endpoint. A first deploy takes about 10 minutes longer while the GPU endpoint starts.

> **Capacity:** the instance type is `faceSwap.instanceType` in `deploy.config.json`. The first attempt used `ml.g5.xlarge`, but us-east-1 had no capacity for it (`InsufficientInstanceCapacity`), so the default is now `ml.g4dn.xlarge` (NVIDIA T4). Any CUDA GPU instance, or a CPU instance with the `-cpu-` DLC image (~4-10 s per swap), also works.
>
> **Cost:** the `ml.g4dn.xlarge` endpoint is billed per hour while it runs, even when idle. Destroy the stack, or set `faceSwap.enabled: false` and redeploy, when the demo isn't in use.
>
> **Licences:** the AlphaFace code is MIT. The ArcFace `w600k_r50` identity weights come from InsightFace, whose pretrained models are for non-commercial research use. Check the licences before any commercial use.

Local smoke test of the face swap (CPU is fine, ~15 s):

```bash
./sagemaker/alphaface/build_model.sh
python sagemaker/alphaface/build/model/code/inference.py sagemaker/alphaface/build/model selfie.jpg painting.jpg out.jpg
```

The script prints the CloudFront URL. To switch models, edit `deploy.config.json`.

## Test

```bash
python3 -m unittest discover -s tests -v      # API validation / worker pipeline incl. face-swap fallback (needs boto3)
cd infra && npm install && npx tsc && npx cdk synth -q
```

## Clean up

```bash
cd infra && npx cdk destroy --all
```

The buckets and table use `DESTROY` removal policies because this is a development preview.
