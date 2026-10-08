<!-- 当前自动板端音频、上位机手势与CPU导演：部署、实测与验收边界；2026-10-09。 -->
# 手势、语音、拍手与本地导演

默认支持另一台Ubuntu 24.04 / Python 3.12笔记本。手势在上位机读取RK3588 `/snapshot.jpg`；中文语音和拍手默认由网页自动启动板端worker，读取UQ212麦克风，无需再开终端重复启动。停止、切换模式或转为手动关节控制会结束旧worker及arecord；切到另一音频模式时由新worker接管麦克风。

这些功能共享 Playground 的 `/api/state`、`/api/perception`、`/api/action`。同一时刻只让前端选中的模式产生动作。`--dry-run` 完全不发 POST，也不读取模式；可用本地图片/WAV验真实模型。

## Ubuntu 24.04 安装

在复制到演示笔记本的工程根目录创建项目环境，模型与环境不入 Git：

```bash
sudo apt-get install python3.12-venv alsa-utils libportaudio2 git curl cmake build-essential
python3.12 -m venv .venv
.venv/bin/python -m pip install -r host/requirements.txt
bash scripts/fetch_interaction_models.sh all
```

手势固定 MediaPipe 0.10.21，使用真正的 Gesture Recognizer 模型。其发行包依赖 OpenCV contrib；该环境锁定 `opencv-contrib-python==4.11.0.86`、`numpy==1.26.4`，并固定 JAX/SciPy 等关键依赖，防止自动升级 NumPy 2。**不要在 RK3588 的 `/opt/roarm-camera/.venv` 安装整套 `requirements.txt`**，以免覆盖设备已有 OpenCV 4.8。

下载脚本先验证既有文件，下载使用 `.part`，校验成功后再替换正式文件。每个模型旁保存 `.sha256` 和 `.source.txt`，再次运行可离线复验已下载文件；模型及附属文件均在 `models/`。

| 模型 | 固定来源/版本 | 文件 SHA256 |
|---|---|---|
| MediaPipe Gesture Recognizer float16 | Google发布的模型版本1 | `97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482` |
| Vosk中文小模型 | `vosk-model-small-cn-0.22.zip`，42MB | `3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba` |
| Qwen2.5-1.5B-Instruct Q4_K_M | 官方GGUF仓库提交 `91cad51170dc346986eccefdc2dd33a9da36ead9`，约1.12GB | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |

