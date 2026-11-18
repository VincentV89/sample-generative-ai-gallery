# Gallery Serverless: Time-Travel Portrait Studio

A fully serverless version of the generative AI gallery, built for events:

- **Gallery display** (`#/display`): a full-screen kiosk page for a (portrait) screen. It cycles through the newest portraits with their title and story, shows new arrivals as soon as they are finished, and has a **QR code** that opens the create page.
- **Create page** (`#/create`, the default page, mobile-first): visitors **take a selfie or upload a picture**, then choose an era, a role, an art style and a likeness level, and can add an optional twist. They must agree to the consent box before a photo is used.

How a portrait is made:

1. In the browser, the photo is cropped to 2:3, resized to about 1 MP and re-encoded as JPEG, which also strips EXIF and location data.
2. **Claude Opus 5.5** (`global.anthropic.claude-opus-5-5`) acts as the *art director*. It looks at the photo and describes the sitter's visible features (hair, glasses, expression, pose) without identifying them. It then invents the character, backstory, title, caption and palette, and writes the image prompt. It also screens unsafe photos and ideas, including prompt-injection attempts.
3. The *painter*:
   - With a photo: **Stable Image Control Structure** (`us.stability.stable-image-control-structure-v1:0`, from `us-west-2`) repaints the photo and keeps the face, pose and composition. The likeness setting (Artistic / Balanced / Faithful) maps to `control_strength` 0.45 / 0.6 / 0.75. Stable Image Ultra on Bedrock is text-to-image only.
   - Without a photo: **Stable Image Ultra** (`stability.stable-image-ultra-v1:1`) paints a fictional character from text.
4. The portrait goes up on the gallery and the display. The visitor's original photo is deleted as soon as the job finishes, and an S3 lifecycle rule on `uploads/` (1 day) is the backstop.

## Architecture

```
Browser ──► CloudFront ──┬─ /*          ──► S3 (site, private, OAC)
                         ├─ /gallery/*  ──► S3 (images, private, OAC)
                         └─ /api/*      ──► API Gateway HTTP API ──► Lambda (api.py)
                                                                       │ async invoke
                                                                       ▼
                                   DynamoDB ◄── Lambda (worker.py) ──► Bedrock: Claude Opus 5.5
                                                         │             Bedrock: Stable Image Ultra
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

```bash
./deploy.sh            # reads deploy.config.json (stack name, region, model IDs)
```

The script prints the CloudFront URL. To switch models, edit `deploy.config.json`.

## Test

```bash
python3 -m unittest discover -s tests -v      # API validation / worker parsing (needs boto3)
cd infra && npm install && npx tsc && npx cdk synth -q
```

## Clean up

```bash
cd infra && npx cdk destroy --all
```

The buckets and table use `DESTROY` removal policies because this is a development preview.
