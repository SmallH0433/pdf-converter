# PDF 阅读器（安卓版）

桌面版「阅读器」的安卓对应实现：PDF 预览、手写笔压感标注、留言便签、全文查找（文字层）。

- 渲染：系统 `PdfRenderer`；注释读写：PdfBox-Android（手写墨迹为 PDF Ink 注释、留言为 Text 注释，与桌面端及其他阅读器互通）
- 手写：手写笔（`TOOL_TYPE_STYLUS`）压感书写、橡皮端擦除；统一交互：单指=使用当前工具（画笔/橡皮书写擦除、选择/留言轻点交互）、双指=拖动缩放页面；手写笔在屏时忽略手指（手掌排斥）；已有 Ink/Text 注释打开时自动导入显示
- 笔画选择：框选（矩形）/圈选（套索）选中笔画后，可拖动移动、缩放（±10%）、旋转（±15°）、改色、删除
- 查找：`PDFTextStripper` 逐页提取文本与字形位置，命中高亮、上一条/下一条跳转（安卓版暂无 OCR）
- 保存：写回原文件（SAF `wt`）或另存为副本；出现在系统 PDF「打开方式」中

## 构建

需要 Android SDK（compileSdk 37）与 JDK 17+（可用 Android Studio 自带的 jbr）：

```bash
cd android
# local.properties 中配置 sdk.dir=<SDK 路径>
gradle :app:assembleDebug   # 或 ./gradlew（如已生成 wrapper）
```

APK 输出在 `app/build/outputs/apk/debug/`。

注意：项目路径不能含非 ASCII 字符，否则需在 `gradle.properties` 中加 `android.overridePathCheck=true`（本仓库已加）。
