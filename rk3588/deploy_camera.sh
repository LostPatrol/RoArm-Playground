#!/bin/bash
# Deploy serial playground, models and field manuals; preserve a dated backup.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
device_host=${1:-192.168.112.122}
ssh_key=${ROARM_SSH_KEY:-$HOME/.ssh/roarm-rk3588}
ssh_options=(-F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -i "$ssh_key")
ssh "${ssh_options[@]}" "root@$device_host" 'test -x /opt/roarm-camera/.venv/bin/python && backup=/opt/roarm-camera/backups/$(date +%Y%m%d-%H%M%S) && mkdir -p "$backup" && for asset in camera_server.py arm_serial.py playground.py vision.py control.html playground.js playground.css arm_adapter.js README.md host firmware docs; do if test -e "/opt/roarm-camera/$asset"; then cp -rp "/opt/roarm-camera/$asset" "$backup/"; fi; done && mkdir -p /opt/roarm-camera/models /opt/roarm-camera/docs && if test -f /etc/systemd/system/roarm-camera.service; then cp -p /etc/systemd/system/roarm-camera.service "$backup/"; fi'
scp "${ssh_options[@]}" "$source_dir/camera_server.py" "$source_dir/arm_serial.py" "$source_dir/playground.py" "$source_dir/vision.py" "$source_dir/control.html" "$source_dir/playground.js" "$source_dir/playground.css" "$source_dir/arm_adapter.js" "$source_dir/README.md" "root@$device_host:/opt/roarm-camera/"
scp -r "${ssh_options[@]}" "$source_dir/../host" "root@$device_host:/opt/roarm-camera/"
# Only public IMU reference files; never upload a local Wi-Fi config.h.
ssh "${ssh_options[@]}" "root@$device_host" 'mkdir -p /opt/roarm-camera/firmware/esp32_imu'
scp "${ssh_options[@]}" "$source_dir/../firmware/esp32_imu/README.md" "$source_dir/../firmware/esp32_imu/config.example.h" "$source_dir/../firmware/esp32_imu/esp32_imu.ino" "root@$device_host:/opt/roarm-camera/firmware/esp32_imu/"
scp -r "${ssh_options[@]}" "$source_dir/../docs/playground" "root@$device_host:/opt/roarm-camera/docs/"
scp "${ssh_options[@]}" "$source_dir/../docs/wifi-startup.md" "root@$device_host:/opt/roarm-camera/docs/"
# Model downloads are explicit and checksummed; installation never fetches new versions.
for model in yolox_nano.onnx haarcascade_frontalface_default.xml face_detection_yunet_2023mar.onnx; do
    if [[ -f "$source_dir/../models/$model" ]]; then
        scp "${ssh_options[@]}" "$source_dir/../models/$model" "root@$device_host:/opt/roarm-camera/models/"
    fi
done
scp "${ssh_options[@]}" "$source_dir/roarm-camera.service" "root@$device_host:/etc/systemd/system/"
ssh "${ssh_options[@]}" "root@$device_host" 'chmod 644 /opt/roarm-camera/*.py /opt/roarm-camera/*.html /opt/roarm-camera/*.js /opt/roarm-camera/*.css && /opt/roarm-camera/.venv/bin/python -c "import ast; from pathlib import Path; [ast.parse(p.read_text()) for p in Path(\"/opt/roarm-camera\").glob(\"*.py\")]" && systemctl daemon-reload && systemctl enable roarm-camera.service && systemctl restart roarm-camera.service && systemctl is-active roarm-camera.service'
