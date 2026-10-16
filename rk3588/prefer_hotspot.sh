#!/usr/bin/env bash
# Prefer the saved phone hotspot, returning to the office Wi-Fi when it is absent.
set -euo pipefail
# These are saved NetworkManager profile names; credentials remain in NetworkManager.
hotspot=roarm-vivo-x300
fallback=roarm-demo-wifi
if [[ ${1:-} == --install ]]; then
    nmcli connection modify "$hotspot" connection.autoconnect yes connection.autoconnect-priority 20
    nmcli connection modify "$fallback" connection.autoconnect yes connection.autoconnect-priority 0
    # NetworkManager priority does not preempt an already active fallback connection.
    script_path=$(readlink -f "$0")
    cat > /etc/systemd/system/roarm-hotspot-preference.service <<EOF
# Re-evaluate the saved hotspot preference without changing arm services.
[Unit]
Description=Prefer the RoArm phone hotspot when visible
After=NetworkManager.service
[Service]
Type=oneshot
ExecStart=/bin/bash "$script_path"
TimeoutStartSec=45
EOF
    cat > /etc/systemd/system/roarm-hotspot-preference.timer <<'EOF'
# Periodic checks are needed when the hotspot appears after fallback Wi-Fi connected.
[Unit]
Description=Check RoArm phone hotspot availability
[Timer]
OnBootSec=15
OnUnitInactiveSec=20
AccuracySec=2
[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now roarm-hotspot-preference.timer
    systemctl start roarm-hotspot-preference.service
    exit 0
fi
# The RK has one USB Wi-Fi adapter; allow its device name to change after replacement.
device=$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2 == "wifi" {print $1; exit}')
[[ -n "$device" ]] || exit 0
current=$(nmcli -g GENERAL.CONNECTION device show "$device")
[[ "$current" != "$hotspot" ]] || exit 0
ssid=$(nmcli -g 802-11-wireless.ssid connection show "$hotspot")
if ! visible=$(nmcli -g SSID device wifi list ifname "$device" --rescan yes); then
    echo 'Wi-Fi scan failed; keep the current connection and retry later.' >&2
    exit 0
fi
if printf '%s\n' "$visible" | grep -Fxq -- "$ssid"; then
    echo "Preferred hotspot is visible; connecting $hotspot."
    nmcli --wait 25 connection up "$hotspot" ifname "$device" || echo 'Hotspot connection failed; NetworkManager can fall back and the timer will retry.' >&2
elif [[ -z "$current" || "$current" == -- ]]; then
    nmcli --wait 25 connection up "$fallback" ifname "$device" || echo 'Fallback unavailable; retrying later.' >&2
fi
