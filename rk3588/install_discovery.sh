#!/usr/bin/env bash
# Publish a stable local name for the RK webpage without changing its system hostname.
set -euo pipefail
# Avahi answers local multicast DNS queries on the device's current network addresses.
config=/etc/avahi/avahi-daemon.conf
device_name=${1:-roarm}
if [[ ! $device_name =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]]; then
    echo 'Use a single DNS hostname label, such as roarm.' >&2
    exit 1
fi
if ! command -v avahi-daemon >/dev/null; then
    apt-get update
    apt-get install -y --no-install-recommends avahi-daemon
fi
if [[ ! -f "$config.roarm-backup" ]]; then
    cp -p "$config" "$config.roarm-backup"
fi
# Replace only the active name; preserve the distribution's other daemon settings.
sed -i '/^host-name=/d' "$config"
sed -i "/^\[server\]$/a host-name=$device_name" "$config"
systemctl enable avahi-daemon
systemctl restart avahi-daemon
systemctl is-active avahi-daemon
echo "Playground local URL: http://$device_name.local:8080/"
