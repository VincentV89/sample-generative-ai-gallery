# Gallery Serverless: Time-Travel Portrait Studio

A fully serverless version of the generative AI gallery. Visitors pick an era, a role and an art style, and can add an optional twist:

1. **Claude Opus 5.5** (`global.anthropic.claude-opus-5-5`) acts as the *art director*. It invents a fictional character, writes the backstory, title, museum caption and colour palette, and writes the image prompt. It also screens unsafe or prompt-injection ideas.
2. **Stable Image Ultra** (`stability.stable-image-ultra-v1:1`, served from `us-west-2`) acts as the *painter*.
3. The finished portrait goes up on a public **gallery wall**, which also has a kiosk-style **Exhibition mode** (`#/wall`) for event screens.

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
| `POST /api/portraits` | `{era, role, style, idea?}` → `202 {id}` (queues the async worker) |
| `GET /api/portraits/{id}` | Status (`QUEUED`/`RUNNING`/`COMPLETE`/`FAILED`/`REJECTED`), stage and result |
| `GET /api/gallery?cursor=` | Newest completed portraits (paged) |

Cost and safety guard-rails for a public demo:
- API stage throttling (5 rps, burst 10).
- The worker's reserved concurrency is capped at 5.
- Input is validated against an allowlist, and the free-text idea is limited to 200 characters and treated as untrusted.
- Claude's rules require fictional, family-friendly characters, and Stability's own content filters also apply.
- Unfinished or rejected jobs expire through a DynamoDB TTL.

## Deploy

Prerequisites:
- Node.js 18+ and the AWS CLI v2.
- An account where CDK is bootstrapped in the target region.
- Bedrock model access to Claude Opus 5.5 (us-east-1, global profile) and Stable Image Ultra (us-west-2).

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
