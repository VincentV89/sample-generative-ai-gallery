"""SageMaker inference handler: AlphaFace face swap (visitor face -> painted portrait).

AlphaFace (Yu et al., 2026, arXiv:2601.16429, MIT license,
https://github.com/andrewyu90/Alphaface_Official) is a real-time GAN face swapper. It is
robust to facial pose. It works on FFHQ-aligned 256x256 face crops:

  target (painting crop, 256px, [0, 1]) + source identity (visitor crop resized to 112px,
  [-1, 1]) -> ArcFace R50 identity code -> swapped 256px crop.

This handler:
1. detects the largest face in the source photo and in the target portrait (OpenCV YuNet),
2. FFHQ-aligns both from the 5 facial landmarks,
3. runs AlphaFace,
4. colour-matches the swapped crop to the painting (so it keeps the painted look), then
   pastes it back with a feathered face mask. ``blend`` (0-1) sets how strong the swap is.

Request  (application/json): {"source": <b64 jpeg/png>, "target": <b64 jpeg/png>, "blend": 0.9}
Response (application/json): {"image": <b64 jpeg>, "faces": {"source": n, "target": n},
                              "inferenceMs": int}
On a request without a usable face, it returns {"error": "...", "code": "NO_FACE_*"} (still
HTTP 200, so the caller can fall back to another painter).
"""
import base64
import io
import json
import os
import sys
import time

import cv2
import numpy as np
import torch
from blending import face_mask, match_colour, composite_face
from torch import nn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "alphaface"))

from Swapper_Units_AdIN import Decoder, Encoder  # noqa: E402  (upstream AlphaFace code)
from arcface_resnet import resnet50  # noqa: E402

TARGET_SIZE = 256
SOURCE_SIZE = 112
MAX_SIDE = 2048
MIN_FACE_PX = 48


# ---------------------------------------------------------------- model
class IdEncoder(nn.Module):
    """ArcFace R50 (w600k) + the AlphaFace identity projection (emp.npy), L2-normalised."""

    def __init__(self, emap):
        super().__init__()
        self.resnet = resnet50()
        self.ema = nn.Linear(512, 512)
        self.ema.weight.data = torch.from_numpy(emap).permute(1, 0).contiguous()
        self.ema.bias.data.fill_(0.0)

    def forward(self, x):
        x = self.ema(self.resnet(x))
        return x / torch.linalg.norm(x, dim=1, keepdim=True)


class Swapper(nn.Module):
    def __init__(self):
        super().__init__()
        self.E = Encoder(512)
        self.G = Decoder(1024, 3)

    def forward(self, target, id_code):
        return self.G(self.E(target, id_code))


class AlphaFaceModel:
    def __init__(self, model_dir, device):
        self.device = device
        emap = np.load(os.path.join(model_dir, "emp.npy")).astype(np.float32)
        self.id_encoder = IdEncoder(emap)
        self.id_encoder.resnet.load_state_dict(
            torch.load(os.path.join(model_dir, "arcface_w600k_r50_pytorch.pt"), map_location="cpu"))
        self.swapper = Swapper()
        self.swapper.load_state_dict(torch.load(os.path.join(model_dir, "alphaface_swapper.pt"), map_location="cpu"))
        self.id_encoder.eval().to(device)
        self.swapper.eval().to(device)
        self.detector_path = os.path.join(model_dir, "face_detection_yunet_2023mar.onnx")

    @torch.inference_mode()
    def swap_crop(self, target_crop_rgb, source_crop_rgb):
        """target/source: uint8 RGB 256x256 FFHQ-aligned crops -> uint8 RGB 256x256 swapped crop."""
        tgt = torch.from_numpy(target_crop_rgb).permute(2, 0, 1).float().div(255.0).unsqueeze(0).to(self.device)
        src = cv2.resize(source_crop_rgb, (SOURCE_SIZE, SOURCE_SIZE), interpolation=cv2.INTER_AREA)
        src = torch.from_numpy(src).permute(2, 0, 1).float().div(127.5).sub(1.0).unsqueeze(0).to(self.device)
        out = self.swapper(tgt, self.id_encoder(src))
        out = out[0].clamp(0, 1).mul(255.0).byte().permute(1, 2, 0).cpu().numpy()
        return out


# ---------------------------------------------------------------- face geometry
def detect_faces(detector_path, bgr):
    """Returns YuNet faces sorted by area (largest first): rows of [x, y, w, h, 5x(lx, ly), score]."""
    h, w = bgr.shape[:2]
    det = cv2.FaceDetectorYN.create(detector_path, "", (w, h), score_threshold=0.6, nms_threshold=0.3, top_k=50)
    _, faces = det.detect(bgr)
    if faces is None:
        return np.zeros((0, 15), np.float32)
    faces = [f for f in faces if min(f[2], f[3]) >= MIN_FACE_PX]
    return np.array(sorted(faces, key=lambda f: -f[2] * f[3]), np.float32).reshape(-1, 15)


