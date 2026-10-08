#!/usr/bin/env bash
# Build pinned llama.cpp locally; CPU is portable, CUDA targets both demo GPUs.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${LLAMA_SOURCE_DIR:-$project_dir/agent/codex/llama.cpp-b4514}"
backend="${1:-cpu}"
case "$backend" in cpu|cuda) ;; *) echo 'Usage: build_director.sh [cpu|cuda]' >&2; exit 2;; esac
if [[ ! -d "$source_dir/.git" ]]; then
    mkdir -p "$(dirname -- "$source_dir")"
    git clone --depth 1 --branch b4514 https://github.com/ggml-org/llama.cpp.git "$source_dir"
fi
expected_commit=ec7f3ac9ab33e46b136eb5ab6a76c4d81f57c7f1
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$expected_commit" ]] || {
    echo 'llama.cpp source commit differs from pinned b4514; use a fresh LLAMA_SOURCE_DIR' >&2; exit 1;
}
cuda_options=(-DGGML_CUDA=OFF)
if [[ "$backend" == cuda ]]; then
    cuda_options=(-DGGML_CUDA=ON '-DCMAKE_CUDA_ARCHITECTURES=86;89')
fi
cmake -S "$source_dir" -B "$source_dir/build-$backend" -DCMAKE_BUILD_TYPE=Release \
    -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF "${cuda_options[@]}"
cmake --build "$source_dir/build-$backend" --target llama-server -j "${BUILD_JOBS:-6}"
echo "Built $source_dir/build-$backend/bin/llama-server"
