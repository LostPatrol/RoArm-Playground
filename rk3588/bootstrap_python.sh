#!/bin/sh
# Create this project's Python environment using the OS-provided OpenCV packages.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 -m venv --system-site-packages --without-pip "$project_dir/.venv"
"$project_dir/.venv/bin/python" -c 'import sys, cv2, numpy; print("Project Python:", sys.prefix)'
