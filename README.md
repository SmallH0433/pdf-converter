# PDF 转换工具

一个基于 PySide6 的跨平台桌面 PDF 工具箱，支持扫描版 PDF 的 OCR 文字识别与多后端 GPU 加速。Windows 使用 Fluent Design，macOS 使用原生窗口与 Apple 风格界面。

## 功能

| 功能 | 说明 |
|---|---|
| 阅读器 | 预览 PDF，手写笔压感标注（墨迹/橡皮擦）、留言便签，笔画框选/圈选后可移动、缩放、旋转、改色、删除，全文查找（扫描页可选 OCR），标注可写回原文件或另存 |
| PDF 转图片 | 支持 PNG / JPG / WEBP / BMP / TIFF，自定义 DPI 与页码范围，可打包为 ZIP |
| 页码节选 | 勾选缩略图、输入页码范围或按目录章节快速选择，导出为新 PDF |
| 目录/书签自动生成 | 根据标题字号、粗体和章节编号自动识别书签（如 `第1章` / `1.3`），预览删改后导出 |
| 图片转 PDF | 多张图片合成为单个 PDF，支持拖拽添加、调整顺序与页面大小 |
| PDF OCR | 为扫描版 PDF 添加隐形文字层（页面外观不变），识别后可搜索、复制、生成书签 |

### 本地大模型书签识别（可选）

「目录/书签自动生成」页可以勾选「使用本地大模型识别书签」，选择本机已有的 GGUF 模型。应用使用内置 llama.cpp 引擎直接运行模型，无需安装 LM Studio；如果本机已有 LM Studio 模型，应用也会自动发现。普通的字号/编号识别仍为默认方式，无需安装大模型。

首次使用选中的模型时，程序会保存模型副本；macOS 保存到 `~/Library/Application Support/PDF Converter/llm_models/`，Windows 安装版保存到程序目录的 `llm_models/`。请为模型预留足够磁盘空间。

LLM 只判断从 PDF 提取的候选标题，不自行生成页码或改写文字；识别结果可在导出前检查、删除。扫描件需要同时勾选 OCR。模型文件和下载中的 `.part` 文件均不会进入 Git 或安装包。

## 安装

