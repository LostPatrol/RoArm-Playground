<!-- RTL8822CU开机联网机制、失败恢复与冷启动验收边界；2026-10-09。 -->
# USB网卡开机联网

本项目的RTL8822CU网卡初次通电可能枚举为`0bda:1a2b`驱动光盘；正确无线模式为`0bda:c812`。这两个ID不能当成两个不同网卡。网卡与摄像头接USB-A Hub，机械臂由RK Type-C串口连接。

`roarm-wifi-usb.service`设置已知网卡的usb-storage忽略标志；udev规则按实际USB端口启动`roarm-wifi-switch@端口.service`。程序精确匹配bus/dev，解除该虚拟光盘的storage驱动占用，再用现有libusb消费最多8个512字节旧应答包，每次读取超时1秒。队列清空后关闭接口，单独发送标准EJECT，检查真实ID变为c812后加载驱动。切换失败每3秒重试，180秒内最多4次启动，单次最长40秒，包含USB清理/切换/确认预算。成功后不再重试；NetworkManager沿用已保存的`roarm-demo-wifi`自动联网。机制不依赖固定Hub端口号或DHCP地址。

2026-10-09首次完整断电验证发现切换失败：网卡保持1a2b，没有无线接口，SSH/网页不可达。原服务单次失败后不会自动重试；手动恢复后首次增加有界重试，但第二次完整断电的四次重试仍失败，因此重试本身没有解决问题。

随后读到18字节遗留数据及两条13字节旧CSW，清理后单EJECT真正成功、设备进入c812并自动联网。此前单独USB复位、接口重新配置、BOT复位和单EJECT都未恢复。

新路径的第三次正式接线完整断电验证已通过：新boot_id、内核记录初始1a2b→约10.4秒枚举c812；切换服务首次执行成功，NRestarts=0，执行约2.82秒。NetworkManager自动取得原IP，SSH/Playground可达，相机与机械臂真实反馈正常。连续30.03秒收到448视频帧（14.92fps），73/73状态请求串口在线、73个不同反馈时间戳；程序/抓取示教持久化保留。全程未发机械臂运动命令。

usb_modeswitch2.5.2的`-K`先发送准备指令，第一条响应错误就跳过后面的真正EJECT。−8代表响应溢出，日志的“Device is gone”不是实际USB断连证据。实现参考[官方源码包](https://www.draisberghof.de/usb_modeswitch/usb-modeswitch-2.5.2.tar.bz2)和[libusb溢出说明](https://libusb.sourceforge.io/api-1.0/libusb_packetoverflow.html)。清理步骤通过Python标准库ctypes使用usb-modeswitch已依赖的libusb，不新增pip依赖。不会切共享Hub电源。

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

本次联网后时钟已自动同步。时间大幅跳变使部分早期journal被轮转；结合systemd保留的退出状态、单调起止时间、boot_id与dmesg核对启动，不补造缺失的stdout。USB清理/故障路径新增12项模拟测试，完整工程66项通过；模拟检查和上述实体证据分别保留。
