#!/usr/bin/env bash
# Builds the SageMaker model artifact (model.tar.gz) for the AlphaFace face-swap endpoint.
#
#   ./build_model.sh [OUT_DIR]        -> OUT_DIR/model.tar.gz (default: ./build)
#
# Contents: AlphaFace generator weights + ArcFace R50 identity encoder (from the official
# AlphaFace release), the OpenCV YuNet face detector, and code/ (inference.py + the upstream
# AlphaFace network definitions at a pinned commit).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mkdir -p "${1:-$HERE/build}" && cd "${1:-$HERE/build}" && pwd)"
WORK="$OUT/work"
ALPHAFACE_REPO=https://github.com/andrewyu90/Alphaface_Official.git
ALPHAFACE_COMMIT=d41fbd4974ed3a68d9a48b79019f9be297726c30
# Google Drive IDs published in the AlphaFace README (demo swapper checkpoint, ArcFace R50 w600k).
ALPHAFACE_GDRIVE_ID=18ZOQB3WmIFnMwi1GqBroFFEOuSNKWpZQ
ARCFACE_GDRIVE_ID=1qc4s6eRQPluma72WFibUnw74GPMAYRtY
YUNET_URL=https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

mkdir -p "$WORK" "$OUT/model/code/alphaface"
if [[ ! -d "$WORK/venv" ]]; then
  python3 -m venv "$WORK/venv"
  "$WORK/venv/bin/pip" install -q gdown numpy torch --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
fi
PY="$WORK/venv/bin/python"

if [[ ! -d "$WORK/Alphaface_Official" ]]; then
  git clone -q "$ALPHAFACE_REPO" "$WORK/Alphaface_Official"
fi
git -C "$WORK/Alphaface_Official" checkout -q "$ALPHAFACE_COMMIT"

[[ -s "$WORK/alphaface_demo.pt" ]] || "$WORK/venv/bin/gdown" -q "$ALPHAFACE_GDRIVE_ID" -O "$WORK/alphaface_demo.pt"
[[ -s "$OUT/model/arcface_w600k_r50_pytorch.pt" ]] || "$WORK/venv/bin/gdown" -q "$ARCFACE_GDRIVE_ID" -O "$OUT/model/arcface_w600k_r50_pytorch.pt"
[[ -s "$OUT/model/alphaface_swapper.pt" ]] || "$PY" -I "$HERE/extract_swapper.py" "$WORK/alphaface_demo.pt" "$OUT/model/alphaface_swapper.pt"
[[ -s "$OUT/model/face_detection_yunet_2023mar.onnx" ]] || curl -sSfL -o "$OUT/model/face_detection_yunet_2023mar.onnx" "$YUNET_URL"

cp "$WORK/Alphaface_Official/Models/emp.npy" "$OUT/model/emp.npy"
cp "$WORK/Alphaface_Official/Models/Swapper_Units_AdIN.py" "$WORK/Alphaface_Official/Models/arcface_resnet.py" \
   "$WORK/Alphaface_Official/LICENSE" "$OUT/model/code/alphaface/"
cp "$HERE/code/inference.py" "$HERE/code/requirements.txt" "$OUT/model/code/"

tar -C "$OUT/model" -czf "$OUT/model.tar.gz" .
echo "Built $OUT/model.tar.gz ($(du -h "$OUT/model.tar.gz" | cut -f1))"
