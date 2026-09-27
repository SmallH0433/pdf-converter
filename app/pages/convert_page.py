"""PDF → 图片 转换页面。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    Slider,
    SpinBox,
    StrongBodyLabel,
)

from ..core import pdf_service
from ..core.workers import ConvertImagesWorker
from .widgets import DropCard


class ConvertPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("convertPage")
        self._pdf_path: str | None = None
        self._total_pages = 0
        self._worker: ConvertImagesWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(14)

        root.addWidget(StrongBodyLabel("PDF 转图片", self))

        self.drop_card = DropCard(self)
        self.drop_card.pdf_selected.connect(self._load_pdf)
        root.addWidget(self.drop_card)

        self.info_label = CaptionLabel("支持 PNG / JPG / WEBP / BMP / TIFF", self)
        root.addWidget(self.info_label)

        # 参数卡片
        settings = CardWidget(self)
        form = QFormLayout(settings)
        form.setContentsMargins(20, 16, 20, 16)
        form.setSpacing(12)

        self.range_edit = LineEdit(self)
        self.range_edit.setPlaceholderText("留空 = 全部页；格式如 1-3,5")
        form.addRow("页码范围", self.range_edit)

        self.format_combo = ComboBox(self)
        self.format_combo.addItems(pdf_service.IMAGE_FORMATS)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        form.addRow("图片格式", self.format_combo)

        self.dpi_spin = SpinBox(self)
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(150)
        self.dpi_spin.setSuffix(" DPI")
        form.addRow("分辨率", self.dpi_spin)

        quality_row = QWidget(self)
        quality_layout = QHBoxLayout(quality_row)
        quality_layout.setContentsMargins(0, 0, 0, 0)
        self.quality_slider = Slider(Qt.Orientation.Horizontal, self)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(90)
        self.quality_label = BodyLabel("90", self)
        self.quality_slider.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))
        quality_layout.addWidget(self.quality_slider)
        quality_layout.addWidget(self.quality_label)
        self.quality_row = quality_row
        quality_row.setVisible(False)  # 默认 PNG，无需质量选项
        form.addRow("JPG 质量", quality_row)

        dir_row = QWidget(self)
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        self.dir_edit = LineEdit(self)
        self.dir_edit.setPlaceholderText("选择输出文件夹")
        browse_btn = PushButton("浏览…", self)
        browse_btn.clicked.connect(self._pick_dir)
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(browse_btn)
        form.addRow("输出目录", dir_row)

        self.zip_check = CheckBox("同时打包为 ZIP", self)
        form.addRow("", self.zip_check)

        root.addWidget(settings)

        # 操作区
        action_row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("开始转换", self)
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
        root.addStretch(1)

    # ---- 文件加载 ----
    def _load_pdf(self, path: str):
        try:
            doc = pdf_service.open_pdf(path)
            self._total_pages = doc.page_count
            doc.close()
        except Exception as e:
            InfoBar.error("打开失败", str(e), parent=self, position=InfoBarPosition.TOP)
            return
        self._pdf_path = path
        self.drop_card.set_file(path)
        self.info_label.setText(f"共 {self._total_pages} 页")
        self.start_btn.setEnabled(True)
        if not self.dir_edit.text():
            self.dir_edit.setText(os.path.join(os.path.dirname(path), "输出图片"))

    # ---- 参数 ----
    def _on_format_changed(self, fmt: str):
        self.quality_row.setVisible(fmt.upper() in ("JPG", "WEBP"))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if d:
            self.dir_edit.setText(d)

    # ---- 执行 ----
    def _start(self):
        if not self._pdf_path:
            return
        out_dir = self.dir_edit.text().strip()
        if not out_dir:
            InfoBar.warning("缺少输出目录", "请先选择输出文件夹", parent=self,
                            position=InfoBarPosition.TOP)
            return
        try:
            pages = pdf_service.parse_page_range(self.range_edit.text(), self._total_pages)
        except pdf_service.PageRangeError as e:
            InfoBar.warning("页码范围有误", str(e), parent=self, position=InfoBarPosition.TOP)
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, len(pages))
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self._worker = ConvertImagesWorker(
            self._pdf_path, pages, out_dir,
            self.format_combo.currentText(), self.dpi_spin.value(),
            self.quality_slider.value(), self.zip_check.isChecked(), self)
        self._worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
        self._finish_ui()

    def _finish_ui(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _on_done(self, files: list):
        self._finish_ui()
        self.progress.setVisible(False)
        InfoBar.success("转换完成", f"已生成 {len(files)} 个文件",
                        parent=self, position=InfoBarPosition.TOP, duration=5000)

    def _on_fail(self, msg: str):
        self._finish_ui()
        self.progress.setVisible(False)
        InfoBar.error("转换失败", msg, parent=self, position=InfoBarPosition.TOP)
