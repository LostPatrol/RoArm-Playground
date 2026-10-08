<!-- 项目入口：功能边界、目录、开发验证及 RK3588 部署入口。 -->
# RoArm-Playground

基于 RoArm-M2 与 RK3588 的机械臂互动实验项目，用于面向初中生的 AI 与 Agent Vibe Coding 演示。当前实现无线视频、网页控制和实机测试，把 USB 摄像头预览、机械臂原生控制页面和真实关节反馈放在同一页面。

## 当前功能

- USB 摄像头动态发现、MJPEG 视频、快照及断线重试。
- 同源代理机械臂原生页面与指令，保留角度、坐标、LED 等原生入口。
- 按键请求串行化、松键/失焦停车、页面退出时逐轴停止持续运动。
- RTL8822CU USB 模式切换、systemd/udev 配置及设备诊断。
- 只读系统检查与有限范围运动复测，保存真实反馈和图像。

四轴已实测能运动；底座、肩、肘仍存在到位误差。本项目后续普通场景不以高精度定位为要求。ROS 2 集成、视觉抓取、语音与 IMU 随动尚未实现，详见 [实测基线](docs/baseline.md) 和 [演示方向](docs/scenarios.md)。

## 目录

| 路径 | 用途 |
|---|---|
| `rk3588/` | 视频与控制服务、部署脚本、USB/无线诊断和运动测试 |
| `tests/` | 本机模拟测试，不向实体机械臂发送指令 |
| `docs/` | 开发、公开仓库范围与实测基线 |

平台参考资料：[RK-Vison 视觉平台介绍（PDF）](docs/RK-Vison视觉平台介绍20211115.pdf)。

本地 `agent/` 保存任务、执行报告、研究过程；`rk3588/system-test/` 保存现场原始证据。这些资料保留于开发机，未纳入公开仓库。

## 本机开发

已使用 Ubuntu 24.04、系统 OpenCV/NumPy；ROS 2 Jazzy 是本机现有环境，当前网页服务不依赖 ROS。

```sh
sudo apt-get install python3-venv python3-opencv python3-numpy
sh rk3588/bootstrap_python.sh
.venv/bin/python -B tests/test_camera_server.py
node tests/test_arm_adapter.js
```

Node.js 仅用于 JavaScript 模拟测试，不是设备运行依赖。依赖与公开文件范围见 [开发说明](docs/development.md)。

## RK3588 部署

摄像头与 RTL8822CU 网卡接 USB-A Hub，RK3588 独立供电。参考设备实际运行 Ubuntu 20.04.6 / aarch64 / Linux 5.10.198；开发机与设备系统版本不同。

完整步骤见 [RK3588 部署与复测](rk3588/README.md)。部署脚本支持目标 IP 与 `ROARM_SSH_KEY`；首次安装先创建设备 Python 环境。设备特定驱动二进制包保留在本地，公开仓库不携带该归档。

网页“停止持续运动”针对 T123；断网时无法保证请求送达，也不能代替固件任务或硬件急停。运动复测脚本会实际驱动机械臂，运行前确认现场空间并避免多个控制来源同时操作。
