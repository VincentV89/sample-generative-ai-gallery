"""HTTP API handler (API Gateway HTTP API, payload v2) for the serverless gallery.

Routes
  GET  /api/options          -> creative options (eras, roles, styles)
  GET  /api/gallery          -> newest completed portraits (?cursor= for paging)
  POST /api/portraits        -> queue a new portrait, returns {id}
                                (optional "photo": base64 JPEG/PNG of the visitor)
  GET  /api/portraits/{id}   -> status / result of a portrait
"""
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from catalog import (DEFAULT_LIKENESS, ERAS, LIKENESS, MAX_IDEA_LENGTH, MAX_PHOTO_BYTES, ROLES,
                     STYLES, public_options)

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
LAMBDA = boto3.client("lambda")
S3 = boto3.client("s3")
WORKER = os.environ["WORKER_FUNCTION_NAME"]
IMAGE_BUCKET = os.environ["IMAGE_BUCKET"]

GALLERY_PAGE_SIZE = 24
PUBLIC_FIELDS = ("id", "status", "stage", "era", "role", "style", "title", "story",
                 "caption", "palette", "prompt", "imageUrl", "error", "createdAt",
                 "completedAt", "textModel", "imageModel", "fromPhoto", "likeness")


def _resp(status, body, cache_seconds=0):
    headers = {"Content-Type": "application/json"}
    headers["Cache-Control"] = f"public, max-age={cache_seconds}" if cache_seconds else "no-store"
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, default=str)}


def _public(item):
    out = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    for k in ("era", "role", "style", "likeness"):
        if k in out:
            out[f"{k}Label"] = _label(k, out[k])
    return out


def _label(kind, key):
    if kind == "era":
        return ERAS.get(key, {}).get("label", key)
    if kind == "role":
        return ROLES.get(key, key)
    if kind == "likeness":
        return LIKENESS.get(key, {}).get("label", key)
    return STYLES.get(key, {}).get("label", key)


def _decode_photo(value):
    """Validate an uploaded photo. Returns (bytes, content_type) or raises ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("Photo must be a base64 image")
    if value.startswith("data:"):
        value = value.split(",", 1)[-1]
    if len(value) > MAX_PHOTO_BYTES * 4 // 3 + 4:
        raise ValueError("Photo is too large")
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError:
        raise ValueError("Photo must be a base64 image") from None
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    raise ValueError("Photo must be a JPEG or PNG image")


def _create(event):
    try:
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _resp(400, {"message": "Body must be JSON"})
    if not isinstance(body, dict):
        return _resp(400, {"message": "Body must be a JSON object"})

    era, role, style = body.get("era"), body.get("role"), body.get("style")
    idea = body.get("idea") or ""
    if era not in ERAS or role not in ROLES or style not in STYLES:
        return _resp(400, {"message": "Unknown era, role or style"})
    if not isinstance(idea, str) or len(idea) > MAX_IDEA_LENGTH:
        return _resp(400, {"message": f"Idea must be text up to {MAX_IDEA_LENGTH} characters"})
    likeness = body.get("likeness") or DEFAULT_LIKENESS
    if likeness not in LIKENESS:
        return _resp(400, {"message": "Unknown likeness"})

    photo = None
    if body.get("photo"):
        if body.get("consent") is not True:
            return _resp(400, {"message": "Please agree to the photo terms to use your picture"})
        try:
            photo = _decode_photo(body["photo"])
        except ValueError as exc:
            return _resp(400, {"message": str(exc)})

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": uuid.uuid4().hex,
        "status": "QUEUED",
        "stage": "queued",
        "era": era,
        "role": role,
        "style": style,
        "idea": " ".join(idea.split()),
        "createdAt": now,
        # Unfinished/failed jobs expire; the worker removes the TTL on success.
        "ttl": int(time.time()) + 7 * 24 * 3600,
    }
    if photo:
        # Private prefix (not routed by CloudFront); deleted by the worker and by a lifecycle rule.
        key = f"uploads/{item['id']}{'.png' if photo[1] == 'image/png' else '.jpg'}"
        S3.put_object(Bucket=IMAGE_BUCKET, Key=key, Body=photo[0], ContentType=photo[1])
        item.update(photoKey=key, fromPhoto=True, likeness=likeness)
    TABLE.put_item(Item=item)
    LAMBDA.invoke(FunctionName=WORKER, InvocationType="Event",
                  Payload=json.dumps({"id": item["id"]}).encode())
    return _resp(202, {"id": item["id"], "status": item["status"]})


def _get(portrait_id):
    if not portrait_id or len(portrait_id) != 32 or not portrait_id.isalnum():
        return _resp(404, {"message": "Not found"})
    item = TABLE.get_item(Key={"id": portrait_id}).get("Item")
    if not item:
        return _resp(404, {"message": "Not found"})
    return _resp(200, _public(item))


def _gallery(params):
    kwargs = {
        "IndexName": "gallery",
        "KeyConditionExpression": Key("galleryPk").eq("GALLERY"),
        "ScanIndexForward": False,
        "Limit": GALLERY_PAGE_SIZE,
    }
    cursor = (params or {}).get("cursor")
    if cursor:
        try:
            kwargs["ExclusiveStartKey"] = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeDecodeError):
            return _resp(400, {"message": "Bad cursor"})
    result = TABLE.query(**kwargs)
    next_key = result.get("LastEvaluatedKey")
    return _resp(200, {
        "items": [_public(i) for i in result.get("Items", [])],
        "cursor": base64.urlsafe_b64encode(json.dumps(next_key).encode()).decode() if next_key else None,
    })


def handler(event, _context):
    route = event.get("routeKey", "")
    try:
        if route == "GET /api/options":
            return _resp(200, public_options(), cache_seconds=300)
        if route == "GET /api/gallery":
            return _gallery(event.get("queryStringParameters"))
        if route == "POST /api/portraits":
            return _create(event)
        if route == "GET /api/portraits/{id}":
            return _get((event.get("pathParameters") or {}).get("id"))
        return _resp(404, {"message": "Not found"})
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Unhandled error for {route}: {exc!r}")
        return _resp(500, {"message": "Internal error"})
