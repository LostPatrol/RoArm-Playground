<!-- 当前开发基线：串口Playground、分端依赖、测试与公开范围；2026-10-09。 -->
# 本机开发与仓库维护

优先开发/演示平台为Ubuntu 24.04 / Python 3.12；本机现有ROS 2 Jazzy，Playground不依赖ROS。Python运行使用项目 `.venv/bin/python`。`bootstrap_python.sh`创建使用系统OpenCV/NumPy的基础环境；完整手势环境安装[host固定依赖](../host/requirements.txt)，当前项目venv为OpenCV contrib4.11/NumPy1.26.4。设备Ubuntu20.04/Python3.8保持OpenCV4.8/NumPy1.24，音频只安装Vosk依赖，不安装整套上位机包。

当前首页与 `/api/state`、`/api/action`采用RK3588 USB串口，动作不经ESP32无线代理。模型、启动步骤与迁移说明见[部署复现](playground/deployment.md)和[host说明](playground/host.md)；CPU Qwen导演已经真实构建/推理，4060/CUDA路径尚未实测。

## 验证

```sh
sudo apt-get install python3-venv python3-opencv python3-numpy
sh rk3588/bootstrap_python.sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_arm_adapter.js
bash -n rk3588/deploy_camera.sh scripts/fetch_vision_models.sh scripts/fetch_interaction_models.sh host/build_director.sh host/run_director.sh
sh -n rk3588/bootstrap_python.sh rk3588/install_rtl8822cu.sh
node --check rk3588/arm_adapter.js
node --check rk3588/playground.js
```

Python测试覆盖串口适配、模式/程序并发与取消、视觉算法、host方向绑定、音频及USB切换资源生命周期；历史HTTP代理和USB sysfs模拟测试保留。JavaScript测试使用模拟DOM/XHR。2026-10-09冷启动修复后全套Python测试66/66通过（camera7、host9、playground19、vision19、wifi12），真实图像样本补齐，无skip。图像测试需配置部署说明中的样本路径；缺样本明确skip，不能计作通过。这些检查不能替代真人互动和实体抓取。实际完整断电结果见[开机联网](wifi-startup.md)。Node.js仅用于开发测试。

## 公开范围

公开源码、正式测试、systemd/udev配置和部署文档。`.gitignore`排除Python环境、缓存、模型下载文件、凭据文件、含本机凭据的 `AGENTS.md`、内部 `MEMORY.md`、`agent/` 和现场原始测试目录。模型以固定URL、版本与SHA256下载脚本复现。当前结果见[状态表](playground/status.md)；[baseline.md](baseline.md)保留task01历史及未通过项。

本地 `rtl8822cu-5.10.198.tar.gz` 内含四个 ARM64 内核模块与两份固件，适用于特定设备内核。公开整理时不分发这份二进制归档；它不是通用安装包。驱动来源为 [lwfinger/rtw88 固定提交](https://github.com/lwfinger/rtw88/tree/a56bcd26e770257612a0803249cbd4095fc6feca)，在目标设备内核头文件下编译。重新构建需遵循上游说明，并自行核对固件来源、分发条款与对应源码；本次整理不新增未经验证的重建脚本。

没有该归档时，仍可在已具备网络的 RK3588 部署摄像头与网页控制服务；`install_rtl8822cu.sh` 的本地模块安装步骤则需要先提供匹配的归档。

## 部署文档

本机保留 `rk3588/README.md` 和 `docs/playground/`。`deploy_camera.sh`备份旧程序、文档与systemd单元，同步完整串口/调度/视觉/网页/host资源、视觉模型和验收手册到 `/opt/roarm-camera/`。中文模型首次单独复制，设备运行数据在 `/var/lib/roarm-playground/`。网页自动管理板端音频worker，停止/切换同时结束arecord；DynamicUser子进程显式使用该数据目录作为HOME。

每次代码任务在本地 `agent/report/`新增报告并维护 `MEMORY.md`。默认使用 `main`，公开仓库为[LostPatrol/RoArm-Playground](https://github.com/LostPatrol/RoArm-Playground)。
