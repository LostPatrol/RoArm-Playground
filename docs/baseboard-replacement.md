<!-- RoArm-M2-S 新驱动板的固件安装、USB接入和首次舵机验收；2026-10-12。 -->
# 更换机械臂驱动板

RoArm-M2-S 使用 Waveshare General Driver for Robots。单独购买的驱动板需要安装机械臂专用程序；USB能枚举CP2102N不代表已经安装RoArm程序。厂家提供的[产品初始化说明](https://www.waveshare.net/wiki/RoArm-M2-S)和[官方固件包](https://files.waveshare.com/wiki/RoArm-M2-S/RoArm-M2-S_FACTORY-250701.zip)适用于本次更换。

## 安装前确认

断开舵机和外部12V，先只接ESP32的USB Type-C口。旁边LADAR口不能烧录ESP32。逐板核对USB序列号、ESP32硬件MAC、实际Flash容量和加密/Secure Boot状态；不要把旧板身份或分区地址当作新板检测结果。

本次新板USB序列号为`96a4a40cf172ef1194e8734f8fcc3fa0`，ESP32-D0WD-V3 rev3.1，MAC `30:76:f5:00:ae:a4`，实际Flash为16 MiB。旧板序列号`b0b749aecb3fed11871196b80a86e0b4`、MAC `48:e7:29:b5:e7:70`，已经损坏，应退出使用。新板与旧板备份分别保存，不能相互冒充。

RK3588的正常串口所有者为`roarm-camera.service`。安装前停止服务，所有硬件会话共用`/opt/roarm-camera/agent/codex/control-loss-20261009/flash-transaction.lock`，使用`flock`独占。服务退出时可能发送停车命令，因此应先保持舵机断开。

使用项目Python执行esptool。本次使用已有esptool 4.5.1及隔离依赖，未改变生产服务的Python依赖。完整读取实际16 MiB Flash两次，比较SHA256并用`verify_flash`校验；在开发机和RK均保存备份后再写入。不要因为官方镜像头声明4 MiB而只备份4 MiB。

## 官方镜像和地址

使用烧录包`configure/esp32/multi_download.conf`中的Factory配置。不要使用包内旧的`spi_download.conf`，它仍指向WAVE_ROVER；也不要使用`combine/target.bin`或`dl_temp`缓存。

| 地址 | `bin/`中的文件 |
| --- | --- |
| `0x1000` | `RoArm-M2_example.ino.bootloader.bin` |
| `0x8000` | `RoArm-M2_example.ino.partitions.bin` |
| `0xe000` | `boot_app0.bin` |
| `0x10000` | `RoArm-M2_example.ino.bin` |

本次包SHA256：`14a251acbcaad7cc71fd9db76834564537e4f76b1e20d2a6073d071c13d510a8`；应用SHA256：`2d55cefa3654d9d0a6c864cf3120d9fde4bc46b63d6fa9fc97c7e0dc2855a268`。官方程序版本0.84，DIO/80MHz、4 MiB布局，app0 `0x10000/0x140000`，app1 `0x150000/0x140000`，文件系统`0x290000/0x160000`。该布局能装入新板16 MiB物理Flash；保留官方镜像参数，不把Flash头擅自改成16 MiB。

esptool的核心操作如下；路径、端口和Python环境应先按实际设备设置，不直接复制未知设备路径：

```sh
"$project_python" "$esptool_file" --chip esp32 --port "$new_board_port" \
  --baud 921600 --before no_reset --after no_reset write_flash \
  --flash_mode keep --flash_freq keep --flash_size keep \
  0x1000 "$factory_bin/RoArm-M2_example.ino.bootloader.bin" \
  0x8000 "$factory_bin/RoArm-M2_example.ino.partitions.bin" \
  0xe000 "$factory_bin/boot_app0.bin" \
  0x10000 "$factory_bin/RoArm-M2_example.ino.bin"
```

上例`no_reset`要求已经确认进入ROM下载模式；首次连接使用`default_reset`。写入后逐文件`verify_flash`；不使用`erase_flash`、`force`或任何eFuse写操作。需要清理旧固件的持久化区域时，必须先核对新旧分区和备份，再只处理明确的区域。

完成ROM操作后显式释放DTR使GPIO0为高，再通过RTS复位，捕获真实`SPI_FAST_FLASH_BOOT`和`RoArm-M2 started`，随后检查T105→T1051、T602启动任务和T200文件列表。仅有esptool的“Hard resetting”字样不足以证明程序启动。

## 恢复RK3588入口

控制链路保持浏览器→Wi-Fi→RK3588→USB→ESP32。RK连接现有无线网络，机械臂ESP32不需要加入该网络。保留原厂AP即可；不要为了USB控制写入STA密码或擦除NVS。

`arm_serial.py`自动寻找唯一`/dev/serial/by-id/*CP2102N*`，无需改成新序列号，也无需修改舵机ID或零位。USB串口115200/8N1；舵机总线1Mbps，底座11、肩主动12/从动13、肘14、夹爪15，EEMode默认0为夹爪。原有程序保存在`/var/lib/roarm-playground`，更换ESP32不会删除它们。

```sh
systemctl daemon-reload
systemctl start roarm-camera.service
systemctl is-active roarm-camera.service
systemctl is-enabled roarm-camera.service
```

通过`http://<RK地址>:8080/`、`/api/state`及`/snapshot.jpg`检查网页、串口应答与相机。**没有舵机时，原厂T1051仍会输出默认角度及零load；界面connected只能证明ESP32应答，不能证明舵机在线或机械臂恢复运动。**

## 首次连接原机械臂

1. 完成烧录和无舵机通信验证后，断开新底板USB和外部12V，确认断电再接舵机、OLED和原附件，核对插头方向。不要接回烧毁旧板。
2. 采用原配12V/5A机械臂电源；RK使用自己的电源。USB供电用于烧录，不能代替舵机12V供电。
3. 固定机械臂，清空运动范围，在旁观察后上电。官方程序会检查舵机、重设PID和力矩，并在初始化检查成功时自动归位；归位过程包含肩从动ID13松力矩、与主动ID12配合校准零位后重新加力。此行为属于原厂程序，Playground自身启动不主动INIT或改力矩。
4. 连接后先检查真实舵机反馈/状态与现场姿态，再逐轴显式低速小步并观察方向和反馈变化；肩12/13应作为联动关节控制，不能单独随意驱动13。不要用默认角度计算相对动作，也不要为通信检查执行T501改ID、T502校准或T210松力矩。
5. 只在实际运动及新鲜反馈均确认后记录机械臂恢复。此前烧板是否同时损坏舵机仍需要这一阶段确认；普通验收以可见运动、方向和真实反馈为准，不要求高精度定位。

本机过程证据在`agent/codex/new-baseboard-20261012/`，RK同名目录在`/opt/roarm-camera/agent/codex/`；执行报告独立保存在`agent/report/`。同份本说明应同步到RK的`/opt/roarm-camera/docs/baseboard-replacement.md`。
