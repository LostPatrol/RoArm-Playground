<!-- Ubuntu24笔记本与RK3588部署复现；2026-10-09。 -->
# 部署与复现

优先演示操作系统Ubuntu24.04/Python3.12；RK3588保持Ubuntu20.04/Python3.8/OpenCV4.8，无需升级系统或NPU运行时。

## 接线与协议

USB摄像头/网卡→USB-A Hub→RK3588，RK独立供电；Type-C→机械臂USB/ESP32口，不能误接LADAR。采用唯一CP2102N的`/dev/serial/by-id/`，多候选时指定`--serial-device`。

启动只读T105，不写初始化/重置/力矩。网页角度为度；T101为rad、速度为整数steps/s，T102用base/shoulder/elbow/hand完整字段。控制经RK串口，旧ESP32无线命令入口不使用。

## 演示笔记本

模型与依赖详细版本见[host.md](host.md)。工程根目录首次安装：

```bash
sudo apt-get install python3.12-venv python3-opencv python3-numpy alsa-utils libportaudio2 git curl cmake build-essential
python3.12 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r host/requirements.txt
bash scripts/fetch_vision_models.sh
bash scripts/fetch_interaction_models.sh all
```

实际Python均用项目环境。本机MediaPipe依赖在venv中使用OpenCV contrib4.11/NumPy1.26.4，未覆盖设备库。手势在笔记本运行：

```bash
.venv/bin/python -m host.worker --server http://RK-IP:8080 --mode gestures
```

只在网页gesture/rps模式输出动作。CPU导演服务另开终端：

```bash
bash host/build_director.sh cpu
DIRECTOR_HOST=0.0.0.0 bash host/run_director.sh cpu
```

CPU构建固定llama.cpp提交、关闭GGML_NATIVE，已实际构建/推理。CUDA选项包含86/89架构，但4060/CUDA未实测；CPU路径可保留，速度需在演示笔记本重新测。

将`rk3588/roarm-director.conf.example`复制到设备`/etc/systemd/system/roarm-camera.service.d/director.conf`，替换LAPTOP-IP，再`systemctl daemon-reload && systemctl restart roarm-camera`。地址变更只改配置；模型输出先预览，点击执行才运动。

## RK3588

首次项目环境见[rk3588说明](../../rk3588/README.md)。板端仅安装Vosk依赖：

```bash
/opt/roarm-camera/.venv/bin/python -m pip install -r /opt/roarm-camera/host/requirements-vosk.txt
```

不要在设备安装整套host/requirements.txt。将校验后的中文模型目录复制到`/opt/roarm-camera/models/vosk-model-small-cn-0.22/`；需要alsa-utils。本轮已安装和验证。

```bash
bash scripts/fetch_vision_models.sh
bash rk3588/deploy_camera.sh RK-IP
```

脚本先备份旧程序/文档/systemd，再同步串口、调度、视觉、网页、host、视觉模型和全部手册；不自行下载或升级依赖。中文模型首次另行复制，脚本不反复覆盖。下载脚本固定SHA，支持已有模型离线复验。

源码在`/opt/roarm-camera/`；动作程序、抓取示教和图像在`/var/lib/roarm-playground/`。systemd用video/dialout/audio组和StateDirectory。设备保留`/opt/roarm-camera/docs/playground/`，开发机保留同份`docs/playground/`。

网页语音/拍手启动板端音频worker，停止/切换结束worker及arecord。默认`hw:CARD=UQ212,DEV=0`、双声道16k、0.5秒预热；更换麦克风配置`--audio-device`。独立上位机worker也可使用，但同模式不要同时启动两路音频输入。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_arm_adapter.js
node --check rk3588/playground.js
bash -n rk3588/deploy_camera.sh scripts/fetch_vision_models.sh scripts/fetch_interaction_models.sh host/build_director.sh host/run_director.sh
```

真实图像测试用`ROARM_VISION_REAL_IMAGE`、`ROARM_VISION_FACE_IMAGE`、`ROARM_VISION_EMPTY_IMAGE`、`ROARM_FOAM_REAL_IMAGE`指定物品、人像、无人场景及泡沫本地样本；缺样本明确skip，不能计作通过。模拟测试不连接实体机械臂。

systemd DynamicUser下音频子进程HOME指定到运行数据目录，避免Vosk缓存路径查询系统账户失败；子进程退出会在状态与事件中提示，详细原因查`journalctl -u roarm-camera`。

实体测试按[18份手册](README.md)保存真实反馈、照片及失败。回滚先停止当前模式，再恢复设备backup目录的整套资源和原单元；保留程序/图像历史。
