# 桌面构建与发布指南

[English](README_EN.md) · [发布清单](RELEASE_CHECKLIST.md) · [用户安装与操作](../docs/GUIDE.md)

本文是维护者构建说明。普通用户安装、数据位置和启动行为统一见用户手册。当前是 PyInstaller 桌面启动器：启动本机 FastAPI 服务并打开系统浏览器，没有自动更新或应用商店集成。

## 本地构建

需要 Python 3.11+，在目标操作系统和所需处理器架构上构建；不要把 macOS 产物当作 Windows/Linux 安装包。

```bash
python -m pip install -r requirements-packaging.txt
python scripts/build_desktop.py --dry-run
python scripts/build_desktop.py
python scripts/package_release.py --version v0.1.0
```

`build_desktop.py` 从 `openavatar/desktop.py` 构建，包含静态资源、语言资源、模板、项目 LICENSE 与凭据库组件。输出在 `dist/`，中间文件在 `build/`，`.spec` 为可再生成文件。`package_release.py` 产生 `release/` 下的 ZIP 和 SHA-256 文件；可用 `--platform macos|windows|linux` 显式选择已有产物类型，这不会跨平台编译。

桌面运行数据写入系统应用数据目录或 `OPENAVATAR_DATA_DIR`，不应出现在安装包里。发行包不附带私人数据库、演示人物、API Key、本地大模型权重、Piper 音色模型。FFmpeg、可选 OCR 引擎和 Linux 凭据服务的可用性需要在目标环境验证。

## GitHub Actions

- `quality.yml`：PR 和 main/master 推送执行编译、关键静态检查、自动测试、浏览器/WebSocket 检查及依赖漏洞审计。
- `build-desktop.yml`：手动运行或推送 `v*` 标签时，在 macOS、Windows、Linux 原生 runner 上分别构建并上传 Actions artifact。
- 手动运行仅提供构建产物供检查。推送 `v*` 标签会进一步创建或更新对应 **公开 Release** 并上传 ZIP/校验文件；同标签重跑会覆盖同名文件。

因此标签推送属于发布动作，应在[清单](RELEASE_CHECKLIST.md)完成并确认发布后进行。工作流中有跨平台配置，不等于已完成对应平台的实机验收。

## 干净发布源

本机数据、钥匙串、虚拟环境、旧 `.spec`、构建目录和审计报告不属于发布源。不要直接压缩整个开发目录。首次公开还必须检查 Git 历史：工作区删除旧素材不会删除历史内容。含旧演示或个人内容的历史应留在本机，使用经过审查的干净公开历史。

从干净源码重新构建，不复用历史安装包。核对归档清单、处理器架构、项目 LICENSE、随包第三方许可证/声明与 SHA-256。项目 LICENSE 本身不能代替第三方许可清单。

## 平台验收

在各目标平台启动软件，验证页面、数据路径、Key 保存/删除、导入/导出、服务关闭，以及系统证书和凭据库。网络功能需使用测试账号验证，不能把模拟测试解释为真实服务可用。

当前包未正式签名。发布说明应明确平台/架构、未签名状态、外部依赖和已验证范围，不承诺所有系统无需额外配置即可运行。源码公开与桌面正式版发布是两个不同的验收范围。
