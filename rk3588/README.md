<!-- RK3588部署入口：USB串口Playground、视频与无线基线；2026-10-09。 -->
# RK3588 RoArm Playground

统一网页提供18项演示入口、USB视频、实际关节反馈及串口运动控制。打开 `http://<RK3588地址>:8080/`。软件实现与现场验收分开记录；抓取和头戴IMU仍开发中。

总说明：[Playground](../docs/playground/README.md)、[实测状态](../docs/playground/status.md)、[部署复现](../docs/playground/deployment.md)、[待处理事项](../docs/playground/blockers.md)。设备同步文档在 `/opt/roarm-camera/docs/playground/`。

## 硬件基线

- rd-rk3588，Ubuntu20.04.6/aarch64/Linux5.10.198，约15GiB内存。
- 新Genesys Hub 05e3:0610接USB-A，RTL8822CU网卡0bda:c812和UQ212摄像头1bcf:28c4接Hub。
- RK3588独立12V/2A供电；Type-C用C-C线接机械臂USB/ESP32口，不能误接LADAR。
- 使用唯一ESP32 CP2102N的 `/dev/serial/by-id/`，115200/8N1；多候选时指定 `--serial-device`。
- 动态发现摄像头，不绑定video40；640×480约15fps。设备OpenCV4.8/NumPy1.24保持。
- Wi-Fi为现场NetworkManager配置 `roarm-demo-wifi`，密码只存设备。DHCP地址可变。

命令链路：浏览器/上位机→Wi-Fi→RK3588→USB串口→机械臂。新运行时 `/arm/` 返回迁移提示；首页使用 `/api/state`、`/api/action`，不向ESP32无线发命令。历史ArmProxy模拟测试保留。

## Python与部署

开发机用项目 `.venv/bin/python`，设备用 `/opt/roarm-camera/.venv/bin/python`。首次设备创建：

```sh
apt-get install python3-venv python3-opencv python3-numpy alsa-utils
mkdir -p /opt/roarm-camera
python3 -m venv --system-site-packages --without-pip /opt/roarm-camera/.venv
/opt/roarm-camera/.venv/bin/python -c 'import cv2,numpy'
```

创建后程序均用项目Python。已有定制OpenCV先核对，不覆盖库。板端ASR安装Vosk0.3.45和已校验中文模型，见部署复现；不要在设备安装笔记本MediaPipe整套依赖。

```sh
bash scripts/fetch_vision_models.sh
bash rk3588/deploy_camera.sh RK-IP
ROARM_SSH_KEY="$HOME/.ssh/your-device-key" bash rk3588/deploy_camera.sh RK-IP
```

脚本备份旧程序/文档/单元，复制完整功能资源、host和视觉模型，再重启服务。数据在 `/var/lib/roarm-playground/`，源码/模型在 `/opt/roarm-camera/`。systemd使用video/dialout/audio组。

默认语音、拍手由网页启动板端USB音频worker；停止或切模式同时结束arecord。默认声卡 `hw:CARD=UQ212,DEV=0`。手势需笔记本运行host.worker；本地导演按 `roarm-director.conf.example` 配置。

```sh
systemctl is-active roarm-camera
curl --noproxy '*' http://127.0.0.1:8080/api/state
journalctl -u roarm-camera -n 40 --no-pager
```

## 使用与检查

卡片切换结束旧自动模式。停止取消程序、逐轴终止T123，再用T102保持实测姿态；物理连接中断时不能保证停车送达。未改PID、力矩、DEFA、BOOT或任务FLASH。

夹爪45..180°，角度减小张开。网页为度；T101/T102为rad，速度100为舵机steps/s。普通演示允许机械误差，模型角度不能证明实体到位。

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_arm_adapter.js
node --check rk3588/playground.js
```

`system_check.py` 的机械臂HTTP检查属于历史Wi-Fi基线；`motion_check.py`、`task01_motion_test.py`保留历史实验，不作为新Playground入口。新现场验收按18份手册执行。

## 无线驱动及边界

rtw88来源 [lwfinger固定提交](https://github.com/lwfinger/rtw88/tree/a56bcd26e770257612a0803249cbd4095fc6feca)，匹配Linux5.10.198。设备特定 `rtl8822cu-5.10.198.tar.gz` 保留本地，未公开分发。已有网络部署不需要重装驱动；首次无线安装需 `install_rtl8822cu.sh` 所列资源。

0bda:1a2b光盘模式切换由专用udev/systemd单元处理。首次完整断电时切换失败，手动重启切换服务后已恢复；现增加3秒间隔、120秒内最多4次的失败重试，修复后完整断电仍待复验。见[开机联网说明](../docs/wifi-startup.md)。旧Type-C Hub仍不作为可用基线。

本轮四轴、颜色跟随、示教/回放、真实全景、CPU导演及模拟IMU已实测。真人互动、全周人物全景、泡沫离桌、IMU硬件、4060/CUDA和冷启动见集中待处理事项，未将未完成项写成通过。
