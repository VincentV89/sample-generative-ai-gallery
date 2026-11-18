"""HTTP API handler (API Gateway HTTP API, payload v2) for the serverless gallery.

Routes
  GET  /api/options          -> creative options (eras, roles, styles)
  GET  /api/gallery          -> newest completed portraits (?cursor= for paging)
  POST /api/portraits        -> queue a new portrait, returns {id}
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

from catalog import ERAS, MAX_IDEA_LENGTH, ROLES, STYLES, public_options

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
LAMBDA = boto3.client("lambda")
WORKER = os.environ["WORKER_FUNCTION_NAME"]

GALLERY_PAGE_SIZE = 24
PUBLIC_FIELDS = ("id", "status", "stage", "era", "role", "style", "title", "story",
                 "caption", "palette", "prompt", "imageUrl", "error", "createdAt",
                 "completedAt", "textModel", "imageModel")


def _resp(status, body, cache_seconds=0):
    headers = {"Content-Type": "application/json"}
    headers["Cache-Control"] = f"public, max-age={cache_seconds}" if cache_seconds else "no-store"
    return {"statusCode": status, "headers": headers, "body": json.dumps(body, default=str)}


def _public(item):
    out = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    for k in ("era", "role", "style"):
        if k in out:
            out[f"{k}Label"] = _label(k, out[k])
    return out


def _label(kind, key):
    if kind == "era":
        return ERAS.get(key, {}).get("label", key)
    if kind == "role":
        return ROLES.get(key, key)
    return STYLES.get(key, {}).get("label", key)


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
