# PDF 转换工具

一个基于 PySide6（Fluent Design）的 Windows 桌面 PDF 工具箱，支持扫描版 PDF 的 OCR 文字识别与多后端 GPU 加速。

## 功能

| 功能 | 说明 |
|---|---|
| 阅读器 | 预览 PDF，手写笔压感标注（墨迹/橡皮擦）、留言便签，笔画框选/圈选后可移动、缩放、旋转、改色、删除，全文查找（扫描页可选 OCR），标注可写回原文件或另存 |
| PDF 转图片 | 支持 PNG / JPG / WEBP / BMP / TIFF，自定义 DPI 与页码范围，可打包为 ZIP |
| 页码节选 | 勾选缩略图、输入页码范围或按目录章节快速选择，导出为新 PDF |
| 书签生成 | 根据标题字号、粗体和章节编号自动识别书签（如 `第1章` / `1.3`），预览删改后导出 |
| 图片转 PDF | 多张图片合成为单个 PDF，支持拖拽添加、调整顺序与页面大小 |
| PDF OCR | 为扫描版 PDF 添加隐形文字层（页面外观不变），识别后可搜索、复制、生成书签 |

## 安装

从 [GitHub Releases](https://github.com/SmallH0433/pdf-converter/releases) 下载最新安装包，双击安装即可。当前稳定版为 **1.2**：

- [下载 PDF-Converter-Setup-1.2.0.exe](https://github.com/SmallH0433/pdf-converter/releases/download/v1.2.0/PDF-Converter-Setup-1.2.0.exe)

- 无需 Python 环境，无需管理员权限（安装到用户目录）
- 支持 Windows 10 / 11（64 位）；Windows 10 建议 21H2 及以上
- 自带卸载程序，注册到 Windows「应用和功能」

### 1.2 更新内容

- OCR 引擎升级至 RapidOCR 3.9.2（PP-OCRv6 中文模型）
- 修复 CPU/GPU 版 ONNX Runtime 混装导致 CUDA 被覆盖的问题
- 修复 CUDA 运行库目录过早失效、界面显示 GPU 但实际回退 CPU 的问题
- 根据 OCR 会话实际加载的 Provider 显示 CUDA、DirectML、CoreML 或 CPU
- 保持 Windows 10 64 位、AMD/Intel/高通 DirectML 及 CPU 回退支持

## GPU 加速（可选）

OCR 默认使用 CPU 即可用；在「PDF OCR」页面可一键安装 GPU 加速包，程序按显卡厂商自动选择方案：

| 平台 / 显卡 | 后端 | 加速包 |
|---|---|---|
| NVIDIA（Windows / Linux） | CUDA | 约 1.1GB（CUDA 运行库） |
| AMD / Intel / 高通（Windows 10+） | DirectML | 约 250MB（onnxruntime-directml） |
| 苹果 Mac（源码运行） | CoreML | 无需安装，onnxruntime 自带 |

- CUDA 与 DirectML 加速包**可以共存**（双显笔记本适用），开始 OCR 任务时按当时状态自动选择：插电优先 CUDA（独显性能最高），离电走 DirectML（默认使用当前显示输出 GPU：独显直连用独显、混合输出用核显），更省电
- 加速包下载自 PyPI（默认清华镜像源），安装后离线可用
- 海思（麒麟/昇腾/马良）无 ONNX Runtime 桌面后端，程序会检测并明确提示；华为 Windows 笔记本的 Intel/AMD 显卡已由 DirectML 覆盖

## 手写笔输入（按操作系统自动选择原生 API）

阅读器的手写标注通过 Qt 手写板事件接入各系统的原生手写 API，程序启动时按当前操作系统自动选择：

| 操作系统 | 手写后端 | 压感 / 橡皮擦端 |
|---|---|---|
| Windows | Windows Ink（Qt6 默认） | 支持 |
| Android | Android Stylus / MotionEvent（S Pen 等） | 支持；手指专用于滚动翻页 |
| macOS | NSEvent 数位板事件（外接数位板） | 支持 |
| Linux | X11 / Wayland 数位板事件（libinput） | 支持 |
| iPadOS | Apple Pencil | PySide6 无法在 iPadOS 运行，不支持 |

桌面平台鼠标也可书写（无压感）；当前生效的后端显示在阅读器页面底部状态栏。

## 从源码运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python.exe run.py
```

或直接双击 `启动.bat`。

## 打包

```bash
# 生成 dist/PDF转换工具/（文件夹版，OCR 组件内置）
.venv/Scripts/python.exe -m PyInstaller PDF转换工具.spec

# 生成版本化安装程序 installer/PDF-Converter-Setup-1.2.0.exe（需 NSIS 3.12，置于 _nsis/）
NSISDIR="$(pwd -W)/_nsis/nsis-bundle/windows" _nsis/nsis-bundle/windows/makensis.exe setup.nsi
```

命令行 OCR 工具（与 GUI 共用核心逻辑）：

```bash
.venv/Scripts/python.exe ocr_pdf.py 输入.pdf 输出_ocr.pdf
```

## 技术栈

- UI：PySide6 + PySide6-Fluent-Widgets
- PDF 引擎：PyMuPDF
- OCR：RapidOCR（PP-OCRv6 中文模型）+ ONNX Runtime（CUDA / DirectML / CoreML 多后端）
- 打包：PyInstaller（onedir）+ NSIS
