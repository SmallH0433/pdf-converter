# PDF 阅读器（iOS）

原生 iPhone / iPad 版本，使用 `PDFKit` 读取、搜索与保存 PDF 注释，不依赖第三方库。

## 功能

- 文件 App 打开 PDF，也可从其他 App 的“打开方式”进入
- 图片转 PDF 可先选择从相册或文件导入多张图片
- PDF 转图片完成后可选择保存到相册、文件或直接分享
- 顶栏主页按钮可关闭当前文档并返回初始界面，未保存时提供保存确认
- Apple Pencil / 手指手写，支持压感线宽、颜色切换、橡皮和撤销
- PDF Text 留言注释的新建、编辑与删除
- 文字层全文搜索、上一条 / 下一条与高亮
- 矩形或套索选择 Ink 注释，并可缩放、旋转、改色和删除
- 写回原文件或通过系统文件选择器另存副本
- 主界面提供自动书签：按章节编号和短标题识别页面标题，生成可跳转的 PDF 目录
- 主界面提供 PDF OCR：使用 Apple Vision 识别扫描页，并导出带隐形文字层的可搜索 PDF
- 自动书签先显示目录预览，可编辑标题、页码和层级，添加或删除条目后再导出
- 页码节选先显示原页面缩略图，可点选页面、输入范围、全选或清除后再导出
- iPhone / iPad、横竖屏与深色模式
- iOS 26 使用原生 Liquid Glass 悬浮控制层；iOS 16–25 自动回退为系统材质
- iPadOS 横屏使用左侧竖向工具栏和右下角翻页面板，并支持旋转时自动重排

## 构建

使用 Xcode 打开 `PDFReader.xcodeproj`，选择共享的 `PDFReader` Scheme 和模拟器或真机运行。
真机归档前需要在 Signing & Capabilities 中选择自己的开发团队。

命令行模拟器构建：

```bash
cd ios
xcodebuild -project PDFReader.xcodeproj \
  -scheme PDFReader \
  -sdk iphonesimulator \
  -configuration Debug \
  CODE_SIGNING_ALLOWED=NO build
```
