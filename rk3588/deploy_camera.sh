#!/bin/bash
# Deploy video/control assets and documentation; keep a dated device backup.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
device_host=${1:-192.168.112.122}
ssh_key=${ROARM_SSH_KEY:-$HOME/.ssh/roarm-rk3588}
ssh_options=(-F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i "$ssh_key")
ssh "${ssh_options[@]}" "root@$device_host" 'test -x /opt/roarm-camera/.venv/bin/python && backup=/opt/roarm-camera/backups/$(date +%Y%m%d-%H%M%S) && mkdir -p "$backup" && for asset in camera_server.py control.html arm_adapter.js README.md; do if test -f "/opt/roarm-camera/$asset"; then cp -p "/opt/roarm-camera/$asset" "$backup/"; fi; done && if test -f /etc/systemd/system/roarm-camera.service; then cp -p /etc/systemd/system/roarm-camera.service "$backup/"; fi'
scp "${ssh_options[@]}" "$source_dir/camera_server.py" "$source_dir/control.html" "$source_dir/arm_adapter.js" "$source_dir/README.md" "root@$device_host:/opt/roarm-camera/"
scp "${ssh_options[@]}" "$source_dir/roarm-camera.service" "root@$device_host:/etc/systemd/system/"
ssh "${ssh_options[@]}" "root@$device_host" 'chmod 644 /opt/roarm-camera/camera_server.py /opt/roarm-camera/control.html /opt/roarm-camera/arm_adapter.js && /opt/roarm-camera/.venv/bin/python -c "import ast; from pathlib import Path; ast.parse(Path(\"/opt/roarm-camera/camera_server.py\").read_text())" && systemctl daemon-reload && systemctl enable roarm-camera.service && systemctl restart roarm-camera.service && systemctl is-active roarm-camera.service'