从 [GitHub Releases](https://github.com/SmallH0433/pdf-converter/releases) 下载最新版本。当前版本为 **1.3.1**：

- Windows 10 / 11：[下载 PDF-Converter-Setup-1.2.16.exe](https://github.com/SmallH0433/pdf-converter/releases/download/v1.2.16/PDF-Converter-Setup-1.2.16.exe)
- macOS 13+（Apple Silicon）：[下载 PDF-Converter-macOS-arm64-1.3.1.dmg](https://github.com/SmallH0433/pdf-converter/releases/download/v1.3.1/PDF-Converter-macOS-arm64-1.3.1.dmg)
- Android 8.0+：[下载 PDF-Converter-Android-1.0.1.apk](https://github.com/SmallH0433/pdf-converter/releases/download/v1.2.2/PDF-Converter-Android-1.0.1.apk)

macOS 包目前使用临时签名、尚未经过 Apple 公证；如果系统首次打开时拦截，请在 Finder 中右键应用并选择「打开」。

- 无需 Python 环境，无需管理员权限（安装到用户目录）
- 支持 Windows 10 / 11（64 位）；Windows 10 建议 21H2 及以上
- 自带卸载程序，注册到 Windows「应用和功能」
- 安装新版本时自动识别并沿用旧版安装目录，覆盖旧程序文件，保留已下载的 GPU 加速包

### 1.3.1 更新内容

- 新增 macOS 13+ Apple Silicon 独立安装包
- macOS 使用原生标题栏、菜单栏、系统字体和 Apple 风格侧边栏，并跟随系统深色/浅色外观
- macOS OCR 使用 ONNX Runtime CoreML Provider，支持 Apple 芯片加速
- macOS 安装包内置 llama.cpp Metal ARM64 运行时，本地 GGUF 模型无需 LM Studio
- 新增 `⌘O` 打开 PDF 与 `⌃⌘S` 显示/隐藏侧边栏快捷键

### 1.2.16 更新内容

- OCR 与本地大模型同时启用时分别显示 OCR 和 LLM 识别进度
- 书签识别结果支持直接编辑标题、页码和层级
- 识别结果增加勾选框、全选和取消全选，可批量删除多个条目

### 1.2.15 更新内容

- LM Studio 在模型加载/切换期间返回的 HTTP 5xx 或短暂连接失败会自动重试（最多 4 次，递增间隔），并行使用多个模型时不再轻易报 500

### 1.2.14 更新内容

- 本地大模型书签识别重构为四步流水线：先识别书名 → 摘除封面/前言/目录等无关页 → 摘除每页重复的页眉页脚 → 筛选章节与小节；各步骤独立请求，失败自动回退到确定性规则
- 书名用于识别封面文字和页眉（书名片段直接摘除）

### 1.2.13 更新内容

- 修复书签识别失败或取消后状态栏仍停留在最后一条进度提示、看起来像卡死的问题（现在会显示实际的失败/取消原因）
- 工作线程统一兜底捕获所有异常并反馈到界面，不再无声退出

### 1.2.12 更新内容

- 修复模型列表重复：同一模型的应用副本、LM Studio 硬链接注册项和原始文件不再重复显示（按文件身份与同内容去重）

### 1.2.11 更新内容

- "第N讲"纳入章级编号规则（level 1）
- 提取阶段剔除例题/习题题干（三级编号后紧跟"设/已知/求/证/解"等动词或句读，及"定理2""例3.1"类标签），中文教辅书的书签噪声大幅减少
- 行数较少的目录续页按比例判定剔除，带点线页码的目录条目不再混入候选
- 提示词补充中文书规则：例题题干排除、"第N讲"为章、"基础知识结构/例题精解"等栏目为节

### 1.2.10 更新内容

- 编号标题的层级改由程序按编号段数确定（"N"→章、"N.M"→节、"N.M.K"→子节），不再依赖模型判断，彻底消除层级漂移
- 提取阶段剔除 OCR 拆散的纯数字碎片（如 "1 .2"、"13.1 5"），不再进入候选
- 提示词进一步收紧：排除 Sec./Fig./Table 引用、数字开头的正文句，首批也须按编号定级，"CHAPTER N" 与书名只选其一

### 1.2.9 更新内容

- 优化本地大模型提示词：层级按编号段数强制确定（"N"→章、"N.M"→节、"N.M.K"→子节），禁止参考上一批层级，修复层级越到后面越乱的问题
- 提示词明确排除习题编号碎片、定理/推论标签、编号列表步骤、封面文字和习题答案
- 习题答案页（Answers / 习题答案）纳入整页剔除

### 1.2.8 更新内容

- 本地大模型识别书签前，自动剔除目录、前言、序言、致谢、后记、索引等无关页面（兼容书眉罗马数字页码和"第 X 版前言"等变体），防止目录条目污染书签
- 提示词同步要求模型排除漏网的目录条目与索引词条

### 1.2.7 更新内容

- 修复源码运行与安装版各保存一份模型副本时，因 LM Studio 中已有同名注册项而误报"同名但不同内容的模型"；现在会比对副本内容，一致时直接复用现有注册

### 1.2.6 更新内容

- 修复本地大模型识别书签时推理过程耗尽输出上限、返回内容被截断而报"没有返回 JSON"的问题：默认输出上限提高到 4096 token，输出被截断时自动加大到 12288 重试

### 1.2.5 更新内容

- 目录/书签自动生成可选用内置 llama.cpp 引擎加载本地 GGUF 大模型判断标题（无需 LM Studio）
- 模型首次使用时复制到应用目录；模型本体不进入 Git 仓库或安装包
- 更新程序窗口、安装程序和卸载程序图标

### 1.2.4 更新内容

- Windows 安装包支持自动查找旧版本的自定义安装路径并直接覆盖升级
- 升级时清理旧程序依赖，保留 CUDA / DirectML 加速包；程序运行中则提示关闭后重试

### 1.2.3 更新内容

- 修复 Windows 安装后因打包混入不兼容的 Poppler ICU DLL 而无法启动
- 覆盖安装时自动清理 1.2.2 遗留的错误 DLL

### 1.2.2 更新内容

- 自动书签支持 `Section 1.2`、`Section1.2` 等小节格式，并能还原 PDF 中被拆开的编号标题
- 加强公式与变量行过滤，避免将等式误判为书签或与同页标题错误拼接
- 安卓版采用现代化 HiUI 风格，完善深色模式与触控交互
- 安卓版框选新增拖拽手柄缩放、旋转，转屏后自动适应页面宽度

### 1.2.1 更新内容

- 修复 Intel 集显机器无法启用 DirectML、错误回退 CPU 的问题
- WMI 无法读取显卡名称时仍提供 DirectML 安装入口
- 避免界面刷新过早加载并锁定错误的 ONNX Runtime 后端
- Intel/AMD/高通机器优先使用 DirectML，并校验全部三个 OCR 模型会话
- 打包阶段阻止 CPU/CUDA/DirectML 版 ONNX Runtime 混装

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
- Intel/AMD/高通机器会优先选择 DirectML；即使 WMI 无法读取显卡名称，Windows 10 1903 及以上仍会显示 DirectML 安装入口
- 状态中的“首次识别时验证”表示尚未创建推理会话；首次 OCR 后会按三个模型会话实际使用的 Provider 显示 GPU 或 CPU
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

### macOS（Apple Silicon）

项目已适配 macOS ARM：依赖清单会自动使用官方 `onnxruntime` 的 CoreML Provider，不安装 Windows/Linux 专用的 GPU 发行版。源码环境配置完成后运行：

```bash
.venv/bin/python run.py
```

首次部署所需的 ARM 原生 Python、虚拟环境和依赖均保存在项目目录内，不修改系统 Python。

生成独立的 `.app`、`.dmg` 与 `.zip` 发布包：

```bash
./macos/build_release.sh
```

## 打包

```bash
# 生成 dist/PDF转换工具/（文件夹版，OCR 组件内置）
.venv/Scripts/python.exe -m PyInstaller PDF转换工具.spec

# 生成版本化安装程序 installer/PDF-Converter-Setup-1.2.16.exe（需 NSIS 3.12，置于 _nsis/）
_nsis/nsis-bundle/makensis setup.nsi
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
