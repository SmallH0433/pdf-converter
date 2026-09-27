"""图片转 PDF 页面：多选图片，调整顺序，合成为单个 PDF。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    ListWidget,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
)

from ..core import pdf_service
from ..core.workers import ImagesToPdfWorker

MM_TO_PT = 72 / 25.4


class ImageListWidget(ListWidget):
    """支持拖入图片文件的列表。"""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(ListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                if url.toLocalFile().lower().endswith(pdf_service.IMAGE_EXTS):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        paths = [url.toLocalFile() for url in e.mimeData().urls()
                 if url.toLocalFile().lower().endswith(pdf_service.IMAGE_EXTS)]
        if paths:
            self.files_dropped.emit(paths)


class Img2PdfPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("img2pdfPage")
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(14)

        root.addWidget(StrongBodyLabel("图片转 PDF", self))
        hint = CaptionLabel(
            "支持 PNG / JPG / WEBP / BMP / TIFF，可直接把图片拖入下方列表；每张图片占一页。",
            self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 图片管理按钮
        btn_card = CardWidget(self)
        btn_row = QHBoxLayout(btn_card)
        btn_row.setContentsMargins(20, 12, 20, 12)
        btn_row.setSpacing(10)
        add_btn = PushButton("添加图片", self)
        add_btn.clicked.connect(self._add_images)
        remove_btn = PushButton("移除选中", self)
        remove_btn.clicked.connect(self._remove_selected)
        up_btn = PushButton("上移", self)
        up_btn.clicked.connect(lambda: self._move(-1))
        down_btn = PushButton("下移", self)
        down_btn.clicked.connect(lambda: self._move(1))
        sort_btn = PushButton("按名称排序", self)
        sort_btn.clicked.connect(self._sort_by_name)
        clear_btn = PushButton("清空", self)
        clear_btn.clicked.connect(self._clear)
        for b in (add_btn, remove_btn, up_btn, down_btn, sort_btn, clear_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        root.addWidget(btn_card)

        self.status_label = CaptionLabel("尚未添加图片", self)
        root.addWidget(self.status_label)

        self.list = ImageListWidget(self)
        self.list.files_dropped.connect(self._add_paths)
        self.list.setMinimumHeight(240)
        root.addWidget(self.list, 1)

        # 页面设置
        option_card = CardWidget(self)
        option_row = QHBoxLayout(option_card)
        option_row.setContentsMargins(20, 14, 20, 14)
        option_row.setSpacing(12)
        option_row.addWidget(BodyLabel("页面大小：", self))
        self.size_combo = ComboBox(self)
        self.size_combo.addItems(["原始尺寸", *pdf_service.PAGE_SIZES.keys()])
        self.size_combo.currentTextChanged.connect(self._on_size_changed)
        option_row.addWidget(self.size_combo)
        option_row.addWidget(BodyLabel("边距（毫米）：", self))
        self.margin_spin = DoubleSpinBox(self)
        self.margin_spin.setRange(0, 50)
        self.margin_spin.setValue(10)
        self.margin_spin.setEnabled(False)
        option_row.addWidget(self.margin_spin)
        option_row.addStretch(1)
        root.addWidget(option_card)

        # 操作行
        action_row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("导出 PDF", self)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = PushButton("取消", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.progress = ProgressBar(self)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

    # ---- 图片列表管理 ----
    def _add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths: list[str]):
        existing = {self.list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.list.count())}
        added = 0
        for p in paths:
            if p in existing or not os.path.isfile(p):
                continue
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.list.addItem(item)
            existing.add(p)
            added += 1
        if added:
            self._update_status()

    def _remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._update_status()

    def _move(self, delta: int):
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows:
            return
        if delta < 0:
            for r in rows:
                if r > 0 and self.list.item(r - 1) not in self.list.selectedItems():
                    item = self.list.takeItem(r)
                    self.list.insertItem(r - 1, item)
                    item.setSelected(True)
        else:
            for r in reversed(rows):
                if r < self.list.count() - 1 and self.list.item(r + 1) not in self.list.selectedItems():
                    item = self.list.takeItem(r)
                    self.list.insertItem(r + 1, item)
                    item.setSelected(True)

    def _sort_by_name(self):
        paths = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.list.count())]
        paths.sort(key=lambda p: os.path.basename(p).lower())
        self.list.clear()
        self._add_paths(paths)

    def _clear(self):
        self.list.clear()
        self._update_status()

    def _update_status(self):
        n = self.list.count()
        self.status_label.setText(f"共 {n} 张图片" if n else "尚未添加图片")
        self.start_btn.setEnabled(n > 0)

    def _on_size_changed(self, text: str):
        self.margin_spin.setEnabled(text != "原始尺寸")

    # ---- 导出 ----
    def _start(self):
        paths = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.list.count())]
        if not paths:
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "保存 PDF", "图片合成.pdf", "PDF 文件 (*.pdf)")
        if not out_path:
            return

        size_text = self.size_combo.currentText()
        page_size = None if size_text == "原始尺寸" else pdf_service.PAGE_SIZES[size_text]
        margin_pt = self.margin_spin.value() * MM_TO_PT if page_size else 0

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self._worker = ImagesToPdfWorker(paths, out_path, page_size, margin_pt, self)
        self._worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._finish_ui()

    def _finish_ui(self):
        self.start_btn.setEnabled(self.list.count() > 0)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)

    def _on_done(self, path: str):
        self._finish_ui()
        InfoBar.success("导出完成", f"已导出：{path}", parent=self,
                        position=InfoBarPosition.TOP, duration=5000)

    def _on_fail(self, msg: str):
        self._finish_ui()
        InfoBar.error("导出失败", msg, parent=self, position=InfoBarPosition.TOP)
