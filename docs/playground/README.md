<!-- Playground入口、真实基线与18项独立验收手册；2026-10-09。 -->
# RoArm Playground

打开 `http://<RK3588地址>:8080/`。页面提供18个项目入口、实时视频、真实关节反馈、三维几何示意、统一控制和事件。选择卡片会结束上一自动模式；点击“启动实验”才开始新模式。

控制链路为 **浏览器/上位机 → Wi-Fi → RK3588 → USB串口 → 机械臂**。板上CPU执行轻量视觉和中文语音；上位机负责手势模型和可选本地语言模型。无需访问ESP32无线控制页。

先阅读[当前实现与实测状态](status.md)、[集中待处理事项](blockers.md)和[部署复现](deployment.md)。软件存在、样本模型推理、API注入、真实现场互动是不同验证层级，状态表分别说明。

| 序号 | 展示项目 | 独立验收手册 |
|---|---|---|
| 1 | 寻找观众、亮灯致意 | [人脸](acceptance/01-face.md) |
| 2 | 彩色指挥棒 | [颜色跟随](acceptance/02-color.md) |
| 3 | 手势遥控 | [手势](acceptance/03-gesture.md) |
| 4 | 中文语音控制 | [语音](acceptance/04-voice.md) |
| 5 | 拍手导演与节奏律动 | [拍手](acceptance/05-clap.md) |
| 6 | 动作示教、记忆与回放 | [示教](acceptance/06-teach.md) |
| 7 | 图形化动作编程 | [积木](acceptance/07-program.md) |
| 8 | 视觉标记寻宝 | [标记](acceptance/08-markers.md) |
| 9 | 常见物品识别与竞猜 | [检测](acceptance/09-objects.md) |
| 10 | 和机器人猜拳 | [猜拳](acceptance/10-rps.md) |
| 11 | 点击框选并追踪 | [跟踪](acceptance/11-track.md) |
| 12 | 全景摄影师 | [全景](acceptance/12-panorama.md) |
| 13 | 找不同 | [差异](acceptance/13-difference.md) |
| 14 | 真实反馈驱动的三维机械臂 | [三维](acceptance/14-digital.md) |
| 15 | 自然语言小导演 | [导演](acceptance/15-director.md) |
| 16 | 现场Agent改规则 | [现场修改](acceptance/16-agent.md) |
| 17 | 黑色泡沫识别与抓取尝试 | [泡沫](acceptance/17-foam.md) |
| 18 | ESP32＋IMU头部随动 | [随动](acceptance/18-imu.md) |

实现细节与模型依据：[视觉模块](vision.md)、[上位机/板端音频与模型](host.md)。产品资料参考 [RoArm-M2-S Wiki](https://www.waveshare.com/wiki/RoArm-M2-S)、[运动协议](https://www.waveshare.com/wiki/RoArm-M2-S_Robotic_Arm_Control)。Wiki直接访问可能403，字段交叉核对厂家公开固件源码，未推测未验证的重置/力矩参数。