def ffhq_affine(landmarks5, size=TARGET_SIZE):
    """FFHQ alignment (Karras et al.) from 5 points: right eye, left eye, nose, right/left mouth corner.

    Returns the 2x3 affine matrix mapping the image to the size x size aligned crop.
    """
    lm = np.asarray(landmarks5, np.float64).reshape(5, 2)
    eye_a, eye_b, _, mouth_a, mouth_b = lm
    eye_left, eye_right = (eye_a, eye_b) if eye_a[0] < eye_b[0] else (eye_b, eye_a)
    eye_avg = (eye_left + eye_right) * 0.5
    eye_to_eye = eye_right - eye_left
    mouth_avg = (mouth_a + mouth_b) * 0.5
    eye_to_mouth = mouth_avg - eye_avg

    x = eye_to_eye - np.flipud(eye_to_mouth) * [-1, 1]
    x /= np.hypot(*x)
    x *= max(np.hypot(*eye_to_eye) * 2.0, np.hypot(*eye_to_mouth) * 1.8)
    y = np.flipud(x) * [-1, 1]
    c = eye_avg + eye_to_mouth * 0.1
    quad = np.stack([c - x - y, c - x + y, c + x + y])  # top-left, bottom-left, bottom-right
    dst = np.array([[0, 0], [0, size], [size, size]], np.float64)
    return cv2.getAffineTransform(quad.astype(np.float32), dst.astype(np.float32))


def decode_image(b64):
    if isinstance(b64, str) and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    arr = np.frombuffer(base64.b64decode(b64), np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Could not decode image")
    h, w = bgr.shape[:2]
    if max(h, w) > MAX_SIDE:
        scale = MAX_SIDE / max(h, w)
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return bgr


def swap(model, source_bgr, target_bgr, blend=0.9):
    src_faces = detect_faces(model.detector_path, source_bgr)
    if not len(src_faces):
        return None, {"code": "NO_FACE_SOURCE", "error": "No face found in the visitor photo"}
    tgt_faces = detect_faces(model.detector_path, target_bgr)
    if not len(tgt_faces):
        return None, {"code": "NO_FACE_TARGET", "error": "No face found in the painted portrait"}

    source_rgb = cv2.cvtColor(source_bgr, cv2.COLOR_BGR2RGB)
    target_rgb = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2RGB)
    m_src = ffhq_affine(src_faces[0][4:14])
    m_tgt = ffhq_affine(tgt_faces[0][4:14])
    src_crop = cv2.warpAffine(source_rgb, m_src, (TARGET_SIZE, TARGET_SIZE), flags=cv2.INTER_AREA,
                              borderMode=cv2.BORDER_REFLECT)
    tgt_crop = cv2.warpAffine(target_rgb, m_tgt, (TARGET_SIZE, TARGET_SIZE), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)

    swapped = model.swap_crop(tgt_crop, src_crop)
    aligned_landmarks = cv2.transform(tgt_faces[0][4:14].reshape(1, 5, 2), m_tgt)[0]
    mask = face_mask(aligned_landmarks, TARGET_SIZE)
    swapped = match_colour(swapped, tgt_crop, mask)

    # Paste back into the full-resolution portrait.
    h, w = target_rgb.shape[:2]
    inv = cv2.invertAffineTransform(m_tgt)
    face_full = cv2.warpAffine(swapped, inv, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    mask_full = cv2.warpAffine(mask, inv, (w, h), flags=cv2.INTER_LINEAR, borderValue=0.0)
    out = composite_face(face_full, target_rgb, mask_full, blend)
    out_bgr = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    return out_bgr, {"faces": {"source": int(len(src_faces)), "target": int(len(tgt_faces))}}


# ---------------------------------------------------------------- SageMaker hooks
def model_fn(model_dir, context=None):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading AlphaFace on {device}")
    return AlphaFaceModel(model_dir, device)


def input_fn(request_body, content_type="application/json"):
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type {content_type}")
    if isinstance(request_body, (bytes, bytearray)):
        request_body = request_body.decode("utf-8")
    return json.loads(request_body)


def predict_fn(data, model, context=None):
    started = time.time()
    if data.get("ping"):
        return {"ok": True}
    source = decode_image(data["source"])
    target = decode_image(data["target"])
    image, info = swap(model, source, target, data.get("blend", 0.9))
    if image is None:
        return info
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return {"image": base64.b64encode(buf.tobytes()).decode(), "inferenceMs": int((time.time() - started) * 1000),
            **info}


def output_fn(prediction, accept="application/json"):
    return json.dumps(prediction), "application/json"


if __name__ == "__main__":  # local smoke test: python inference.py MODEL_DIR source.jpg target.jpg out.jpg
    mdl = model_fn(sys.argv[1])
    with open(sys.argv[2], "rb") as fs, open(sys.argv[3], "rb") as ft:
        payload = {"source": base64.b64encode(fs.read()).decode(), "target": base64.b64encode(ft.read()).decode()}
    result = predict_fn(payload, mdl)
    if "image" not in result:
        print(result)
        sys.exit(1)
    with open(sys.argv[4], "wb") as fo:
        fo.write(base64.b64decode(result["image"]))
    print({k: v for k, v in result.items() if k != "image"})
