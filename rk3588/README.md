<!-- 部署与复测说明：2026-10-08 task01 同屏控制、运动反馈及 USB-A Hub 基线。 -->
# RK3588 摄像头与无线网络

目前无线网络、摄像头与原生机械臂同屏控制已部署。task01 实测底座、肩、肘、夹爪均能运动，但底座/肩/肘到位误差未通过 0.5° 标准；夹爪 −10° 测试通过。先前 1° 无位移的记录仍保留，不能将“能运动”视为精确到位。自动识别抓取等场景尚未实现。

## 已验证的连接

摄像头和网卡连接新 Hub，Hub 接 RK3588 的 USB-A。RK3588 使用独立 12V/2A 电源，Type-C 可接本机用于 ADB 调试，也已验证拔掉 Type-C 数据线后无线及视频继续工作。不要把旧 Type-C Hub 方案当成可用方案。

- RK3588：rd-rk3588，Ubuntu 20.04.6，aarch64，Linux 5.10.198，约 15 GiB 内存。
- Hub：Genesys Logic，USB ID 05e3:0610。
- 网卡：RTL8822CU，正常无线模式 0bda:c812，接口 wlx90de807ab292；光盘模式 0bda:1a2b。
- 摄像头：UQ212，1bcf:28c4；当前采集节点 /dev/video40，640×480，实测约 15 fps。
- Wi-Fi 使用现场网络；NetworkManager 配置名 `roarm-demo-wifi`，自动连接开启、网卡省电关闭。密码仅保存于设备配置。
- 示例 RK3588 地址 `192.168.112.122`、机械臂地址 `192.168.112.156`；部署时替换为实际 DHCP 地址。

浏览器打开 `http://<RK3588地址>:8080/`，即可查看摄像头、实时关节反馈和原生控制界面；同源 `/arm/` 与 `/arm/js` 将请求转发到机械臂，保留 `/status`、`/snapshot.jpg`、`/stream.mjpg`。桌面及手机宽度已用真实 Chrome 检查，原生底座方向键和 LED 开关已操作；BOOT/getDevInfo 及重启/重置入口被阻断。

界面按住方向键运动，松开、失焦或取消触摸时停止对应轴。上方“停止持续运动”清除四轴 T123 指令；它不负责中断固件任务播放，也不能保证断网时停止请求送达。原生 T123 会同步写所有舵机，停止递增后仍有运动余量。不要让多个控制来源同时操作机械臂。

## Python 环境

本机只运行本项目环境：

```sh
sh rk3588/bootstrap_python.sh
.venv/bin/python rk3588/system_check.py --samples 80 --seconds 60 --output rk3588/system-test/manual-check
```

设备上的项目环境为 `/opt/roarm-camera/.venv`。首次创建环境需要系统 Python 的 venv 模块；运行时通过 `--system-site-packages` 使用系统 OpenCV、NumPy。三个已部署的 Python 服务/工作单元均改用该环境。首次安装可在设备上以 root 执行（已有 OpenCV 时先确认当前版本，避免直接覆盖设备定制包）：

```sh
apt-get install python3-venv python3-opencv python3-numpy
mkdir -p /opt/roarm-camera
python3 -m venv --system-site-packages --without-pip /opt/roarm-camera/.venv
/opt/roarm-camera/.venv/bin/python -c 'import cv2, numpy'
```

## 无线驱动部署

