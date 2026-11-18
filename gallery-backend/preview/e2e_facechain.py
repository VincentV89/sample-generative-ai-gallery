"""End-to-end check of the preview upload -> face crop -> FaceChain face swap -> display flow.

Uses the same API calls as the frontend: POST /apis/images/upload, PUT the photo to the presigned
URL, then poll GET /apis/images/{userId} until the new result appears. Afterwards it confirms the
face-swap Lambda invoked the SageMaker endpoint (no composite fallback) for this upload.

Usage: e2e_facechain.py <region> <api_endpoint> <face_photo.jpg> <face_swap_function> <out.jpg>
"""
import io
import json
import sys
import time
import urllib.request
import uuid

import boto3
from PIL import Image


def call(method, url, body=None, headers=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def main(region, api, photo, function_name, out_path):
    user_id = f"e2e{uuid.uuid4().hex[:8]}"
    started = int(time.time() * 1000)
    payload = {"userId": user_id, "theme": "ancient_rome", "gender": "female", "skin": "white_fair"}
    status, body = call("POST", f"{api}/images/upload", json.dumps(payload).encode(),
                        {"Content-Type": "application/json"})
    upload = json.loads(body)
    print(f"POST upload -> {status}, uuid {upload['uuid']}")

    status, _ = call("PUT", upload["uploadUrl"], open(photo, "rb").read(), {"Content-Type": "image/jpeg"})
    print(f"PUT photo -> {status}")

    deadline = time.time() + 240
    result = None
    while time.time() < deadline:
        try:
            status, body = call("GET", f"{api}/images/{user_id}")
            result = json.loads(body)
            if result.get("uuid", "").endswith(upload["uuid"]):
                break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        time.sleep(3)
    else:
        raise SystemExit("no result image within 240s")
    print(f"GET result -> {status} after {(time.time() * 1000 - started) / 1000:.1f}s")

    _, image = call("GET", result["imageUrl"])
    img = Image.open(io.BytesIO(image))
    img.save(out_path)
    print(f"result image {img.format} {img.size}, saved to {out_path}")

    # Did this upload go through the GPU endpoint?
    logs = boto3.client("logs", region_name=region)
    time.sleep(10)
    events = logs.filter_log_events(logGroupName=f"/aws/lambda/{function_name}", startTime=started,
                                    filterPattern=f'"{upload["uuid"]}"')["events"]
    fallback = [e["message"] for e in events if "FaceChain endpoint" in e["message"]]
    if fallback:
        raise SystemExit(f"face swap fell back to the composite: {fallback[0].strip()}")
    print("face-swap Lambda used the FaceChain endpoint (no composite fallback logged)")


if __name__ == "__main__":
    main(*sys.argv[1:6])
