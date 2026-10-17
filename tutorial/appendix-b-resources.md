<!-- 附录B：延伸资源索引，只给官方入口与用途，不罗列教程链接。 -->
# 附录 B 资源索引

> 用法：这里只放**入口**，不放教程。每个条目写清"去看什么"，而不是"这个网站好"。课堂要求的知识都已写在前十三章，本附录用于课后自学。

## B.1 模型与产品的官方入口

| 资源 | 地址 | 看什么 |
|---|---|---|
| Anthropic（Claude） | https://www.anthropic.com | 产品能力、模型文档、API 说明 |
| OpenAI | https://openai.com | 模型家族与 API 文档；对比用 |
| Google Gemini | https://deepmind.google/models/gemini/ | 多模态能力与公开评测 |
| 通义千问 | https://tongyi.aliyun.com | 国内可用服务与 API 控制台 |
| DeepSeek | https://www.deepseek.com | 开放模型权重与技术报告 |
| 智谱 GLM | https://www.zhipuai.cn | 国内模型与开发者平台 |
| 月之暗面 Kimi | https://kimi.moonshot.cn | 长上下文场景 |
| 豆包 / 火山引擎 | https://www.volcengine.com | 国内 API 与语音、图像服务 |
| Mistral | https://mistral.ai | 欧洲开源权重模型 |
| Meta Llama | https://www.llama.com | 开放权重模型与许可条款 |

> 提醒：价格、可用地区、模型版本随时变化，一律以官网为准。本课程不提供任何价格承诺。

## B.2 本地运行

| 资源 | 地址 | 用途 |
|---|---|---|
| llama.cpp | https://github.com/ggml-org/llama.cpp | C/C++ 推理引擎，GGUF 格式的事实标准 |
| Ollama | https://ollama.com | 一条命令拉起本地模型的封装工具 |
| LM Studio | https://lmstudio.ai | 图形界面的本地模型管理器，适合初学者 |
| vLLM | https://docs.vllm.ai | 服务端高吞吐推理框架 |
| Hugging Face | https://huggingface.co | 模型与数据集托管；看 model card 与许可证 |
| ModelScope（魔搭） | https://modelscope.cn | 国内镜像与中文模型 |

## B.3 模型与框架

| 资源 | 地址 | 用途 |
|---|---|---|
| PyTorch | https://pytorch.org | 主流训练框架与教程 |
| TensorFlow | https://www.tensorflow.org | 另一主流框架，部署生态成熟 |
| OpenCV | https://opencv.org | 传统视觉与轻量推理，边缘设备常用 |
| ONNX | https://onnx.ai | 跨框架的模型交换格式 |
| Ultralytics YOLO | https://docs.ultralytics.com | 目标检测的常用实现 |
| MediaPipe | https://ai.google.dev/edge/mediapipe/solutions/guide | 手势、姿态、人脸等端侧方案 |
| Vosk | https://alphacephei.com/vosk | 离线语音识别 |
| whisper.cpp | https://github.com/ggml-org/whisper.cpp | 本地语音识别 |
| ComfyUI | https://www.comfy.org | 节点式图像生成工作流 |

## B.4 Agent 与开发工具

| 资源 | 地址 | 用途 |
|---|---|---|
| Claude Code | https://www.anthropic.com/claude-code | 终端内的编程 Agent |
| Model Context Protocol | https://modelcontextprotocol.io | 工具接入协议规范 |
| GitHub | https://github.com | 代码托管、Issue、Actions |
| Git 官方文档 | https://git-scm.com/doc | 版本管理基础 |
| Cursor | https://cursor.com | 集成 Agent 的编辑器 |
| OpenHands | https://github.com/All-Hands-AI/OpenHands | 开源 Agent 平台，适合研究其内部循环 |

## B.5 数据集与评测

| 资源 | 地址 | 用途 |
|---|---|---|
| Hugging Face Datasets | https://huggingface.co/datasets | 公开数据集入口 |
| Papers with Code | https://paperswithcode.com | 论文、代码与榜单对照 |
| LMSYS Chatbot Arena | https://lmarena.ai | 人类偏好的模型对比 |
| Open LLM Leaderboard | https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard | 开源模型基准分数 |
| COCO | https://cocodataset.org | 目标检测/分割标准数据集 |
| ImageNet | https://www.image-net.org | 图像分类基准 |

> 看榜单的三个纪律：看评测日期、看评测方法、看是否与你的任务同分布。榜单分数高不等于你的场景好用。

## B.6 硬件与机器人

| 资源 | 地址 | 用途 |
|---|---|---|
| 矽递 Seeed Studio | https://www.seeedstudio.com | RoArm 系列机械臂与开发板 |
| RoArm 文档 | https://www.seeedstudio.com/RoArm-M2-S.html | 产品页与资料入口 |
| 乐鑫 Espressif | https://www.espressif.com | ESP32 系列芯片与 SDK |
| ROS 2 文档 | https://docs.ros.org | 机器人软件框架（本项目未使用，可作扩展） |
| ArduPilot | https://ardupilot.org | 开源飞控，无人机项目常用 |
| OpenCV ArUco | https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html | 标记检测与位姿估计 |

## B.7 课程项目相关

本课程的机械臂案例即仓库自身。读代码的顺序建议：

1. `README.md` —— 项目是什么、怎么跑；
2. `docs/playground/README.md` —— 18 项功能的入口表；
3. `docs/playground/status.md` —— 每一项实测到了哪一层；
4. `rk3588/playground.py` —— 模式协调与动作程序；
5. `rk3588/vision.py` —— 各类感知的实现与失败边界；
6. `host/director.py` —— 语言模型如何被收窄成安全动作。

每一步都对照第 12 章的"说得出 / 跑得通 / 测得过 / 现场看得见"四层去读，会比顺着文件读快得多。

## B.8 三条使用建议

- **优先读官方文档**，其次读模型卡（model card）与许可证，最后才看二手教程。二手教程常常滞后一到两个版本。
- **看到数字先问来源**：谁测的、什么硬件、什么输入。没有这三项的"提升了 300%"一律不可信。
- **把链接当起点，不当结论**。本课程要求的判断必须由你自己完成一次：打开页面、找到那句话、看它是否支持结论。
