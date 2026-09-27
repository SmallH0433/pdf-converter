"""首页：功能入口与使用说明。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    DisplayLabel,
    FlowLayout,
    FluentIcon as FIF,
    IconWidget,
    PrimaryPushButton,
    StrongBodyLabel,
)


class FeatureCard(CardWidget):
    clicked = Signal()

    def __init__(self, icon, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(232, 150)  # 固定尺寸，供 FlowLayout 按宽度自动换行
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(34, 34)
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
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(16)

        layout.addWidget(DisplayLabel("PDF 转换工具", self))
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
        flow.setSpacing(14)
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
        card1.clicked.connect(lambda: self.navigate.emit("convertPage"))
        card2.clicked.connect(lambda: self.navigate.emit("extractPage"))
        card3.clicked.connect(lambda: self.navigate.emit("bookmarkPage"))
        card4.clicked.connect(lambda: self.navigate.emit("img2pdfPage"))
        card5.clicked.connect(lambda: self.navigate.emit("ocrPage"))
        for card in (card1, card2, card3, card4, card5):
            flow.addWidget(card)
        layout.addWidget(card_area)

        tip = CaptionLabel("提示：在功能页面中均可直接拖入 PDF 文件。", self)
        layout.addWidget(tip)
        layout.addStretch(1)