驱动来源 [lwfinger/rtw88](https://github.com/lwfinger/rtw88/tree/a56bcd26e770257612a0803249cbd4095fc6feca)，固定提交 `a56bcd26e770257612a0803249cbd4095fc6feca`，针对设备自身 Linux 5.10.198 头文件编译。本地归档 `rtl8822cu-5.10.198.tar.gz` 含四个 ARM64 模块和两份固件；升级内核需重新编译。该二进制归档没有纳入公开仓库，安装前需自行提供匹配产物；范围说明见 [开发文档](../docs/development.md)。已具备网络的设备可直接部署摄像头服务。

将下面文件放到设备同一目录，以 root 执行 `sh install_rtl8822cu.sh`。设备需要已有 `usb_modeswitch`、`NetworkManager`、Python venv 支持：

- `rtl8822cu-5.10.198.tar.gz`、`install_rtl8822cu.sh`
- `usb-modeswitch-rtl8822cu.conf`、`prepare_wifi_usb.py`、`roarm-wifi-usb.service`
- `switch_wifi_usb.py`、`roarm-wifi-switch@.service`、`80-roarm-wifi-switch.rules`

安装脚本部署模块、固件、项目环境和模式切换单元。启动服务保留原有 usb_storage quirks，添加 `0bda:1a2b:i`；udev 用网卡具体 USB 路径触发工作单元，支持新 Hub 下的 `2-1.1`，避免旧 usb_modeswitch dispatcher 对嵌套端口的处理失败。

**冷启动仍有风险：**此前断电启动时内核提前绑定存储驱动，导致网卡光盘模式切换超时；启动后重新插入网卡曾恢复。新的专用 udev 工作单元已部署，但新 Hub 完全断电启动、从光盘模式自动联网的路径尚未实测，不宣称已修复无人干预冷启动。不要为了复测远程切断唯一无线通道。

## 摄像头部署与调试

设备项目环境准备好后，在本机同步 Python 与两份静态资源（无新增 Python/Node 依赖）：

```sh
bash rk3588/deploy_camera.sh 192.168.112.122
# 使用其他私钥时：
ROARM_SSH_KEY="$HOME/.ssh/your-device-key" bash rk3588/deploy_camera.sh 192.168.112.122
```

脚本将 `camera_server.py`、`control.html`、`arm_adapter.js` 及本文档安装到 `/opt/roarm-camera/`，同步 systemd 单元并重启服务；存在的旧资源、文档和单元保存在设备 `/opt/roarm-camera/backups/<时间>/`，也支持没有旧资源的首次部署。默认私钥为 `$HOME/.ssh/roarm-rk3588`，可用 `ROARM_SSH_KEY` 覆盖。手动部署也必须同步三份功能文件，不能只复制 Python。确认项目环境能导入 OpenCV 和 NumPy，然后运行：

```sh
systemctl daemon-reload
systemctl enable --now roarm-camera.service
curl --noproxy '*' http://127.0.0.1:8080/status
```

服务以动态用户运行，通过 video 附加组访问 USB 摄像头；自动查找真实 USB 视频节点，忽略板载 ISP 的大量节点，摄像头拔插后重新检测。

机械臂 IP 改变时，在设备执行 `systemctl edit roarm-camera.service`，添加以下覆盖后重新启动服务；RK3588 地址改变时直接使用新地址打开控制台：

```ini
[Service]
ExecStart=
ExecStart=/opt/roarm-camera/.venv/bin/python /opt/roarm-camera/camera_server.py --arm-url http://新的机械臂IP
```

测试（不连接真机写入）：`.venv/bin/python -B tests/test_camera_server.py`、`node tests/test_arm_adapter.js`。Node 只用于本机验证，不是设备运行依赖。

本机无线 SSH（专用私钥保存在用户 SSH 目录）：

```sh
ssh -F /dev/null -i "$HOME/.ssh/roarm-rk3588" -o IdentitiesOnly=yes root@192.168.112.122
```

ADB 序列号通过 `adb devices` 获取，本机权限规则为 `70-roarm-rockchip-adb.rules`。Type-C 优先角色已恢复 sink，`roarm-typec-preference.service` 已禁用，仅保留历史实验文件。

## 运动复测

`system_check.py` 只读，不发送运动指令。`motion_check.py` 保留原始 1° 复测。`task01_motion_test.py` 会实际运动，按单轴保存命令、反馈和三张图，并尝试返回起点；每次运行前确认空间，禁止同时运行多个运动测试。例如：

```sh
.venv/bin/python rk3588/task01_motion_test.py --joint 1 --delta-deg 10 --output rk3588/system-test/manual-base-10deg
```

`--joint 1/2/3/4` 分别为底座/肩/肘/夹爪；`--mode jog` 测试原生 T123 按键协议。测试脚本 1–15° 范围只是本轮现场测试限制，不是机械臂能力或界面角度限制。`passed` 要求绝对目标误差和返回误差均小于 0.5°；本轮未调整 PID、力矩或动态适应。原始证据保存在开发机 `system-test/task01/`，未纳入公开仓库；结果与未解决项见下表，本机完整摘要另见 `docs/baseline.md`。

| 项目 | 2026-10-08 已验证结果 | 限制 |
|---|---|---|
| 视频 | 640×480，约 15 fps；拔掉本机 Type-C 数据线后仍工作 | 完全断电联网路径未验收 |
| 四轴运动 | 四轴均能运动，夹爪通过当轮严格标准 | 底座/肩/肘目标或回位误差未通过 |
| 网页 | 桌面/手机布局、底座按钮、LED 命令、INIT 已操作 | Torque OFF/DEFA/坐标运动/拖拽未实机验收 |
| 感知与 ROS | 现有 NPU 单图能执行；厂家 ROS SDK 已评估 | 识别抓取、语音、IMU 随动及 ROS 集成尚未实现 |
