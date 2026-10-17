<!-- Usage and deployment of the independent static course materials. -->
# AI 与 VibeCoding 课程资料

分章 Markdown 讲义、浏览器交互实验、自测题和可下载 PDF。教学内容在 `tutorial/*.md`，网页产物在 `tutorial/site/`，不依赖机械臂、模型服务或项目后端。

## 阅读与离线使用

- 公网入口：<http://47.93.249.150/tutorial/>
- 分章 PDF：<http://47.93.249.150/tutorial/download.html>
- 完整离线包：<http://47.93.249.150/tutorial/download/tutorial-offline.zip>
- Markdown 原文：`site/source/`，离线包中也包含。

Windows 可运行 `tutorial/start.ps1`，或直接双击 `tutorial/site/index.html`。其他电脑同样可以直接打开首页；离线 ZIP 解压后打开其中的 `index.html`，无需安装 Python 或 Node.js。

如需局域网分享，在仓库根目录用该电脑已有的 Python 3 执行：

```text
python -m http.server 8080 --directory tutorial/site
```

Linux/macOS 可将 `python` 换成 `python3`。本机打开 `http://localhost:8080/`，同一网络的其他设备访问 `http://演示机IP:8080/`；按系统提示允许本地网络访问。

## 更新网页与 PDF

只修改 Markdown 后需重新构建；只阅读预构建网页无需执行：

```text
python tutorial/tools/build_docs.py --pdf --package
```

构建脚本仅使用 Python 3.10+ 标准库。PDF 导出需要现有 Chrome/Edge，使用随站点附带的 Esther Inspired Paper 主题，输出到 `site/download/`。没有浏览器时可省略 `--pdf` 构建网页和离线包。仓库本机使用 `.venv/Scripts/python.exe` 执行上述命令。

## 阿里云部署与回滚

Windows 在仓库根目录运行：

```powershell
powershell -File tutorial/tools/deploy.ps1
```

要求 `ssh aliyun` 已配置，服务器已有 Nginx、Python 3 和 systemd。脚本只上传 `site/`，新增 `/tutorial/` 路由，并保存旧配置；其他已有路由保持原配置。发布目录为 `/var/www/roarm-tutorial/releases/版本号`，`current` 链接指向正在服务的版本。Nginx 会设置为开机启动。

回退到已存在的版本，在服务器执行：

```sh
ln -sfn /var/www/roarm-tutorial/releases/旧版本号 /var/www/roarm-tutorial/current
nginx -t && systemctl reload nginx
```

配置备份在 `/var/www/roarm-tutorial/backups/`。首次发布前的主配置为 `nginx-版本号.conf`；需要撤销路由时先恢复该文件至 `/etc/nginx/nginx.conf`，通过 `nginx -t` 后再 reload。首次发布没有旧网站版本可回退。

## 主题声明

PDF 使用的 Esther Inspired Paper 改编自 [ESTHER不二的 Esther Design System](https://github.com/esthersjw/esther-design-system)，按 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) 保留署名、非商业和相同方式共享要求。随附原主题及字体回退配置，无需外部字体或 CDN。
