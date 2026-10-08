<!-- RTL8822CU开机联网机制、失败恢复与冷启动验收边界；2026-10-09。 -->
# USB网卡开机联网

本项目的RTL8822CU网卡初次通电可能枚举为`0bda:1a2b`驱动光盘；正确无线模式为`0bda:c812`。这两个ID不能当成两个不同网卡。网卡与摄像头接USB-A Hub，机械臂由RK Type-C串口连接。

`roarm-wifi-usb.service`设置已知网卡的usb-storage忽略标志；udev规则按实际USB端口启动`roarm-wifi-switch@端口.service`，调用`usb_modeswitch`并检查真实ID变为c812后加载驱动。切换失败每3秒重试，120秒内最多4次启动，单次最长25秒。成功后不再重试；NetworkManager沿用已保存的`roarm-demo-wifi`自动联网。机制不依赖固定Hub端口号或DHCP地址。

2026-10-09首次完整断电验证发现切换失败：网卡保持1a2b，没有无线接口，SSH/网页不可达。日志记录首条EJECT响应读取错误−8；不能只凭usb_modeswitch打印“消息发送成功”判定网卡已切换。原服务单次失败后不会自动重试。手动重启同一切换服务一次后实际进入c812，NetworkManager自动取得原IP，摄像头14.9fps、Playground恢复。现已加入上述有界重试；**修复后的再次完整断电验收仍需现场完成**，本轮手动恢复不能代替它。

## 故障定位与恢复

Wi-Fi不可达时，通过临时USB调试线/ADB或本地屏幕读取下列状态；先保留本次启动日志，避免直接反复重启覆盖证据。

```sh
lsusb
ip -br address
systemctl list-units 'roarm-wifi-switch*' --all
systemctl status roarm-wifi-usb --no-pager
systemctl status roarm-wifi-switch@2-1.1.service --no-pager
journalctl -b -u roarm-wifi-switch@2-1.1.service --no-pager
nmcli device status
```

`2-1.1`是本次实际网卡端口示例，按lsusb/sysfs/服务列表替换。达到重试上限时先读取原因，再用`systemctl reset-failed roarm-wifi-switch@实际端口.service`及`systemctl start roarm-wifi-switch@实际端口.service`恢复。不要重启整个Hub或解绑机械臂作为常规修复。

## 完整断电验收

保持正式接线，切断RK、机械臂和Hub全部供电，再恢复。无需ADB手工切换或nmcli手工连接，应在启动后取得无线IP、SSH可达、Playground可访问、真实视频连续更新、真实T1051反馈持续更新。若使用了手工恢复，整次无人干预冷启动应记录为未通过。

验收同时检查`programs.json`与`grasp.json`持久化。板端时钟无网络时可能退回2023年；使用boot_id、uptime和单调时间判断本次启动，联网后再核对NTP。上位机手势/语言模型是独立进程，需要按host手册重新启动，不能用RK网页自启动代替其恢复。
