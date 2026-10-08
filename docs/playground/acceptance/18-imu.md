<!-- 18-imu 功能验收；软件测试与现场验收分别记录。 -->
# ESP32＋IMU头部随动

现场状态：**待实测**。最终结论统一以 [状态表](../status.md) 为准；本文列验收方法，不预先宣布通过。

## 目的

接收真实传感器姿态，校准中立位后映射底座/肘部；单独验证模拟输入接口。

## 所需物品与前置

ESP32、姿态传感器、供电、固定方式与实际姿态算法；设备与RK服务网络可达。服务器地址通过配置传入，不写死主机IP。硬件尚未接入前仅验模拟链路。

可选 [ESP32＋MPU6050参考固件](../../../firmware/esp32_imu/README.md) 提供不依赖外部传感器库的发送端；它未经Arduino编译与硬件验证，且不代表用户已经确定选用该传感器。

## 网页操作

1. 打开“头部随动”，先观察是否标注模拟。
2. 拖动“左右/俯仰”滑块后点击“发送模拟姿态”（simulated:true），确认页面角度更新；未经校准不应运动。校准后点击“启用真实随动”，模拟角也会驱动真实机械臂，必须把输入来源和实体动作分别描述。
3. 接入真实 ESP32/IMU 后，以 simulated:false 发送实际角度；头部居中，点击“设为中立姿态”，建立机械臂初始姿态，再启用随动。
4. 小幅左右转头、抬低头，观察底座与肘部大致同向随动；确认方向后再扩大范围。
5. 切换模式并继续发数据，检查不继续驱动；测试断流及重新校准。

## 通过标准

模拟子项只验协议/页面/调度，明确标模拟。硬件子项须保存真实传感器读数与对应实体动作，校准前不动，退出IMU模式不动；方向正确、大致随动即可。必须分别记录模拟与真实硬件结果。

## 自动测试

在项目根目录使用项目 `.venv/bin/python`。

运行 `.venv/bin/python -m unittest discover -s tests -v` 检查调度、校准与状态；模拟 POST 仅说明接口通，不证明 IMU 测量、漂移或头部随动。

## 现场未验收

ESP32固件、实际传感器型号、安装方向、姿态漂移、无线延迟、断流行为与真实机械随动待实测；硬件接入前维持正在开发。

## 失败定位

收到数据不运动：确认 mode=imu 且已校准；正负相反：修正传感器坐标和安装方向。角度跨 ±180° 时须在发送端做连续角处理；当前接口不补偿IMU漂移。断流不等于全系统物理急停，应记录现有行为。

记录日期、软件版本、输入物品/人员、实际效果与失败现象；保存关键状态、截图或录像，不把自动测试结果替代实体证据。

## 姿态协议与示例

现有入口是 **HTTP POST /api/action，底层TCP**，不是裸 TCP JSON socket；当前没有 UDP 监听接口。ESP32 可直接用 HTTPClient 发请求。若硬件只发 UDP，需单独实现/验证 UDP→HTTP 转发，不能直接向 HTTP 端口发送 UDP 后宣称连接成功。

JSON 字段：`action="imu"`；`yaw`、`pitch` 为有限数值，单位度；`simulated=false` 仅用于来自真实传感器的读数。网页模拟必须传 `true`。目前 roll 不参与运动映射。约 5–10Hz 输入足够初测，后端运动节流约0.4秒；不以提高频率代替真实反馈。

```bash
# 地址从现场配置获取；校准前只接收状态，校准后在IMU模式会控制机械臂。
roarm_server='http://<RK主机地址>:8080'
curl --noproxy '*' --fail "$roarm_server/api/action" \
  -H 'Content-Type: application/json' \
  --data '{"action":"imu","yaw":8,"pitch":-3,"simulated":true}'
```

真实 ESP32 请求示例（伪变量仅代表需接入的真实传感器值）：

```cpp
// serverUrl 来自配置；yawDeg/pitchDeg 必须来自真实姿态估计。
HTTPClient http;
http.begin(serverUrl + "/api/action");
http.addHeader("Content-Type", "application/json");
String payload = "{\"action\":\"imu\",\"yaw\":" + String(yawDeg, 2)
               + ",\"pitch\":" + String(pitchDeg, 2) + ",\"simulated\":false}";
int status = http.POST(payload);
http.end();  // 记录非2xx响应，检查连接及服务日志。
```

校准调用为 `{"action":"imu_calibrate"}`，读取当前 yaw/pitch 为中立值，并读取真实机械臂关节姿态。模式调用为 `{"action":"mode","mode":"imu"}`。当前映射是底座初始角+yaw相对中立变化、肘部初始角+pitch相对中立变化，发送端需按安装方向确定符号。不得将固定生成的数字标为真实IMU。
