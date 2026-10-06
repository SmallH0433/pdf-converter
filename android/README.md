# PDF 转换工具（安卓版）

与 iOS 版对应的原生 Android 首页，提供「阅读与转换」「智能与整理」六个入口：PDF 阅读器、PDF 转图片、页码节选、图片转 PDF、自动书签和 PDF OCR。

- PDF 转图片：选择 PDF，再选择系统文件夹，逐页写入 `page-001.png` 等 PNG 文件
- 图片转 PDF：从系统文件选择器选取一张或多张图片，按选取顺序生成 PDF 并另存
- 自动书签：按章节编号和短标题识别 PDF 文字层，预览缩略图，可编辑标题、页码与 1–6 级层级，添加或删除条目后导出带目录的副本
- PDF OCR：使用设备端 ML Kit 中文文字识别模型（也支持拉丁文字），将扫描页导出为带隐形文字层的可搜索 PDF
- 页码节选：预览页面缩略图，点选页面、输入范围、全选或清除后导出
- 首页和阅读器均支持深色模式与屏幕旋转；所有文件读写通过 Android 系统文档选择器完成

阅读器支持 PDF 预览、手写笔压感标注、留言便签和全文查找（文字层）：

- 渲染：系统 `PdfRenderer`；注释读写：PdfBox-Android（手写墨迹为 PDF Ink 注释、留言为 Text 注释，与桌面端及其他阅读器互通）
- 手写：手写笔（`TOOL_TYPE_STYLUS`）压感书写、橡皮端擦除；统一交互：单指=使用当前工具（画笔/橡皮书写擦除、选择/留言轻点交互）、双指=拖动缩放页面；手写笔在屏时忽略手指（手掌排斥）；已有 Ink/Text 注释打开时自动导入显示
- 笔画选择：框选（矩形）/圈选（套索）选中笔画后，可拖动移动、缩放（±10%）、旋转（±15°）、改色、删除
- 查找：`PDFTextStripper` 逐页提取文本与字形位置，命中高亮、上一条/下一条跳转；扫描件可先通过首页「PDF OCR」生成可搜索副本
- 保存：写回原文件（SAF `wt`）或另存为副本；出现在系统 PDF「打开方式」中
- 主页：关闭当前 PDF 并返回初始界面；有未保存修改时可保存并返回、放弃或取消
- 平板横屏：自动将绘图工具切换到左侧竖向栏；旋转时保留当前文档、页码、工具和搜索状态

## 构建

需要 Android SDK（compileSdk 37）与 JDK 17+（可用 Android Studio 自带的 jbr）：

```bash
cd android
# local.properties 中配置 sdk.dir=<SDK 路径>
./gradlew :app:assembleDebug   # Windows 下使用 .\gradlew.bat
```

APK 输出在 `app/build/outputs/apk/debug/`。

注意：项目路径不能含非 ASCII 字符，否则需在 `gradle.properties` 中加 `android.overridePathCheck=true`（本仓库已加）。
