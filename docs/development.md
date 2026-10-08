<!-- 本机开发与公开仓库整理说明：依赖、检查命令、文件范围和部署文档策略。 -->
# 本机开发与仓库维护

本机基线为 Ubuntu 24.04 / ROS 2 Jazzy。仅使用项目 `.venv/bin/python` 运行 Python；`bootstrap_python.sh` 使用系统 Python 创建环境，并通过 `--system-site-packages` 使用系统 OpenCV、NumPy，不额外下载 pip 包。

## 验证

```sh
sudo apt-get install python3-venv python3-opencv python3-numpy
sh rk3588/bootstrap_python.sh
.venv/bin/python -B tests/test_camera_server.py
node tests/test_arm_adapter.js
bash -n rk3588/deploy_camera.sh
sh -n rk3588/bootstrap_python.sh rk3588/install_rtl8822cu.sh
node --check rk3588/arm_adapter.js
```

Python 测试使用回环地址模拟机械臂服务和 USB sysfs；JavaScript 测试使用模拟 DOM/XHR。它们验证代理、指令顺序与界面逻辑，不能替代真实摄像头、运动和断电启动验收。Node.js 需由本机另行安装，仅用于开发测试。

## 公开范围

公开源码、正式测试、systemd/udev 配置和部署文档。`.gitignore` 排除 Python 环境、缓存、凭据文件、含本机凭据的 `AGENTS.md`、内部 `MEMORY.md`、`agent/` 和现场原始测试目录。原始资料仍留本机；历史事实集中整理于 [baseline.md](baseline.md)，保留未通过项。

本地 `rtl8822cu-5.10.198.tar.gz` 内含四个 ARM64 内核模块与两份固件，适用于特定设备内核。公开整理时不分发这份二进制归档；它不是通用安装包。驱动来源为 [lwfinger/rtw88 固定提交](https://github.com/lwfinger/rtw88/tree/a56bcd26e770257612a0803249cbd4095fc6feca)，在目标设备内核头文件下编译。重新构建需遵循上游说明，并自行核对固件来源、分发条款与对应源码；本次整理不新增未经验证的重建脚本。

没有该归档时，仍可在已具备网络的 RK3588 部署摄像头与网页控制服务；`install_rtl8822cu.sh` 的本地模块安装步骤则需要先提供匹配的归档。

## 部署文档

本机保留 `rk3588/README.md`。`deploy_camera.sh` 将该文档与三份服务资源同步至设备 `/opt/roarm-camera/`，并备份原有资源、文档和 systemd 单元。每次代码任务另在本地 `agent/report/` 新增执行报告，并维护 `MEMORY.md`。默认使用 `main`，公开仓库为 [LostPatrol/RoArm-Playground](https://github.com/LostPatrol/RoArm-Playground)。
