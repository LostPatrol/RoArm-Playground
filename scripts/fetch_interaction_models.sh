#!/usr/bin/env bash
# Download versioned interaction models, verify pinned SHA256, and unpack Vosk.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="${ROARM_MODEL_DIR:-$project_dir/models}"
project_python="${ROARM_PYTHON:-$project_dir/.venv/bin/python}"
mkdir -p "$model_dir"

fetch() {
    local filename="$1" source_url="$2" digest="$3"
    if ! printf '%s  %s\n' "$digest" "$model_dir/$filename" | sha256sum -c --status; then
        curl --http1.1 -fL --retry 3 --retry-all-errors --connect-timeout 20 --max-time 1800 \
            "$source_url" -o "$model_dir/$filename.part"
        printf '%s  %s\n' "$digest" "$model_dir/$filename.part" | sha256sum -c
        mv -- "$model_dir/$filename.part" "$model_dir/$filename"
    fi
    printf '%s  %s\n' "$digest" "$filename" > "$model_dir/$filename.sha256"
    printf '%s\n' "$source_url" > "$model_dir/$filename.source.txt"
}

selection="${1:-all}"
case "$selection" in gestures|speech|llm|all) ;; *) echo 'Usage: fetch_interaction_models.sh [gestures|speech|llm|all]' >&2; exit 2;; esac
if [[ "$selection" == gestures || "$selection" == all ]]; then
    fetch gesture_recognizer.task \
        https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task \
        97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482
fi
if [[ "$selection" == speech || "$selection" == all ]]; then
    fetch vosk-model-small-cn-0.22.zip https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip \
        3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba
    "$project_python" -c 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
        "$model_dir/vosk-model-small-cn-0.22.zip" "$model_dir"
fi
if [[ "$selection" == llm || "$selection" == all ]]; then
    fetch qwen2.5-1.5b-instruct-q4_k_m.gguf \
        https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf \
        6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e
fi
