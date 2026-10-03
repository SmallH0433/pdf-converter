"""首页：功能入口与使用说明。"""
from __future__ import annotations

import platform

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    DisplayLabel,
    FlowLayout,
    FluentIcon as FIF,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    TitleLabel,
)


IS_MACOS = platform.system() == "Darwin"


class FeatureCard(CardWidget):
    clicked = Signal()

    def __init__(self, icon, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("featureCard")
        self.setBorderRadius(12 if IS_MACOS else 8)
        self.setFixedSize(250 if IS_MACOS else 232, 142 if IS_MACOS else 150)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18 if IS_MACOS else 20, 16 if IS_MACOS else 18,
                                  18 if IS_MACOS else 20, 16 if IS_MACOS else 18)
        layout.setSpacing(7 if IS_MACOS else 6)
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(30 if IS_MACOS else 34, 30 if IS_MACOS else 34)
        layout.addWidget(icon_widget)
        layout.addWidget(StrongBodyLabel(title, self))
        desc_label = CaptionLabel(desc, self)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        layout.addStretch(1)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.clicked.emit()


class HomePage(QWidget):
    navigate = Signal(str)  # 目标页面的 route key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32 if IS_MACOS else 36, 28, 32 if IS_MACOS else 36, 28)
        layout.setSpacing(14 if IS_MACOS else 16)

        heading = TitleLabel("PDF 转换工具", self) if IS_MACOS \
            else DisplayLabel("PDF 转换工具", self)
        heading.setObjectName("homeTitle")
        layout.addWidget(heading)
        intro = BodyLabel(
            "将 PDF 转换为 PNG / JPG 等主流图片格式，节选其中几页导出，"
            "根据内容自动生成书签，或将多张图片合成为 PDF。",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # 功能卡片按页面宽度自动换行
        card_area = QWidget(self)
        flow = FlowLayout(card_area, needAni=False)
        flow.setContentsMargins(0, 0, 0, 0)
        flow.setSpacing(12 if IS_MACOS else 14)
        card1 = FeatureCard(
            FIF.PHOTO, "PDF 转图片",
            "支持 PNG / JPG / WEBP / BMP / TIFF，自定义 DPI 与页码范围，可打包为 ZIP。", card_area)
        card2 = FeatureCard(
            FIF.CUT, "页码节选",
            "勾选缩略图、输入页码范围或按目录章节快速选择，导出为新 PDF 或图片。", card_area)
        card3 = FeatureCard(
            FIF.TAG, "书签生成",
            "根据标题字号、粗体和章节编号自动识别书签，可预览删改后导出。", card_area)
        card4 = FeatureCard(
            FIF.ALBUM, "图片转 PDF",
            "多张图片合成为单个 PDF，支持拖拽添加、调整顺序与页面大小。", card_area)
        card5 = FeatureCard(
            FIF.SEARCH, "PDF OCR",
            "为扫描版 PDF 添加隐形文字层，支持 GPU 加速，识别后可搜索、复制、生成书签。", card_area)
        card6 = FeatureCard(
            FIF.PENCIL_INK, "阅读器",
            "预览 PDF，手写笔压感标注、留言便签，全文查找（扫描页可选 OCR）。", card_area)
        card1.clicked.connect(lambda: self.navigate.emit("convertPage"))
        card2.clicked.connect(lambda: self.navigate.emit("extractPage"))
        card3.clicked.connect(lambda: self.navigate.emit("bookmarkPage"))
        card4.clicked.connect(lambda: self.navigate.emit("img2pdfPage"))
        card5.clicked.connect(lambda: self.navigate.emit("ocrPage"))
        card6.clicked.connect(lambda: self.navigate.emit("readerPage"))
        for card in (card1, card2, card3, card4, card5, card6):
            flow.addWidget(card)
        layout.addWidget(card_area)

        tip = CaptionLabel("提示：在功能页面中均可直接拖入 PDF 文件。", self)
        layout.addWidget(tip)

        # 注册到 .pdf「打开方式」（Windows，HKCU 无需管理员）
        from ..core import fileassoc
        if fileassoc.supported():
            row = QHBoxLayout()
            self.assoc_btn = PushButton("", self)
            self.assoc_btn.clicked.connect(self._toggle_fileassoc)
            row.addWidget(self.assoc_btn)
            row.addStretch(1)
            layout.addLayout(row)
            self._refresh_assoc_btn()
        layout.addStretch(1)

    def _refresh_assoc_btn(self):
        from ..core import fileassoc
        self.assoc_btn.setText("从 PDF「打开方式」中移除" if fileassoc.is_registered()
                               else "将本程序加入 PDF「打开方式」")

    def _toggle_fileassoc(self):
        from ..core import fileassoc
        try:
            if fileassoc.is_registered():
                fileassoc.unregister()
                InfoBar.success("已移除", "已从 .pdf 的「打开方式」中移除", parent=self,
                                position=InfoBarPosition.TOP)
            else:
                fileassoc.register()
                InfoBar.success("已注册",
                                "右键 PDF 文件 → 打开方式，即可选择本程序",
                                parent=self, position=InfoBarPosition.TOP)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("操作失败", str(e), parent=self,
                          position=InfoBarPosition.TOP)
        self._refresh_assoc_btn()
