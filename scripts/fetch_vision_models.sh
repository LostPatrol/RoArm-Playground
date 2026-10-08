#!/usr/bin/env bash
# Fetch pinned CPU detector/cascade models; SHA256 checks prevent silent upstream changes.
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
model_dir=${1:-"$repo_dir/models"}
mkdir -p "$model_dir"

fetch() {
    local filename=$1 url=$2 expected=$3
    if [[ -f "$model_dir/$filename" ]] && printf '%s  %s\n' "$expected" "$model_dir/$filename" | sha256sum --check --status; then
        printf 'Verified existing %s\n' "$filename"
        return
    fi
    curl --fail --location --retry 2 --retry-all-errors --connect-timeout 15 --max-time 180 "$url" --output "$model_dir/$filename.part"
    printf '%s  %s\n' "$expected" "$model_dir/$filename.part" | sha256sum --check
    mv "$model_dir/$filename.part" "$model_dir/$filename"
}

fetch yolox_nano.onnx \
    'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx' \
    c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d

# YuNet is the default face detector on OpenCV >=4.8; Haar remains explicit fallback.
fetch face_detection_yunet_2023mar.onnx \
    'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx' \
    8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4

# Haar also normally comes from Ubuntu opencv-data; vendor it for device installations.
fetch haarcascade_frontalface_default.xml \
    'https://raw.githubusercontent.com/opencv/opencv/4.6.0/data/haarcascades/haarcascade_frontalface_default.xml' \
    0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0
printf 'Models ready in %s (OpenCV DNN CPU; no CUDA/PyTorch required).\n' "$model_dir"
