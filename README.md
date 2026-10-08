<!-- 项目入口：task02串口Playground、真实验收边界、开发与部署；2026-10-09。 -->
# RoArm-Playground

基于 RoArm-M2 与 RK3588 的机械臂互动实验项目，用于面向初中生的 AI 与 Agent Vibe Coding 演示。当前统一 Playground 提供18项演示入口、USB摄像头预览、真实关节反馈和三维几何示意。打开 `http://<RK3588地址>:8080/`，控制链路为浏览器/上位机 → Wi-Fi → RK3588 → USB串口 → 机械臂。

使用入口：[Playground与18份验收手册](docs/playground/README.md)、[当前真实状态](docs/playground/status.md)、[部署复现](docs/playground/deployment.md)、[集中待处理事项](docs/playground/blockers.md)。软件实现、样本推理、动作注入和真人互动分别验收。

## 当前功能

- USB 摄像头动态发现、MJPEG 视频、快照及断线重试。
- USB串口关节/灯光实时滑条、原厂力矩/XYZ/命令控制、三维夹爪拖动、动作取消与实测姿态保持。
- 人脸/颜色/AprilTag36h11/物品检测、双轴连续跟随、移动目标光流跟踪、固定视角找不同与全景拍摄；手动运动与识别共存。
- 示教回放、图形化动作编程、真实反馈三维示意、现场Agent改规则入口。
- 板端Vosk中文语音和拍手worker由网页自动启动，停止/切换时关闭麦克风；上位机MediaPipe手势与猜拳。
- 真正的Qwen1.5B量化CPU导演：自然语言生成有界动作预览，明确确认后执行；网页加载上位机模型与worker。
- RTL8822CU USB 模式切换、systemd/udev 配置及设备诊断。
- 只读系统检查与有限范围运动复测，保存真实反馈和图像。

四轴、颜色跟随、回放、全景与CPU导演已有实体证据，板端Vosk真实中文样本识别成功；18项现场验收尚未全部完成。真人口令、手势/拍手、教室噪声和4060/CUDA仍需测试。完整断电后的自动联网、视频、串口恢复已在USB应答清理修复后通过，见[开机联网](docs/wifi-startup.md)。黑泡沫尚无夹起离桌证据；ESP32＋IMU只有软件接口和模拟输入，二者标为“正在开发”。ROS 2未集成，网页不依赖ROS。机械臂存在到位误差，普通演示不以高精度为要求。

## 目录

| 路径 | 用途 |
|---|---|
| `rk3588/` | 视频与控制服务、部署脚本、USB/无线诊断和运动测试 |
| `host/` | 手势、音频worker及本地LLM导演 |
| `scripts/` | 固定版本与SHA256的视觉/互动模型下载 |
| `tests/` | 本机模拟测试，不向实体机械臂发送指令 |
| `docs/` | 开发、公开仓库范围与实测基线 |

平台参考资料：[RK-Vison 视觉平台介绍（PDF）](docs/RK-Vison视觉平台介绍20211115.pdf)。

本地 `agent/` 保存任务、执行报告、研究过程；`rk3588/system-test/` 保存现场原始证据。这些资料保留于开发机，未纳入公开仓库。

## 本机开发

优先支持Ubuntu 24.04 / Python 3.12演示笔记本。基础服务可使用系统OpenCV/NumPy；完整上位机互动环境另安装固定依赖，当前本机项目venv为OpenCV contrib4.11/NumPy1.26.4，设备仍保留OpenCV4.8/NumPy1.24。详见[上位机与音频说明](docs/playground/host.md)。

```sh
sudo apt-get install python3-venv python3-opencv python3-numpy
sh rk3588/bootstrap_python.sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_arm_adapter.js
node --check rk3588/playground.js
```

Node.js 仅用于 JavaScript 模拟测试，不是设备运行依赖。依赖与公开文件范围见 [开发说明](docs/development.md)。

## RK3588 部署

摄像头与 RTL8822CU 网卡接 USB-A Hub，RK3588 独立供电。参考设备实际运行 Ubuntu 20.04.6 / aarch64 / Linux 5.10.198；开发机与设备系统版本不同。

完整步骤见 [RK3588 部署与复测](rk3588/README.md)。[控制说明](docs/playground/controls.md)与[相机规格](docs/playground/camera.md)说明网页新增入口。部署脚本支持目标 IP 与 `ROARM_SSH_KEY`；首次安装先创建设备 Python 环境。设备特定驱动二进制包保留在本地，公开仓库不携带该归档。

网页停止会取消程序、终止持续运动并尝试保持实测姿态；断网或物理连接中断时无法保证送达。历史HTTP运动复测脚本保留作实验记录，当前现场验收使用Playground手册，避免多个控制来源同时操作。
