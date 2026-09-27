"""共享组件：PDF 拖放卡片、可勾选缩略图网格。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    FlowLayout,
    FluentIcon as FIF,
    IconWidget,
    ScrollArea,
    StrongBodyLabel,
)


class DropCard(CardWidget):
    """拖入或点击选择 PDF 的卡片。"""

    pdf_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(110)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.icon = IconWidget(FIF.DOCUMENT, self)
        self.icon.setFixedSize(36, 36)
        self.title = StrongBodyLabel("拖入 PDF 文件，或点击选择", self)
        self.subtitle = CaptionLabel("尚未加载文件", self)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.subtitle, 0, Qt.AlignmentFlag.AlignHCenter)

        self._dialog_filter = "PDF 文件 (*.pdf)"

    def set_file(self, path: str):
        size_mb = os.path.getsize(path) / 1024 / 1024
        self.title.setText(os.path.basename(path))
        self.subtitle.setText(f"{size_mb:.1f} MB · {os.path.dirname(path)}")

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "", self._dialog_filter)
        if path:
            self.pdf_selected.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.pdf_selected.emit(path)
                break


class ThumbnailCard(CardWidget):
    """带复选框的单页缩略图卡片。"""

    toggled = Signal(int, bool)

    def __init__(self, page_index: int, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self.setFixedSize(160, 220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.image = BodyLabel(self)
        self.image.setFixedSize(140, 178)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setText("加载中…")
        self.checkbox = CheckBox(f"第 {page_index + 1} 页", self)
        self.checkbox.stateChanged.connect(
            lambda _s: self.toggled.emit(self.page_index, self.checkbox.isChecked())
        )
        layout.addWidget(self.image)
        layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_thumbnail(self, data: bytes):
        pix = QPixmap()
        pix.loadFromData(data)
        self.image.setPixmap(pix.scaled(
            140, 178,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def set_checked(self, checked: bool):
        self.checkbox.setChecked(checked)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()


class ThumbnailGrid(ScrollArea):
    """可勾选的缩略图流式网格。"""

    selection_changed = Signal(list)  # 0 起始页码列表
    build_progress = Signal(int, int)  # 已创建卡片数, 总数

    BATCH_SIZE = 24  # 每帧创建的卡片数，避免大文档卡死界面

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.container = QWidget(self)
        self.flow = FlowLayout(self.container, needAni=False)
        self.flow.setContentsMargins(8, 8, 8, 8)
        self.flow.setSpacing(10)
        self.setWidget(self.container)
        self.cards: list[ThumbnailCard] = []
        self._pending_total = 0
        self._generation = 0
        self._pending_selection: set[int] | None = None

    def build(self, total_pages: int):
        """分批异步创建卡片，大文档（上千页）也不阻塞界面。"""
        self.clear()
        self._generation += 1
        self._pending_total = total_pages
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda g=self._generation: self._build_batch(g))

    def _build_batch(self, generation: int):
        if generation != self._generation:
            return  # 已被新的 build/clear 取代
        start = len(self.cards)
        end = min(start + self.BATCH_SIZE, self._pending_total)
        for i in range(start, end):
            card = ThumbnailCard(i, self.container)
            card.toggled.connect(self._on_toggled)
            if self._pending_selection is not None:
                card.set_checked(i in self._pending_selection)
            self.flow.addWidget(card)
            self.cards.append(card)
        self.build_progress.emit(end, self._pending_total)
        if end < self._pending_total:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda g=generation: self._build_batch(g))

    def clear(self):
        self._generation += 1  # 使进行中的分批构建失效
        self._pending_total = 0
        for card in self.cards:
            self.flow.removeWidget(card)
            card.deleteLater()
        self.cards = []

    def _on_toggled(self, _index, _checked):
        self.selection_changed.emit(self.selected_pages())

    def selected_pages(self) -> list[int]:
        return [c.page_index for c in self.cards if c.is_checked()]

    def set_thumbnail(self, page_index: int, data: bytes):
        if 0 <= page_index < len(self.cards):
            self.cards[page_index].set_thumbnail(data)

    def set_thumbnails_batch(self, items: list):
        """批量应用缩略图，期间暂停重绘，只触发布局一次。"""
        self.container.setUpdatesEnabled(False)
        try:
            for page_index, data in items:
                self.set_thumbnail(page_index, data)
        finally:
            self.container.setUpdatesEnabled(True)

    def set_selected(self, pages: list[int]):
        wanted = set(pages)
        self._pending_selection = wanted  # 分批构建期间，新卡片也按此勾选
        for c in self.cards:
            c.set_checked(c.page_index in wanted)

    def select_all(self):
        self._pending_selection = set(range(self._pending_total)) if self._pending_total else None
        for c in self.cards:
            c.set_checked(True)

    def select_none(self):
        self._pending_selection = set()
        for c in self.cards:
            c.set_checked(False)
