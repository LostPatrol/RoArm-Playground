<!-- RK3588 与机械臂 C-C 连接实测：换到 USB/ESP32 口后，80 次串口反馈通过。 -->
# Type-C 直连测试（2026-10-08）

用户将 RK3588 与机械臂用 Type-C–Type-C 线连接。初次接到雷达口无机械臂反馈，换到 USB/ESP32 口后连续反馈通过。两轮只读取 USB 状态和机械臂反馈，不发送运动、重启、初始化、无线配置或固件修改指令。

## 实测结果

| 项目 | 结果 |
|---|---|
| RK3588 Type-C 数据角色 | host；控制器 `fc000000.usb` 为 host |
| Type-C 电源角色 | source；preferred_role 仍为 sink，没有修改角色配置 |
| USB 设备 | `7-1`，`10c4:ea60`，CP2102N USB to UART Bridge Controller |
| 驱动和节点 | cp210x 已绑定，`/dev/ttyUSB0`，USB 速率 12 Mbps |
| 首次换口检查 | 115200 / 8N1，发送 `{"T":105}\n`，3/3 次收到真实 T1051 回复 |
| 连续串口反馈 | 80/80 成功，中位 24.62 ms、最大 25.19 ms；同时采集视频 |
| 串口输出 | 收到 13,920 字节，包含 80 次命令回显和 80 次真实关节/坐标/负载反馈 |
| 原有 Wi-Fi 机械臂反馈 | 串口测试结束后 3/3 成功，中位耗时 119.2 ms，字段与串口反馈一致 |
| 摄像头 | 30.05 秒收到 449 帧，14.94 fps，640×480 |
| RK3588 启动状态 | 测试前后 boot_id 相同，无主机重启；摄像头服务继续 active |

已验证 RK3588 Type-C 作为 USB 主机，经这根 C-C 线向 ESP32 发送查询并接收真实机械臂反馈；无需切换 Type-C 配置或安装新驱动。网卡和摄像头仍经 USB-A Hub 工作。本轮没有做串口运动测试、断电恢复、供电能力或其它 Type-C 线材兼容性测试。

## 接口核对与初次失败原因

用户最初接在右侧 Type-C。115200/8N1 下 40 次查询无有效反馈，随后 3 次复测均收到 0 字节；同时原有 Wi-Fi 反馈 40/40 成功，视频为 14.95 fps。用户照片与 RoArm-M2-S 厂家图对照：按照片拍摄方向，左侧口对应编号 9 的 `USB`（ESP32 通信口），右侧口对应编号 8 的 `LADAR`（雷达口）。两口各用独立的 USB 转串口芯片，厂家图中编号 25 用于雷达、26 用于 ESP32。

用户换到左侧口后，USB 序列号改变，节点仍为 `/dev/ttyUSB0`，机械臂查询及反馈随即通过。因此初次失败来自接到雷达通道，并非 C-C 线或 RK3588 Type-C 数据功能故障。后续应用应选 ESP32 对应的 `/dev/serial/by-id/` 路径，不能只凭 ttyUSB0 名称判断接对。

接口位置证据：[厂家 RoArm-M2-S 驱动板标注图](https://www.waveshare.com/img/devkit/accBoard/RoArm-M2-S/RoArm-M2-S-details-53.jpg)、[General Driver for Robots 接口说明](https://docs.waveshare.net/General_Driver_for_Robots/)。照片说明与厂家图对照是插口身份判断依据，不以 USB 芯片产品名作为单独证明。

厂家通信参数为 115200、8 数据位、1 停止位、无校验，见 [JSON 指令发送方式](https://docs.waveshare.net/RoArm-M2/JSON-Control/)；接口位置及 USB 口说明见 [RoArm-M2-S](https://www.waveshare.com/wiki/RoArm-M2-S)。

## 测试与证据

临时测试脚本为开发机 `agent/codex/typec_serial_check.py`，只使用项目 Python 和标准库，没有安装新依赖；单次打开串口，不主动切换 DTR/RTS，关闭 HUPCL，不调用厂家会写入初始化命令的 ROS 驱动。USB 串口驱动打开设备时的硬件电平行为没有用仪器测量。

首次误接雷达口的原始证据保存在开发机 `agent/codex/typec-link-20261008/`；换口后的证据另存 `agent/codex/typec-esp32-20261008/`，包括 `usb-before.json`、`usb-after.json`、`serial-smoke.json`、`serial-results.json`、`camera-results.json`、`http-after.json` 和 `host-state-after.txt`。80 次串口测试期间，测试程序只同时采集摄像头，没有并发通过 HTTP 查询机械臂；HTTP 核查在串口关闭后执行。原始证据不纳入公开 Git 仓库。本文同时保存在 RK3588 `/opt/roarm-camera/docs/typec-check-2026-10-08.md`。

现有网页仍走 Wi-Fi/HTTP，未迁移到串口，未关闭 ESP32 Wi-Fi。单无线接口方案所需的有线数据链路已验证；下一步需要在 RK3588 实现串口后端与本地网页资源，才能将实际网页控制切换到该链路。单次测试的延迟不能视为任何负载下的实时保证。
