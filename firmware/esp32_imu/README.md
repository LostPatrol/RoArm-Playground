<!-- 可选ESP32/MPU6050参考固件：配置、接线、算法、协议和未验证边界。 -->
# 可选 ESP32＋MPU6050 参考发送端

这是供后续硬件接入使用的参考实现，**不是已经替用户确定传感器的方案**。当前没有 ESP32/MPU6050 硬件实测，也没有 Arduino 编译验证；开发机未安装 ArduinoCLI，本轮没有为此安装大型工具链。设备 HTTP 接口已存在，不代表此固件或头部随动已通过。

## 接线与配置

示例针对经典 ESP32 开发板的 I2C 引脚，其他板型按实际配置修改：

| MPU6050 模块 | ESP32 示例 |
|---|---|
| VCC | 3.3V；先核对模块供电规格 |
| GND | GND |
| SDA | GPIO21，可配置 |
| SCL | GPIO22，可配置 |
| AD0 | GND，地址0x68 |
| INT | 本例不接 |

I2C 信号须为3.3V，不把带5V上拉的线路直接接到ESP32。此例未配置0x69地址；若AD0接高电平，需改固件地址并重新检查身份寄存器。

复制 `config.example.h` 为同目录本地 `config.h`，填写 Wi-Fi SSID、密码和 RK 网页服务器地址；示例配置只有占位符。`config.h` 不提交 Git。`ROARM_SERVER` 形如 `http://主机地址:端口`，无末尾斜杠；不要把当前机器IP固化到公开配置。

经典 ESP32 的 Wi-Fi 是2.4GHz。SSID名称带“5G”不能代替实际频段检查；为头戴设备选择可用2.4GHz网络，RK3588可以在同一路由器另一频段，只要两端局域网互通。若选其他ESP32型号，按其实际无线规格核对。

`YAW_SIGN`、`PITCH_SIGN` 初始为1，佩戴方向确认后按实际轴向调整。参考轴定义：z轴大致竖直用于转头，绕y轴用于俯仰；若传感器方向不同，需修改轴映射而不只是盲目改符号。固件不估计roll，也不补偿roll与yaw耦合。

## 工具与构建

只使用 Arduino-ESP32 平台自带 `WiFi`、`HTTPClient`、`Wire` 和标准数学函数，不引入传感器库。候选平台为 Espressif Arduino-ESP32 **2.0.17 或 3.x**；这些属于待编译验证选项，不宣称已经兼容测试通过。先在目标机器选择适合实际板型的已安装版本，记录板型、平台版本和编译输出。

在 Arduino IDE 中打开 `esp32_imu.ino`，选择实际板和串口，再编译、上传。若已有 ArduinoCLI，经典ESP32示例命令为：

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_imu
# 上传前确认具体开发板端口，不把RoArm机械臂ESP32的串口当头戴设备。
arduino-cli upload --fqbn esp32:esp32:esp32 --port <HEAD_TRACKER_SERIAL_PORT> firmware/esp32_imu
```

不能将开发机C++语法检查或本文静态检查写成Arduino编译成功；实际编译需要Arduino core和目标板工具链。

## 实际算法与限制

MPU6050 配置 ±2g、±250°/s，换算分别16384LSB/g、131LSB/(°/s)，低通约42–44Hz，采样目标100Hz。启动保持静止约4秒，对三轴陀螺零偏取平均；检测到显著运动、加速度不接近1g或I2C失败，则停止初始化、不发姿态。

yaw 为z轴去零偏角速度积分产生的**相对角**，不做±180°截断。pitch 使用y轴角速度积分与加速度重力俯仰的互补滤波。六轴没有磁力计或其他航向参考，**yaw会漂移**，运动加速度会影响pitch，简单轴映射不适合大roll和剧烈动作；首次演示只做缓慢、小幅运动，按需要重新启动零偏校准并在网页设置中立位。

HTTP发送最多10Hz，测量间隔使用实际时间；HTTP操作是同步的，会降低采样频率。若网络请求导致超过250ms的未观测间隔，或I2C读取失败，固件锁定停止发送并在串口记录原因，修复后重启。不会以固定零值或最后一帧假装传感器继续工作。这是参考实现的明确限制，长期运行可再评估独立采样任务。

## 联调顺序与协议

1. **先不启用机械随动**。单独给头戴设备供电，静置完成陀螺零偏校准，查看115200串口日志。
2. 确认同网段及服务器可达；固件只发送 `POST /api/action`，不发启动模式、机械臂中立位或任何关节命令。
3. 在网页“头部姿态随动”查看 yaw/pitch，数据必须标为真实输入；小幅转动传感器，先确认符号及角度。
4. 佩戴固定后面朝前，在网页启动IMU、设置中立姿态，再启用真实随动；以最终网页按钮与[验收手册](../../docs/playground/acceptance/18-imu.md)为准。首次开启前仍应确认实体机械臂空间。
5. 退出项目后继续转头，确认后台收包不会重新启动运动；单独检验断流和重启后的重新校准。

真实请求示例：

```json
{"action":"imu","yaw":8.2,"pitch":-3.4,"simulated":false}
```

`yaw/pitch` 单位度，必须来自传感器的实际滤波结果。网络为HTTP/TCP，不提供UDP发送实现；服务器也没有裸UDP姿态入口。现有接收动作复用 Playground `action=imu`：更新状态，只有在IMU模式且网页已校准时才映射到机械臂。`simulated:false` 只说明发送端声明来源，不能自动证明实物接入；须提供传感器和实体运动证据。

## 验收记录

当前仅完成代码与接口静态检查；**未编译、未烧录、未测接线、传感器身份/噪声、Wi-Fi稳定性、漂移、安装方向或真实头部随动**。后续保留板型、模块照片、core版本、编译日志、启动校准输出、服务器实际收包、真实姿态读数及实体运动录像。普通运动验收为方向正确和明显随动，不要求高精度。

失败时先查0x68、SDA/SCL与电源，再查串口校准错误，随后查HTTP响应码和服务器地址；收到数据但不运动则检查网页模式与中立校准。不得用网页滑块模拟输入替代真实硬件验收。

来源：[TDK MPU6000/MPU6050寄存器手册](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map1.pdf)、[Espressif Arduino-ESP32 Wi-Fi API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html)、[官方HTTPClient](https://github.com/espressif/arduino-esp32/blob/master/libraries/HTTPClient/src/HTTPClient.h)。
