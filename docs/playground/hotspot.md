<!-- Stable local webpage, automatic Windows opening, and portable Wi-Fi operation. -->
# 手机热点与自动打开网页

固定入口为 **`http://roarm.local:8080/`**，不需要查询手机分配的IP，也不依赖互联网。电脑与RK3588须处于能互相通信的同一局域网；机械臂继续通过USB接RK。

## 日常使用

1. 打开手机热点`vivo X300`，保持原名称和密码。
2. 给RK和机械臂供电，启动演示笔记本并登录Windows。两端已保存热点并开启自动连接。
3. 等待网页自动打开。RK晚一点启动也可以，电脑会持续等待；也可双击桌面的 **RoArm Playground** 图标。

手势、猜拳和导演仍从各自面板点击连接/加载模型，之后点击启动实验。自动打开网页本身不会激活互动或发送机械臂动作。

手机若有“无设备连接时自动关闭热点”，建议关闭。设备已经连接原Wi-Fi时，打开热点不保证立即切换网络；原Wi-Fi下也能使用同一个固定入口。离开原网络后，会选择可用的已保存网络。

## 工作方式与安装

RK运行Avahi，通过mDNS发布`roarm.local`，随网络地址变化更新名称。系统hostname保持不变。首次在RK部署目录执行：

```sh
bash /opt/roarm-camera/install_discovery.sh
```

脚本从系统软件源安装`avahi-daemon`并启用自启动，保留原配置`/etc/avahi/avahi-daemon.conf.roarm-backup`。可传入其他单标签名称，例如`install_discovery.sh roarm-demo`，对应`roarm-demo.local`；同一网络的多台设备应使用不同名称。

Windows用演示账户的管理员PowerShell执行一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\RoArm-M2\host\install_windows_web.ps1
```

注册登录任务`RoArm-M2 Web`并立即启动，创建桌面快捷方式。该任务每5秒尝试解析RK名称并检查HTTP；就绪后打开默认浏览器，同一任务运行期间只打开一次。它同时把已有模型防火墙规则`RoArm-M2 Host RK`的来源更新为当前可达RK地址，无需因DHCP变化手动改规则。防火墙更新失败会记录错误，但仍可打开基础网页。

完整的`host/install_windows_startup.ps1`会同时注册模型与网页任务；`start_windows.ps1`默认使用`http://roarm.local:8080`。已有安装若只想补上自动开网页，运行上述独立安装脚本即可。模型缺失时仍按[Windows说明](windows.md)安装；网页任务不负责安装模型或启动互动。

## 排查与停用

```powershell
Get-ScheduledTask -TaskName 'RoArm-M2 Web'
Get-Content D:\RoArm-M2\data\host-manager\web.json
```

`web.json`保存等待/就绪、当前地址、浏览器打开时间与防火墙错误。若长时间等待，确认热点仍开着、两端在同一网络，并在RK执行`systemctl status avahi-daemon roarm-camera`。可临时用`http://RK当前IP:8080/`检查；隔离访客的网络可能阻止mDNS或设备互访。

临时停止自动打开：`Stop-ScheduledTask -TaskName 'RoArm-M2 Web'`；恢复：`Start-ScheduledTask -TaskName 'RoArm-M2 Web'`。禁用登录启动用`Disable-ScheduledTask`；桌面图标和直接访问仍可用。

## 验证边界

Windows原生名称解析与HTTP已在手机热点和原Wi-Fi验证；热点消失后RK发布的新地址可以通过同一名称访问。网页任务实际运行、记录浏览器打开成功并自动更新来源规则。RK暂时离线时启动任务，状态为waiting；RK自动联网后变为ready，记录一次浏览器打开。这些不替代Windows自然注销登录、整机冷启动、现场目视或真人互动验收。
