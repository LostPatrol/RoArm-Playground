#!/usr/bin/env bash
# Install this project's host manager as a persistent user service; models remain local.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
rk_server=${1:-http://192.168.112.122:8080}
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    echo 'Create the project .venv and install host/requirements.txt first.' >&2
    exit 1
fi
cat > "$unit_dir/roarm-host.service" <<EOF
# RoArm host manager: user-login startup and recovery, with persistent local model service.
[Unit]
Description=RoArm local gesture and language model manager
After=network.target

[Service]
WorkingDirectory=$project_dir
ExecStart=$project_dir/.venv/bin/python -m host.manager --server $rk_server --start-director
Restart=on-failure
RestartSec=3
KillMode=control-group

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now roarm-host.service
systemctl --user status roarm-host.service --no-pager
