"""Download a ModelScope model repo into a local directory at image build time.

modelscope 1.8.x's snapshot_download uses plain http (reset outside mainland China) and sends a
Range header for empty files (416), so the files are fetched directly over https here, with
retries, resume and sha256 verification. Usage: download_model.py <model_id> <revision> <dest>
"""
import hashlib
import os
import sys
import time

import requests

API = "https://www.modelscope.cn/api/v1/models"
SKIP_PREFIXES = ("description/",)
SKIP_PARTS = ("__pycache__", ".DS_Store")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def with_retries(fn, what, attempts=8):
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # network errors, checksum mismatches
            if i == attempts:
                raise
            print(f"{what}: attempt {i} failed ({e!r}), retrying", flush=True)
            time.sleep(min(60, 5 * i))


def list_files(model_id, revision):
    def get():
        r = requests.get(f"{API}/{model_id}/repo/files",
                         params={"Revision": revision, "Recursive": "True"}, timeout=60)
        r.raise_for_status()
        return r.json()["Data"]["Files"]
    return [f for f in with_retries(get, "list files") if f["Type"] == "blob"
            and not f["Path"].startswith(SKIP_PREFIXES)
            and not any(p in f["Path"] for p in SKIP_PARTS)]


def download(model_id, revision, entry, dest):
    path = os.path.join(dest, entry["Path"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if entry["Size"] == 0:
        open(path, "wb").close()
        return

    def get():
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have > entry["Size"]:
            os.remove(path)
            have = 0
        if have < entry["Size"]:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(f"{API}/{model_id}/repo", params={"Revision": revision, "FilePath": entry["Path"]},
                              headers=headers, stream=True, timeout=120) as r:
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"
                with open(path, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
        if os.path.getsize(path) != entry["Size"]:
            raise IOError(f"incomplete: {os.path.getsize(path)}/{entry['Size']} bytes")
        if entry.get("Sha256") and sha256(path) != entry["Sha256"]:
            os.remove(path)
            raise IOError("sha256 mismatch")

    with_retries(get, entry["Path"])


def main(model_id, revision, dest):
    files = list_files(model_id, revision)
    print(f"{len(files)} files, {sum(f['Size'] for f in files) / 1e6:.0f} MB", flush=True)
    for entry in files:
        download(model_id, revision, entry, dest)
        print(f"ok {entry['Path']} ({entry['Size']} bytes)", flush=True)
    if not os.path.exists(os.path.join(dest, "configuration.json")):
        raise SystemExit("configuration.json missing from the downloaded model")


if __name__ == "__main__":
    main(*sys.argv[1:4])
