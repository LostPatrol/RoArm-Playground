<!-- Native Windows host deployment, operation, and verification boundaries. -->
# Windows 演示笔记本

Windows 原生运行8082模型管理器、MediaPipe手势/猜拳识别和8081真实Qwen导演。浏览器访问RK3588网页；相机、USB串口、板端视觉、中文语音/拍手、示教/程序及运行数据继续由RK提供。无需WSL、虚拟机、Docker、CUDA Toolkit或Visual Studio。

默认项目目录 `D:\RoArm-M2`；使用已有 `D:\softwares\miniconda\python.exe` 的Python3.12创建独立 `.venv`，不修改Miniconda基础环境。安装脚本不安装或更新驱动。CUDA不兼容时先诊断或使用CPU备用；涉及笔记本原有驱动的变更必须先询问用户。

## 安装

先把项目源码复制或通过Git获取到 `D:\RoArm-M2`。在PowerShell运行：

```powershell
Set-Location D:\RoArm-M2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File host\install_windows.ps1
```

其他Python3.12位置可通过 `-Python 'D:\path\python.exe'` 指定。脚本安装 `host/requirements.txt`，下载与现有Linux方案相同的固定手势和Qwen模型并校验SHA256；使用[llama.cpp b4514官方Windows发布](https://github.com/ggml-org/llama.cpp/releases/tag/b4514)的AVX2程序、CUDA12.4程序及配套cudart DLL。模型来源和SHA见[上位机说明](host.md)。

目标机无法访问GitHub时，可在开发机使用`git bundle create main.bundle main`，复制归档到笔记本后用`git fetch D:\path\main.bundle main`获取提交，再按正常Git流程更新源码；模型和运行库也可从已校验的开发机文件复制。无需改变其他项目的Git代理配置。

| 目录 | 内容 |
|---|---|
| `.venv` | 项目Python与依赖 |
| `models` | `gesture_recognizer.task`、`qwen2.5-1.5b-instruct-q4_k_m.gguf`及来源/SHA记录 |
| `tools\llama-b4514\cpu` | 原生AVX2 `llama-server.exe`及DLL |
| `tools\llama-b4514\cuda` | 原生CUDA `llama-server.exe`、DLL和配套cudart |
| `data\cache` | pip缓存和安装归档 |
| `data\temp` | 安装/运行临时文件 |
| `data\host-manager` | 管理器及模型进程日志 |

已有模型和已解压工具可先复制到表中路径，再执行 `host\install_windows.ps1 -SkipDownloads`；仍会安装Python依赖并校验模型SHA。只复制归档、没有展开程序时不能使用此参数。CUDA程序及cudart DLL必须放在同一目录。安装空间按长期3–5GB、峰值6–8GB估算，首次安装建议D盘预留10GB；实际占用以目标笔记本测量为准。任务计划和防火墙等Windows配置由系统保存，不承诺C盘零写入。

## 启动与网页使用

手工启动时，保持这个PowerShell窗口打开；默认使用CUDA，可显式选CPU：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File host\start_windows.ps1 -Backend cuda
# CPU backup:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File host\start_windows.ps1 -Backend cpu
```

RK地址变化时增加 `-Server 'http://RK新地址:8080'`。管理器启动时加载导演；手势worker由网页“尝试连接/加载本机模型”启动。`ROARM_DIRECTOR_BACKEND=cpu|cuda`控制manager默认程序路径；`LLAMA_SERVER`、`DIRECTOR_MODEL_FILE`、`DIRECTOR_CONTEXT`、`DIRECTOR_THREADS`可覆盖程序、模型和推理参数。

在笔记本浏览器打开 `http://192.168.112.122:8080/`，进入手势、猜拳或导演页面，点击加载本机模型。通常使用浏览器所在笔记本的地址；必要时填写 `http://笔记本IP:8082`。如果网页来自另一台电脑或手机，需要填写实际Windows上位机地址。导演先生成预览，再由用户确认执行。加载模型本身不会启动运动模式。

在管理员PowerShell中配置登录启动和限定RK来源的防火墙规则：

```powershell
Set-Location D:\RoArm-M2
# Stop a manually launched manager before registering the task.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File host\install_windows_startup.ps1 -RkAddress 192.168.112.122 -Backend cuda
```

任务名为 `RoArm-M2 Host`，当前用户登录时以交互身份启动，使用最高权限，电池供电也允许运行；启动脚本在manager异常退出后等待3秒重新加载，计划任务负责登录启动。注册时会停止同名旧任务并立即启动新实例，因此不要同时保留手工运行的manager。防火墙规则 `RoArm-M2 Host RK` 只允许指定RK IP访问TCP8081/8082，包含Public网络。RK IP变化时重新运行注册脚本更新规则与服务地址。笔记本IP变化时更新网页的上位机地址。此任务以登录为边界，不提供无人登录时启动的保证。

manager负责恢复自身启动的worker；Windows job在manager退出或被强制终止时清理子进程，避免旧导演占用端口。manager恢复后导演重新加载，手势需要再次从网页加载。

首次CUDA推理可能因缓存生成而较慢，演示前先生成一次预览；`data\cache\cuda`保留GPU缓存。`ready`表示模型已加载，首次请求速度需另行检查；CPU备用首次预览也可能耗时几十秒。

## 检查与维护

```powershell
Get-ScheduledTask -TaskName 'RoArm-M2 Host'
Get-ScheduledTaskInfo -TaskName 'RoArm-M2 Host'
Get-NetFirewallRule -DisplayName 'RoArm-M2 Host RK' | Get-NetFirewallAddressFilter
Invoke-RestMethod http://127.0.0.1:8082/api/status
Invoke-RestMethod http://127.0.0.1:8081/health
Get-ChildItem data\host-manager
Get-Content (Get-ChildItem data\host-manager\manager-*.log | Sort-Object LastWriteTime | Select-Object -Last 1).FullName -Tail 30
```

`ready`必须来自真实模型初始化或llama `/health`，不能仅凭进程PID判断。需要停止托管服务时运行 `Stop-ScheduledTask -TaskName 'RoArm-M2 Host'`；恢复运行使用 `Start-ScheduledTask`。依赖或模型缺失时查看8082响应中的路径与安装命令。删除旧日志和缓存前先停止相关安装/运行；不要删除正式模型、venv或运行DLL。

Windows PowerShell5.1无法用 `ConvertFrom-Json` 解析RK反馈中同时存在的 `T`/`t`键。完整设备状态改用项目Python读取：

```powershell
.venv\Scripts\python.exe -c "import json; from urllib.request import build_opener,ProxyHandler; r=build_opener(ProxyHandler({})).open('http://192.168.112.122:8080/api/state'); print(json.dumps(json.load(r),ensure_ascii=False))"
.venv\Scripts\python.exe -m host.worker --mode gestures --image 'D:\path\hand.jpg' --dry-run
.venv\Scripts\python.exe -m host.director '先亮灯，再向左转五度' --url http://127.0.0.1:8081/v1
```

修改Windows部署入口看 `host/*.ps1`；改进程管理/平台路径看 `host/manager.py` 与 `host/windows_job.py`；改识别或计划看 `host/worker.py` 与 `host/director.py`；网页连接上位机由RK的 `playground.py` / `playground.js`负责。

## 功能覆盖与验收边界

当前已实现的软件功能沿用原有RK链路；Windows新增运行环境覆盖手势/猜拳和真实语言导演。中文语音/拍手继续使用RK麦克风与Linux `arecord`，无需移植到笔记本麦克风。抓取、IMU等原有未完成功能保持[状态说明](status.md)中的边界，本适配不将它们标记为完成。

依赖导入、静态手势图片、真实LLM预览、LAN连接、任务恢复和网页访问分别验证。样本推理和接口通过不替代现场真人手势/语音、远场噪声、实际动作联动或完整18项演示验收；机械臂普通演示不以高精度定位为要求。实际部署结果与未通过项记录于任务报告；[各项现场验收手册](acceptance/)用于后续演示检查。
