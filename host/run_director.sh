#!/usr/bin/env bash
# Start a real small GGUF model through llama.cpp; this process cannot move the arm.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
backend="${1:-cpu}"
case "$backend" in cpu|cuda) ;; *) echo 'Usage: run_director.sh [cpu|cuda]' >&2; exit 2;; esac
source_dir="${LLAMA_SOURCE_DIR:-$project_dir/agent/codex/llama.cpp-b4514}"
server_bin="${LLAMA_SERVER:-$source_dir/build-$backend/bin/llama-server}"
model_file="${DIRECTOR_MODEL_FILE:-$project_dir/models/qwen2.5-1.5b-instruct-q4_k_m.gguf}"
if [[ ! -x "$server_bin" || ! -f "$model_file" ]]; then
    echo 'First run scripts/fetch_interaction_models.sh llm and host/build_director.sh cpu|cuda' >&2
    exit 1
fi
gpu_layers=0
[[ "$backend" == cuda ]] && gpu_layers=99
exec "$server_bin" -m "$model_file" --alias roarm-director \
    --host "${DIRECTOR_HOST:-127.0.0.1}" --port "${DIRECTOR_PORT:-8081}" \
    -c 2048 -t "${DIRECTOR_THREADS:-6}" -ngl "$gpu_layers"
