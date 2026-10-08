<!-- 视觉模块接口、依赖、能力边界与逐项验收手册；设备与开发机共用。 -->
# 视觉展示及验收

`rk3588/vision.py` 使用 OpenCV 与 NumPy，在 Python 3.8 及以上运行；基础模块最初在项目 `.venv` OpenCV 4.6.0 验证，YuNet 增强版本在本机4.11验证、设备需4.8及以上。全部检测框是画面内归一化坐标，**不表示桌面位置、末端位置或机械臂运动目标**。

## 安装与接口

开发机：`bash scripts/fetch_vision_models.sh`。默认写入项目 `models/`；可传入其他目录。脚本下载固定 YOLOX-Nano 0.1.1rc0 ONNX（约 3.6 MB）、YuNet 2023mar ONNX（约232KB，SHA256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`）及 OpenCV 4.6.0 Haar 模型，校验 SHA256 后才完成落盘；可重复执行。设备可复制模型到 `/opt/roarm-camera/models/`，设置 `ROARM_MODEL_DIR=/opt/roarm-camera/models`。主部署说明需与实际设备安装位置一致。

Python 依赖为现有 OpenCV、NumPy；Haar 通常由 `opencv-data` 提供，模型脚本亦下载一份。标记需要 `cv2.aruco` 与 `DICT_APRILTAG_36h11`，实际板端4.8具备。跟踪只用基础 OpenCV 光流，不需要板端缺失的 CSRT，也没有新增模型/依赖。不需要 CUDA、PyTorch、ONNX Runtime。视觉明确走CPU并关闭板端会编译失败的OpenCL自动路径。缺模型、缺标记字典或算法失败会返回 `error`，不自动生成替代检测结果。

```python
from vision import VisionEngine
engine = VisionEngine()  # 或显式传入模型目录
print(engine.capabilities())
result = engine.process(frame, "color", {"color": "red"})
# frame 为 uint8 BGR NumPy 图像；其他 mode: face/markers/objects/track/foam/manual。
engine.set_target(frame, {"x": .2, "y": .2, "w": .3, "h": .3})
tracking = engine.process(next_frame, "track")
changes = engine.difference(before, after)
panorama, error = engine.stitch(frames)
```

公共结果包含 `detections`、`width`、`height`、`elapsed_ms`；检测项包含 `label,x,y,w,h,cx,cy,confidence`，标记与物体另含 `id`。框和中心坐标都在 0..1 内。Haar、标记、颜色、泡沫、模板跟踪的 `confidence` 不是神经网络类别概率，结果中的 `confidence_kind` 给出具体含义。`capabilities()` 的 `available` 描述依赖是否具备，不代表现场验收完成。

## 共用准备

1. 保持摄像头画面可用、光照适中；先验证视频、检测结果和真实状态更新，再启用机械臂随动。
2. 摄像头固定在夹爪附近并随末端运动。每种展示都先选择观察姿态；机械臂移动会改变画面，不能把固定相机算法的结论直接用于运动后的画面。
3. 识别和随动分开验收。先观察目标框；再以低速、大致居中为目标，测试控制方向、目标丢失与模式退出。无需高精度位置标准。
4. 实机测试记录输入、结果、耗时和失败现象。本文的算法验证不能替代下面的现场验收。

自动随动对人脸、颜色、标记、框选目标统一使用水平底座与肘部俯仰，以串口实测角度为基线，约100ms刷新比例目标、不等待到位；默认4%画面死区、底座单次上限8°、肘部6°、速度500舵机steps/s。检测耗时和串口往返会限制实际刷新率，这些参数不表示已经测得10Hz。手动运动会关闭该模式自动运动，保留视觉识别；重新启动跟随恢复自动运动。停止/切换项目会清除旧框。

## 1. 寻找观众、亮灯致意（face）

实现：优先 YuNet 2023mar 神经网络，OpenCV FaceDetectorYN CPU，默认真实模型得分≥0.8，结果 backend 明确显示 YuNet。设备 OpenCV 4.8、本机上位机环境 OpenCV 4.11支持此模型。无 YuNet 时保留显式 Haar fallback 与 warning，其 confidence 为存在标志1；曾在真实无人墙面/桌椅画面误检，不得用该误检宣称有人。也可显式传 `face_backend=haar` 做对照。此功能不识别人脸身份或情绪。

验收：

1. 固定观察姿态，先验证无人墙面/桌椅没有人脸框；再让一名观众正对摄像头，在约 0.5–1.5 米处缓慢左右移动；网页框应随实际脸部移动。
2. 用空墙或离开画面进行反例；不得持续显示旧脸框。
3. 再启用寻找/致意模式，观察水平/俯仰跟随、灯光和点头；致意期间识别继续而自动随动暂停，结束后继续跟随。观众离开超过2秒后重新允许致意，两次致意至少间隔8秒；退出模式停止寻找。转动中暂时模糊可容许短时丢失。
4. 记录正面和侧脸差异、逆光失败；侧脸、人脸过小、遮挡、复杂背景是已知限制。

YuNet 回归：本机 OpenCV4.11 真正推理官方 Lena，人脸得分约0.909；真实无人墙面/桌椅 `task02-camera-before.jpg` 为零检测，约15ms。该无人画面先前 Haar 误检两张脸，保留这一失败历史；单张回归不等于现场人脸联动验收通过。

## 2. 魔法指挥棒（color）

实现：HSV 分割、开闭运算及面积过滤。默认红色，支持 `red/green/blue/yellow`；也可传 `lower/upper` HSV 三元组，OpenCV H 为 0..179，S/V 为 0..255。红色覆盖 hue 两端。`min_area` 默认占画面 0.15%。

验收：

1. 选定颜色，持明显大于噪点的彩卡或指挥棒，置于浅色背景；框的位置、大小应贴合实际色块。
2. 换成其他颜色，选定颜色框应消失；将界面颜色改为新颜色后应重新检出。
3. 用同色小点检查面积过滤；背景同色物件可能成为候选，需通过布置场景减少干扰。
4. 启用随动，左右及上下移动彩卡验证双轴方向；拿走彩卡后不得依靠旧位置继续跟随。

## 8. 视觉标记寻宝（markers）

实现：AprilTag `tag36h11` / OpenCV `DICT_APRILTAG_36h11`，与本机 `ros2-ardupilot-sitl-hardware/correction_service` 的配置和检测源码一致。兼容旧 `detectMarkers` 与新 `ArucoDetector`。编号是实际解码结果，返回 `family` 和四个归一化 `corners`，网页可标出标签边界；这里只解码，不估计3D位姿。

验收：

1. 使用同款tag36h11纸张，或以 `cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)` 生成标记；保留白色边距，纸张平整，以约8–12cm边长开始测试。旧4×4 ArUco纸张已不适用。
2. 依次展示两个不同编号，网页编号及位置应分别对应；普通二维码和随机黑白纸不应被认作这些编号。
3. 逐步增加距离、倾斜及遮挡，记录失效范围；丢失时清除框并提示没有目标。
4. 打开寻宝搜索，目标出现后转向大致目标方向；搜索扫描范围按现场线缆与碰撞空间限制。不能据此宣称已测全周旋转。

可在本机用 `cv2.aruco.drawMarker(dictionary, 17, 400)`（旧版）或 `generateImageMarker`（新版）生成标记；打印前四周添加白边。

## 9. 常见物品识别与竞猜（objects）

实现：官方 YOLOX-Nano ONNX，416×416 原始 BGR 输入、值 114 补边，不做 `/255`；OpenCV DNN CPU 推理、三尺度解码、同类 NMS。使用 COCO 80 类，类别并不覆盖所有物品。

验收：

1. 确认能力页显示模型存在；移走模型后应明确显示模型缺失，不能展示假框。
2. 在干净背景准备瓶子、杯子、书、手机等实际可识别物，逐个入镜，核对类别与框。默认阈值 0.35，可在选项中调 `confidence`。
3. 拿出模型不认识的物品，观察误报并记录；竞猜界面不得把任何颜色轮廓当成神经网络检测。
4. 测试连续使用至少一分钟，记录设备推理耗时、视频连续性、温度和负载。CPU 较慢时降低识别刷新频率，保持原视频流。

真实参考图算法验证：使用 YOLOX 官方 `assets/dog.jpg`，本机检测 dog≈0.855、bicycle≈0.803、car≈0.798，一次约 98 ms。此结果仅验证模型加载、预处理、推理、解码的完整链路；不代表 RK3588 现场帧率或桌面物品准确率。

## 11. 点击框选目标并追踪（track）

实现：用户框选后提取最多80个角点，Lucas-Kanade前后向光流及RANSAC估计平移/缩放/平面旋转；至少6个有效角点、前后误差小于1.5像素、外观误差与内点比例过滤减少漂移。可靠跟踪帧更新近期模板，同时保留初始模板，以0.75/1/1.25倍率全画面相关匹配重捕获（默认门槛0.65）。只用板端已有OpenCV，不下载新模型。目标至少8×8像素，拒绝无纹理区域；无法跟踪/重捕获时 `lost=true`、`track_confidence=0`、空检测，不保留旧框。

验收：

1. 选择有明显图案或边缘的物体，并让框含物体及少量边缘；纯色区域应提示纹理不足。
2. 手持目标连续左右/上下移动，适度改变距离、缓慢旋转；框应随实际图案移动，先仅验证识别，再启用双轴随动。
3. 将目标完全移出画面，确认提示丢失；目标丢失时运动控制不得继续使用旧框。
4. 测试遮挡后的重新捕获和停止/切换项目后的框清除。大幅三维翻面、快速运动模糊、长时遮挡、重复纹理仍可能丢失/误锁；没有训练物品身份模型，失效时重新框选。
5. 摄像头分辨率变化后应提示重新选择；随动摄像头的运动也会改变目标尺度与背景。

## 12. 机器人全景摄影师（stitch）

实现：OpenCV 真正特征拼接。至少两幅有重叠的图像；找不到特征、单应矩阵失败或相机参数优化失败时返回明确原因，不用横向贴图替代拼接。

验收：

1. 先固定肩、肘等姿态，只在可行小扇区内分段转动底座；每次停止并等画面清晰后拍照。
2. 选择有丰富纹理、尽量远处的场景；相邻照片保留约 40–60% 重叠。首轮从两三幅开始。
3. 检查输出确实对齐重叠物体、宽度超过单帧，并观察重影；近处物体的视差、移动观众与曝光差可能导致失败或重影。
4. 对空白墙、无重叠照片测试失败提示。拼接成功仅说明图像结果可展示，不等同于已完成 360° 机械扫描验收。

算法验证：三幅从 800×360 纹理画布裁切的重叠图片，真实拼接输出约 798×360；两幅纯色帧明确返回特征不足。

## 13. 机器人找不同（difference）

实现：固定相机的平滑后绝对差、阈值和轮廓框。默认变化阈值 30（0..255），结果另含 `changed_fraction`。没有自动语义说明“拿走了杯子”。

验收：

1. 在稳定光照和完全相同的机械臂姿态拍基准照片；保持摄像头固定。
2. 移走或移动桌上一件物品，再拍照片；变化框应覆盖实际变化区域，物品移走后的原位置也是合理变化。
3. 用相同照片对比应无变化框；故意转动摄像头，界面需提醒这种对比不满足固定视角条件。
4. 开关室内灯或移动影子，记录误报；相机自动曝光和画面振动都可能被认为变化。

## 17. 黑色泡沫识别入口（foam）

实现：受控绿色桌面下的低饱和度+相对亮度轮廓提取，只报告 `dark_foam_candidate`。默认 `S<=100`；`dark_threshold=220`是上限，实际V门槛为ROI内亮度75分位的0.88倍与上限的较小值，`parameters.effective_dark_threshold`可查看。这避免把自动曝光下V约210的浅色空桌面当黑块，也保留V约170而桌面约205的曝光场景。细长阴影/线缆与整幅暗图过滤仍生效。分数改用轮廓面积/凸包面积，避免斜视立方体只占轴向框一半而被显示低分；分数不是材质概率。灰桌面、键盘等暗物仍可能成为候选，不鉴别材质、不推算深度。

可传 `roi:[x,y,w,h]` 或 `roi:{x,y,w,h}`，数值归一化且区域必须完全在图内。该次桌面视角可用 `roi:[0,0.35,1,0.65]` 减少顶部杆误检，返回框仍对应完整原图。全黑面积超过整幅75%的过滤继续保留。ROI和阈值仅针对观察姿态与实际场景选择，不做普适性保证。

验收：

1. 先人工选择能看到桌面且不碰撞的观察姿态，在受控绿色桌面上放黑色泡沫；网页应显示实际块位置。
2. 拿走泡沫、放入其他黑色物体，明确说明算法会将其他暗物体也列为候选；不得宣称这是材质识别。
3. 如果观察姿态看不到桌面或泡沫，无目标是真实结果，应记录待协助问题。
4. 抓取必须另外校验相机与夹爪、桌面及物体关系；本模块没有提供能替代手眼几何的坐标，不能用检测框宣称抓取成功。

真实照片回归：肘部约135°观察姿态下，泡沫在原图约x150..434、y247..底部；新版候选框约x148..432、y250..480，与实际可见块对应。加桌面ROI后，顶部杆候选消失。通过 `ROARM_FOAM_REAL_IMAGE` 显式启用这一准备场景用例，照片只保留在 `agent/codex`；此结果不能证明夹爪接触或物体离桌。

## 本地验证与复测

```bash
# 项目 Python，不使用系统 Python 替代。
.venv/bin/python -m unittest discover -s tests -p test_vision.py -v
# 可选真实模型验证；样例过程文件放 agent/codex，不进入功能代码。
ROARM_VISION_REAL_IMAGE=agent/codex/yolox-dog.jpg \
  .venv/bin/python -m unittest discover -s tests -p test_vision.py -v
```

测试涵盖双区间红色、面积噪声过滤、颜色切换、HSV、自定义错误、黑块候选、AprilTag36h11编号与角点、模型缺失、多帧平移/缩放/旋转光流跟踪、模板更新/丢失/重捕获、找不同、真拼接成功和失败、无效输入。真实图像测试通过环境变量显式启用；没有文件时显示跳过，不能算作真实推理已通过。`ROARM_FOAM_TASK3_IMAGE` 可启用用户task3截图的空桌面误检回归。

来源：[YOLOX 官方 ONNX 使用说明](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/demo/ONNXRuntime/README.md)、[YOLOX 官方模型发布](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0)、[OpenCV FaceDetectorYN](https://docs.opencv.org/4.x/df/d20/classcv_1_1FaceDetectorYN.html)、[OpenCV YuNet模型](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)、[OpenCV ArUco](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html)、[OpenCV Stitcher](https://docs.opencv.org/4.x/d8/d19/tutorial_stitcher.html)。
