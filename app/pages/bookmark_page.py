"""书签生成页面：根据 PDF 内容自动识别标题，生成书签并导出。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SpinBox,
    StrongBodyLabel,
)

from ..core import ocr_service, pdf_service
from ..core.workers import DetectHeadingsWorker, WriteBookmarksWorker
from .widgets import DropCard

MODES = [
    ("标题样式 + 章节编号", "both"),
    ("仅章节编号", "numbering"),
    ("仅标题样式（字号/粗体）", "font"),
]


class BookmarkPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bookmarkPage")
        self._pdf_path: str | None = None
        self._total_pages = 0
        self._toc: list[dict] = []
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(14)

        root.addWidget(StrongBodyLabel("书签生成", self))
        hint = CaptionLabel(
            "根据标题的字号、粗体和章节编号（如 第1章 / Chapter 2 / 1.3）自动识别书签，"
            "会自动过滤页眉页脚；导出时会替换 PDF 原有书签。", self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.drop_card = DropCard(self)
        self.drop_card.pdf_selected.connect(self._load_pdf)
        root.addWidget(self.drop_card)

        # 识别设置
        option_card = CardWidget(self)
        option_row = QHBoxLayout(option_card)
        option_row.setContentsMargins(20, 14, 20, 14)
        option_row.setSpacing(12)
        option_row.addWidget(BodyLabel("识别方式：", self))
        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems([label for label, _ in MODES])
        option_row.addWidget(self.mode_combo)
        option_row.addWidget(BodyLabel("最大层级：", self))
        self.level_spin = SpinBox(self)
        self.level_spin.setRange(1, 6)
        self.level_spin.setValue(3)
        option_row.addWidget(self.level_spin)
        self.ocr_check = CheckBox("扫描件 OCR 识别", self)
        self.ocr_check.setToolTip(
            "页面无文字层时自动调用 OCR 识别文字（较慢，有 NVIDIA GPU 时显著加速）")
        ok, reason = ocr_service.ocr_available()
        if not ok:
            self.ocr_check.setEnabled(False)
            self.ocr_check.setToolTip(f"OCR 不可用：{reason}")
        option_row.addWidget(self.ocr_check)
        option_row.addStretch(1)
        root.addWidget(option_card)

        # 操作行
        action_row = QHBoxLayout()
        self.detect_btn = PrimaryPushButton("开始识别", self)
        self.detect_btn.setEnabled(False)
        self.detect_btn.clicked.connect(self._start_detect)
        self.cancel_btn = PushButton("取消", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_detect)
        self.delete_btn = PushButton("删除选中条目", self)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.export_btn = PrimaryPushButton("导出带书签的 PDF", self)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        action_row.addWidget(self.detect_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.delete_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.export_btn)
        root.addLayout(action_row)

        self.progress = ProgressBar(self)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.status_label = CaptionLabel("尚未加载文件", self)
        root.addWidget(self.status_label)

        # 书签预览树
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["标题", "页码"])
        self.tree.setColumnWidth(0, 560)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setMinimumHeight(240)
        root.addWidget(self.tree, 1)

    def showEvent(self, e):
        super().showEvent(e)
        # OCR 组件可能在「PDF OCR」页刚装完，进入本页时刷新勾选框可用性
        ok, reason = ocr_service.ocr_available()
        self.ocr_check.setEnabled(ok)
        if not ok:
            self.ocr_check.setToolTip(f"OCR 不可用：{reason}")

    # ---- 文件加载 ----
    def _load_pdf(self, path: str):
        try:
            doc = pdf_service.open_pdf(path)
            self._total_pages = doc.page_count
            existing = doc.get_toc()
            doc.close()
        except Exception as e:
            InfoBar.error("打开失败", str(e), parent=self, position=InfoBarPosition.TOP)
            return
        self._pdf_path = path
        self.drop_card.set_file(path)
        self.detect_btn.setEnabled(True)
        self._toc = []
        self.tree.clear()
        self.export_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        msg = f"共 {self._total_pages} 页"
        if existing:
            msg += f" · 已有 {len(existing)} 条书签（导出时将被替换）"
        self.status_label.setText(msg)

    # ---- 识别 ----
    def _start_detect(self):
        if not self._pdf_path:
            return
        mode = MODES[self.mode_combo.currentIndex()][1]
        self.detect_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, self._total_pages)
        self.progress.setValue(0)
        self._worker = DetectHeadingsWorker(
            self._pdf_path, mode, self.level_spin.value(), self.ocr_check.isChecked(), self)
        self._worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self._worker.finished_ok.connect(self._on_detected)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _cancel_detect(self):
        if self._worker and hasattr(self._worker, "cancel"):
            self._worker.cancel()

    def _on_detected(self, toc: list):
        self._finish_detect_ui()
        self._toc = toc
        self._rebuild_tree()
        if not toc:
            ocr_hint = ""
            if self.ocr_check.isEnabled() and not self.ocr_check.isChecked():
                ocr_hint = "，可勾选「扫描件 OCR 识别」后重试"
            self.status_label.setText(
                f"共 {self._total_pages} 页 · 未识别到标题，可尝试更换识别方式或调大层级{ocr_hint}")
            InfoBar.warning("未识别到标题",
                            f"该 PDF 可能是扫描件或标题样式不明显{ocr_hint}",
                            parent=self, position=InfoBarPosition.TOP)
            return
        self.status_label.setText(f"共 {self._total_pages} 页 · 识别到 {len(toc)} 条书签，可在下方删改后导出")
        self.export_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _on_fail(self, msg: str):
        self._finish_detect_ui()
        self.export_btn.setEnabled(bool(self._toc))
        InfoBar.error("操作失败", msg, parent=self, position=InfoBarPosition.TOP)

    def _finish_detect_ui(self):
        self.detect_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)

    # ---- 预览树 ----
    def _rebuild_tree(self):
        self.tree.clear()
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for idx, item_data in enumerate(self._toc):
            node = QTreeWidgetItem([item_data["title"], str(item_data["page"] + 1)])
            node.setData(0, Qt.ItemDataRole.UserRole, idx)
            node.setToolTip(0, item_data["title"])
            while stack and stack[-1][0] >= item_data["level"]:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.tree.addTopLevelItem(node)
            stack.append((item_data["level"], node))
        self.tree.expandAll()

    def _delete_selected(self):
        items = self.tree.selectedItems()
        if not items:
            return
        to_remove: set[int] = set()
        for item in items:
            stack = [item]
            while stack:
                node = stack.pop()
                idx = node.data(0, Qt.ItemDataRole.UserRole)
                if idx is not None:
                    to_remove.add(idx)
                stack.extend(node.child(i) for i in range(node.childCount()))
        self._toc = [t for i, t in enumerate(self._toc) if i not in to_remove]
        self._toc = pdf_service.normalize_toc(self._toc)
        self._rebuild_tree()
        has = bool(self._toc)
        self.export_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        self.status_label.setText(f"剩余 {len(self._toc)} 条书签")

    # ---- 导出 ----
    def _export(self):
        if not self._pdf_path or not self._toc:
            return
        stem = os.path.splitext(os.path.basename(self._pdf_path))[0]
        out_path, _ = QFileDialog.getSaveFileName(
            self, "保存带书签的 PDF", f"{stem}_带书签.pdf", "PDF 文件 (*.pdf)")
        if not out_path:
            return
        self.export_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self._worker = WriteBookmarksWorker(self._pdf_path, self._toc, out_path, self)
        self._worker.finished_ok.connect(self._on_exported)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_exported(self, path: str):
        self.progress.setVisible(False)
        self.export_btn.setEnabled(True)
        InfoBar.success("导出完成", f"已导出：{path}", parent=self,
                        position=InfoBarPosition.TOP, duration=5000)
