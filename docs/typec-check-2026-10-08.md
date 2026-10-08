<!-- RK3588 与机械臂 C-C 连接实测：USB 枚举通过，ESP32 串口反馈未通过。 -->
# Type-C 直连测试（2026-10-08）

用户将 RK3588 与机械臂用 Type-C–Type-C 线连接。本轮只读取 USB 状态和机械臂反馈，不发送运动、重启、初始化、无线配置或固件修改指令。

## 实测结果

| 项目 | 结果 |
|---|---|
| RK3588 Type-C 数据角色 | host；控制器 `fc000000.usb` 为 host |
| Type-C 电源角色 | source；preferred_role 仍为 sink，没有修改角色配置 |
| USB 设备 | `7-1`，`10c4:ea60`，CP2102N USB to UART Bridge Controller |
| 驱动和节点 | cp210x 已绑定，`/dev/ttyUSB0`，USB 速率 12 Mbps |
| 串口反馈 | 115200 / 8N1，发送 `{"T":105}\n`，40 次查询得到 0 次有效 T1051 回复 |
| 单独复测 | 再查询 3 次，每次等待 3 秒，均收到 0 字节 |
| 原有 Wi-Fi 机械臂反馈 | 40/40 成功，中位耗时 114.5 ms |
| 摄像头 | 30.03 秒收到 449 帧，14.95 fps，640×480 |

这证明 RK3588 Type-C 当前可作为 USB 主机，并通过这根线识别对端 USB 串口芯片；不证明 ESP32 控制通道可用，也不证明机械臂的完整供电能力、冷启动恢复或所有 Type-C 线材兼容性。网卡和摄像头仍经 USB-A Hub 工作。

## 接口核对与待复测项

用户随后提供现场照片，说明接在右侧 Type-C。对照 RoArm-M2-S 厂家驱动板图片：按照片拍摄方向，左侧空口对应编号 9 的 `USB`（ESP32 通信口），右侧已插线口对应编号 8 的 `LADAR`（雷达口）。两口各用独立的 USB 转串口芯片，厂家图中编号 25 用于雷达、26 用于 ESP32。因此本轮枚举与无反馈结果来自雷达口，尚未测试正确 ESP32 口。下一步需由用户将机械臂端线换到左侧空口，然后重新核对 USB 序列号、串口枚举和 T1051 反馈；串口编号可能仍为 ttyUSB0，不能凭节点名称区分两个口。

接口位置证据：[厂家 RoArm-M2-S 驱动板标注图](https://www.waveshare.com/img/devkit/accBoard/RoArm-M2-S/RoArm-M2-S-details-53.jpg)、[General Driver for Robots 接口说明](https://docs.waveshare.net/General_Driver_for_Robots/)。照片说明与厂家图对照是插口身份判断依据，不以 USB 芯片产品名作为单独证明。

厂家通信参数为 115200、8 数据位、1 停止位、无校验，见 [JSON 指令发送方式](https://docs.waveshare.net/RoArm-M2/JSON-Control/)；接口位置及 USB 口说明见 [RoArm-M2-S](https://www.waveshare.com/wiki/RoArm-M2-S)。

## 测试与证据

临时测试脚本为开发机 `agent/codex/typec_serial_check.py`，只使用项目 Python 和标准库，没有安装新依赖；单次打开串口，不主动切换 DTR/RTS，关闭 HUPCL，不调用厂家会写入初始化命令的 ROS 驱动。USB 串口驱动打开设备时的硬件电平行为没有用仪器测量。

开发机原始证据保存在 `agent/codex/typec-link-20261008/`：`usb-before.json`、`usb-after.json`、`serial-results.json`、`serial-recheck.json`、`serial-usb-descriptor.txt` 与 `integration/results.json`。原始证据不纳入公开 Git 仓库。本文同时保存在 RK3588 `/opt/roarm-camera/docs/typec-check-2026-10-08.md`。

现有网页仍走 Wi-Fi/HTTP，未迁移到串口，未关闭 ESP32 Wi-Fi。确认正确插口并通过真实反馈测试后，才能采用单无线接口方案。
