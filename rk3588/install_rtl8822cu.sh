#!/bin/sh
# Run as root on the RK3588, with the driver archive alongside this script.
set -eu
kernel_version=5.10.198
if [ "$(uname -r)" != "$kernel_version" ] || [ "$(uname -m)" != aarch64 ]; then
    echo "These modules require aarch64 Linux $kernel_version." >&2
    exit 1
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
tar -xzf "$script_dir/rtl8822cu-5.10.198.tar.gz" -C "$work_dir"
install -d "/lib/modules/$kernel_version/extra/roarm-rtw88" /lib/firmware/rtw88 /etc/usb_modeswitch.d
install -m 644 "$work_dir"/*.ko "/lib/modules/$kernel_version/extra/roarm-rtw88/"
install -m 644 "$work_dir"/firmware/*.bin /lib/firmware/rtw88/
install -m 644 "$script_dir/usb-modeswitch-rtl8822cu.conf" /etc/usb_modeswitch.d/0bda:1a2b
install -d /opt/roarm-camera /etc/udev/rules.d
# Bootstrap a project environment; runtime services never use system Python directly.
if [ ! -x /opt/roarm-camera/.venv/bin/python ]; then
    python3 -m venv --system-site-packages --without-pip /opt/roarm-camera/.venv
fi
install -m 644 "$script_dir/prepare_wifi_usb.py" "$script_dir/switch_wifi_usb.py" /opt/roarm-camera/
install -m 644 "$script_dir/roarm-wifi-usb.service" "$script_dir/roarm-wifi-switch@.service" /etc/systemd/system/
install -m 644 "$script_dir/80-roarm-wifi-switch.rules" /etc/udev/rules.d/
depmod -a "$kernel_version"
modprobe rtw_8822cu
systemctl daemon-reload
udevadm control --reload-rules
systemctl enable --now roarm-wifi-usb.service
echo 'Driver installed. Verify the adapter with lsusb and nmcli device status.'