来源：[MediaPipe Python指南](https://developers.google.com/edge/mediapipe/solutions/vision/gesture_recognizer/python)、[Vosk官方模型](https://alphacephei.com/vosk/models)、[Qwen官方GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)。

## 手势与猜拳

```bash
.venv/bin/python -m host.worker --server http://RK-IP:8080 --mode gestures
```

前端启动“手势”或“猜拳”，手势 worker 才发送动作。`Open_Palm→open`、`Closed_Fist→fist`、`Victory→victory` 是模型内置分类；另外约定 `Thumb_Up→left`、`Thumb_Down→right`，方便水平控制。不能把拇指指向判定当成真实空间左右追踪。

每个有效手势需置信度≥0.65并持续3帧；相同姿势只触发一次，放下手或换姿势后才能再次触发，动作间隔至少1.5秒。默认最多8fps处理；每帧发布归一化手框与分类结果。

```json
{"kind":"hands","detections":[{"x":0.3,"y":0.2,"w":0.2,"h":0.5,"label":"fist","confidence":0.9}],"gesture":"fist","confidence":0.9}
```

模式为 `gesture/rps` 时动作格式是 `{"action":"gesture","gesture":"fist","confidence":0.9}`。前端可用 `/api/state` 内的 host 感知结果画框；worker 会在真正发动作前再次读取模式。

离线验收命令：

```bash
.venv/bin/python -m host.worker --mode gestures --image /absolute/path/hand.jpg --dry-run
```

已用 Google 官方 `victory.jpg`、`fist.jpg` 图片实际推理，分别得到 `victory=0.7728`、`fist=0.9003`。官方 `right_hands.jpg` 双手图片得到 `open=0.6025`，低于动作阈值，因此该图片不能证明张手动作已通过。真人张手/握拳/剪刀、课堂距离和灯光、真机动作联动仍需现场测试；静态图片与模拟接口通过不替代这些测试。

## 中文离线语音与拍手

当前设备的常规演示只需打开网页“中文语音”或“拍手律动”，点击启动并等待音频状态在线。板端默认设备为 `hw:CARD=UQ212,DEV=0`、16kHz双声道。模式停止后应显示worker停止，麦克风进程退出。

笔记本麦克风的只读诊断示例（`--dry-run`不发送动作）：

```bash
arecord -l
.venv/bin/python -m host.worker --mode speech --audio-device default --dry-run
.venv/bin/python -m host.worker --mode clap --audio-device default --dry-run
```

语音使用 Vosk 真正的中文声学/解码模型，把结果发送为 `{"action":"speech","text":"向左看"}`；它不是只按字符串返回预设识别结果。原始识别去掉中文词间空格，只有解码成完整片段后发出。可识别的运动口令由后端固定映射决定，未知内容不会交给通用模型直接执行。前端模式分别是 `voice`、`clap`。

拍手采用16kHz PCM的短时音量上升检测，有0.6秒间隔与持续音量边沿判定，**没有声称使用神经拍手分类器**。`--clap-threshold 0.10` 可按现场麦克风增益调整。敲桌、大声喊叫也可能触发，需要课堂噪声实测。live麦克风默认丢弃启动预热0.5秒（`--audio-warmup`可显式调整），WAV完整读取；音频worker每2秒发布独立 `kind=speech/clap,worker_status=running` 心跳，即使演示模式未激活也能区分在线与未连接，dry-run不发布心跳。

板端只装 `host/requirements-vosk.txt`；Python3.8无需MediaPipe/JAX/CUDA，也不更改摄像头OpenCV。当前设备已安装；以下用于首次复现和停止网页模式后的只读诊断，常规网页演示无需手工启动：

```bash
/opt/roarm-camera/.venv/bin/python -m pip install -r /opt/roarm-camera/host/requirements-vosk.txt
cd /opt/roarm-camera
.venv/bin/python -m host.worker --mode speech \
  --audio-device hw:CARD=UQ212,DEV=0 --channels 2 --dry-run
```

默认用声卡名定位UQ212；更换麦克风先用 `arecord -l` 核对并配置后端 `--audio-device`。双声道在worker内下混为单声道。模型复制到设备 `models/`，或手工诊断用 `--speech-model` 指定。无需升级NPU runtime；避免自动和手工worker同时读取同一麦克风。

systemd使用DynamicUser，Vosk导入时需要解析用户HOME；首次托管启动曾因缺HOME报 `getpwuid`。当前控制器给音频子进程显式设置 `HOME=/var/lib/roarm-playground`。修复后已从网页启动voice/clap各运行9秒，均收到 `running` 心跳，停止均变为 `stopped`。这是实际自动启停链路测试，不是仅用root手工运行样本代替；真人喊口令/拍手仍待验收。

```bash
.venv/bin/python -m host.worker --mode speech --wav /absolute/path/16k-mono.wav --dry-run
```

本机与RK3588都已真实解码公开的5.592秒中文样本 `zh.wav`，输出“开放时间早上九点至下午五点”，与公开样本内容一致；[样本说明](https://k2-fsa.github.io/sherpa/onnx/sense-voice/python-api.html)。本机完整进程含模型加载2.36秒、最大RSS约188MiB。这证明中文模型推理与WAV读取可运行，不证明固定口令准确率或教室噪声适应已通过。

2026-10-08已把正式 `host/` Python模块和中文模型部署到RK3588 `/opt/roarm-camera`，只安装Vosk 0.3.45及其依赖；安装前后设备OpenCV仍为4.8.0、NumPy仍为1.24.4，路径没有变化。正式ZIP在板端SHA256复验通过。

板端以 `arecord -D hw:1,0 -f S16_LE -r 16000 -c 2 -d 5` 真实采到5秒UQ212音频，双声道下混后RMS=0.1477（−16.61dBFS）、峰值=1.0、约1.07%样本削顶，Vosk输出空文本。幅度异常集中在开头：前两个100ms块RMS为0.9388/0.4513，300ms后最大0.0101、平均0.00570，符合录音启动瞬态。原始WAV dry-run拍手误报1次，保留失败证据；据此加入仅针对live麦克风的0.5秒预热，保持原始WAV不变。当前设备Mic为62%/11dB，未改增益。**录音链路可用，真人讲话/拍手和教室噪声准确率仍未验收**。

板端公开样本完整推理含模型加载3.240秒，文本正确；此结果不是连续语音吞吐或现场端到端动作延迟。

预热修正后板端live拍手worker以 `--dry-run` 连续采音6秒，输出0个拍手事件，没有录音启动误报；仍未做真人拍手命中测试。

设备证据留在 `/opt/roarm-camera/audio-test`，同步到开发机 `agent/codex/task02-audio`。这次板端测试全部离线/`--dry-run`，没有发出任何动作POST。可重复进行只读幅度与识别检查：

```bash
.venv/bin/python -m host.audio_probe /absolute/path/recording.wav \
  --model /absolute/path/vosk-model-small-cn-0.22
```

## 本地LLM导演

使用真正的 llama.cpp OpenAI兼容推理服务，没有模型时直接报错，不用规则计划冒充LLM。默认采用CPU方案，避免把3080的CUDA环境当成4060笔记本的强制条件：

```bash
bash scripts/fetch_interaction_models.sh llm
bash host/build_director.sh cpu
bash host/run_director.sh cpu
.venv/bin/python -m host.director '先亮灯，再向左转十度，等待一秒，然后打招呼'
```

构建固定 llama.cpp `b4514` / `ec7f3ac9ab33e46b136eb5ab6a76c4d81f57c7f1`。源码/构建过程放在 `agent/codex/llama.cpp-b4514`；CPU构建关闭 `GGML_NATIVE`，可在另一台x86笔记本重建，默认6线程、2048上下文。约1.12GB量化模型给16GB内存笔记本保留空间；实际4060笔记本性能尚未测试。

可选GPU方案需要目标机器已有兼容NVIDIA驱动和支持Ada架构的CUDA编译器（CUDA 11.8或更新）：

```bash
bash host/build_director.sh cuda
bash host/run_director.sh cuda
```

构建同时指定 `86;89`，对应RTX3080与RTX4060；不依赖本机特定Python Torch/CUDA轮子。本轮实测CPU，GPU构建与目标笔记本尚未验收。`LLAMA_SERVER`、`LLAMA_SOURCE_DIR`、`DIRECTOR_MODEL_FILE` 可覆盖路径，`DIRECTOR_THREADS` 可调整线程。

默认服务只监听 `127.0.0.1:8081`。RK3588调用笔记本服务时显式使用局域网监听：

```bash
DIRECTOR_HOST=0.0.0.0 bash host/run_director.sh cpu
```

随后把主后端的 `--director-url` 指向 `http://笔记本IP:8081/v1`，`--director-model roarm-director`。这是课堂局域网服务，不应做公网端口映射；默认主后端未配置导演服务时应显示未连接。

`host.director.plan(text,url,model)` 只返回预览，最多12步，不能自己发送 `/api/action`。最终格式：

```json
{"steps":[{"type":"led","value":255},{"type":"joint","joint":"base","delta":10},{"type":"wait","seconds":1},{"type":"greet"}],"explanation":"亮灯，向左转十度，等待后致意"}
```

真正模型选择动作、方向和角度；内部模型schema使用 `direction` 枚举和0..20的整数 `degrees`，由协议方向绑定表编译成上述 `joint/delta`。左右唯一对应底座、上下唯一对应肘、开合唯一对应夹爪，避免小模型选出互相矛盾的关节和方向；明确要求特定关节增加/减少角度时才同时选 `joint` 与 `increase/decrease`。绑定表只读取模型结构化输出，不读取用户文本，不产生替代计划。底座左正右负、肘抬头负低头正、夹爪张开负合拢正；非法关节/方向组合拒绝。输出还独立校验LED 0..255、关节增量±20、等待0..5秒及全部字段，模型结果必须在前端审核后明确执行。

首次真实Qwen1.5B直接生成正负delta时多次弄错左转/右转与夹爪符号，因此保留错误记录并改为语义方向绑定；不能以JSON格式正确宣称语义正确。任意自然语言、复杂动作、安全性与事实理解均未全面验收，即使基础指令通过也须保留预览审核。

修正后的真实CPU回归5条全部得到正确动作/角度：左转10度后致意、右转15度＋张开10度、左转5度＋合拢5度、向右看8度等待2秒、左转12度关灯。首条8.555秒，其余2.170—2.678秒。该成绩仅对应这5条基础指令，没有发送任何真机运动。

## 运行检查与证据

```bash
.venv/bin/python -m unittest tests.test_host_worker -v
bash -n scripts/fetch_interaction_models.sh host/build_director.sh host/run_director.sh
```

单元测试检查模式切换后不发旧动作、dry-run没有网络写入、手势去重、PCM双声道下混、持续大音量不重复拍手、麦克风启动瞬态丢弃与采音进程清理、LLM接口预览及schema边界、模型方向到物理符号的绑定。它们使用本地模拟HTTP服务，不冒充真模型或真机联动。

真实离线模型证据保存在本开发机 `agent/codex/gesture-*.json`、`asr-public-zh-result.json`、`director-real-*.json` 与 `director-llama-cpu.log`；不会作为运行依赖部署。网络/摄像头/arecord出错时 worker 清晰退出，处理设备故障后重新启动即可。
