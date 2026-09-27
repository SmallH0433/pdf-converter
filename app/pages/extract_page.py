"""页码节选页面：勾选或输入范围，导出为新 PDF 或图片。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from ..core import pdf_service
from ..core.workers import ConvertImagesWorker, DetectHeadingsWorker, ExtractPdfWorker, ThumbnailWorker
from .widgets import DropCard, ThumbnailGrid


class TocSelectDialog(MessageBoxBase):
    """目录多选对话框：勾选多个章节，父章节自动包含子章节。"""

    def __init__(self, toc: list[dict], checked: set[int], parent=None):
        super().__init__(parent)
        self._toc = toc
        self._cascading = False

        self.titleLabel = SubtitleLabel("选择章节（可多选）", self)
        self.viewLayout.addWidget(self.titleLabel)
        hint = CaptionLabel("勾选父章节会自动包含其全部子章节。", self)
        self.viewLayout.addWidget(hint)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["标题", "页码"])
        self.tree.setMinimumSize(480, 320)
        self._build_tree(checked)
        self.tree.expandAll()
        self.viewLayout.addWidget(self.tree)

        btn_row = QHBoxLayout()
        select_all_btn = PushButton("全选", self)
        select_all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        select_none_btn = PushButton("全不选", self)
        select_none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(select_none_btn)
        btn_row.addStretch(1)
        self.viewLayout.addLayout(btn_row)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

    def _build_tree(self, checked: set[int]):
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for idx, item_data in enumerate(self._toc):
            node = QTreeWidgetItem([item_data["title"], str(item_data["page"] + 1)])
            node.setData(0, Qt.ItemDataRole.UserRole, idx)
            node.setToolTip(0, item_data["title"])
            node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            node.setCheckState(
                0, Qt.CheckState.Checked if idx in checked else Qt.CheckState.Unchecked)
            while stack and stack[-1][0] >= item_data["level"]:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.tree.addTopLevelItem(node)
            stack.append((item_data["level"], node))
        self.tree.setColumnWidth(0, 380)
        self.tree.itemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, item: QTreeWidgetItem, _col: int):
        """勾选/取消父章节时，级联到所有子章节。"""
        if self._cascading:
            return
        self._cascading = True
        try:
            state = item.checkState(0)
            stack = [item.child(i) for i in range(item.childCount())]
            while stack:
                node = stack.pop()
                node.setCheckState(0, state)
                stack.extend(node.child(i) for i in range(node.childCount()))
        finally:
            self._cascading = False

    def _set_all(self, state: Qt.CheckState):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)

    def checked_indexes(self) -> set[int]:
        result: set[int] = set()
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            node = stack.pop()
            if node.checkState(0) == Qt.CheckState.Checked:
                idx = node.data(0, Qt.ItemDataRole.UserRole)
                if idx is not None:
                    result.add(idx)
            stack.extend(node.child(i) for i in range(node.childCount()))
        return result


class ExtractPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("extractPage")
        self._pdf_path: str | None = None
        self._total_pages = 0
        self._worker = None
        self._thumb_worker: ThumbnailWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(14)

        root.addWidget(StrongBodyLabel("页码节选", self))

        self.drop_card = DropCard(self)
        self.drop_card.pdf_selected.connect(self._load_pdf)
        root.addWidget(self.drop_card)

        # 范围输入 + 快捷按钮
        range_row = QHBoxLayout()
        range_row.addWidget(BodyLabel("页码范围：", self))
        self.range_edit = LineEdit(self)
        self.range_edit.setPlaceholderText("如 1-3,5；或在下方缩略图中勾选")
        self.range_edit.editingFinished.connect(self._apply_range)
        range_row.addWidget(self.range_edit, 1)
        apply_btn = PushButton("应用范围", self)
        apply_btn.clicked.connect(self._apply_range)
        select_all_btn = PushButton("全选", self)
        select_all_btn.clicked.connect(lambda: self._set_all(True))
        select_none_btn = PushButton("全不选", self)
        select_none_btn.clicked.connect(lambda: self._set_all(False))
        range_row.addWidget(apply_btn)
        range_row.addWidget(select_all_btn)
        range_row.addWidget(select_none_btn)
        root.addLayout(range_row)

        self.selected_label = CaptionLabel("尚未加载文件", self)
        root.addWidget(self.selected_label)

        # 目录快速节选
        toc_card = CardWidget(self)
        toc_row = QHBoxLayout(toc_card)
        toc_row.setContentsMargins(20, 12, 20, 12)
        toc_row.setSpacing(12)
        toc_row.addWidget(BodyLabel("目录节选：", self))
        self.toc_select_btn = PushButton("选择章节（可多选）…", self)
        self.toc_select_btn.clicked.connect(self._open_toc_dialog)
        toc_row.addWidget(self.toc_select_btn)
        self.toc_summary = CaptionLabel("", self)
        toc_row.addWidget(self.toc_summary, 1)
        self.toc_detect_btn = PushButton("未检测到书签，点击自动识别目录", self)
        self.toc_detect_btn.clicked.connect(self._detect_toc)
        toc_row.addWidget(self.toc_detect_btn)
        root.addWidget(toc_card)
        self._toc: list[dict] = []
        self._toc_checked: set[int] = set()
        self._toc_worker = None
        self._refresh_toc_ui()

        # 大文档默认不自动生成缩略图（上千页渲染耗时分钟级）
        self.load_thumbs_btn = PushButton("生成全部页面缩略图（较慢）", self)
        self.load_thumbs_btn.setVisible(False)
        self.load_thumbs_btn.clicked.connect(self._start_thumbnail_worker)
        root.addWidget(self.load_thumbs_btn)

        # 缩略图网格
        self.grid = ThumbnailGrid(self)
        self.grid.selection_changed.connect(self._on_selection)
        self.grid.build_progress.connect(self._on_build_progress)
        self.grid.setMinimumHeight(260)
        root.addWidget(self.grid, 1)

        # 导出设置
        export_card = CardWidget(self)
        export_row = QHBoxLayout(export_card)
        export_row.setContentsMargins(20, 14, 20, 14)
        export_row.setSpacing(12)
        export_row.addWidget(BodyLabel("导出为：", self))
        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems(["新 PDF", "图片"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        export_row.addWidget(self.mode_combo)

        export_row.addWidget(BodyLabel("格式：", self))
        self.format_combo = ComboBox(self)
        self.format_combo.addItems(pdf_service.IMAGE_FORMATS)
        export_row.addWidget(self.format_combo)

        export_row.addWidget(BodyLabel("DPI：", self))
        self.dpi_spin = SpinBox(self)
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(150)
        export_row.addWidget(self.dpi_spin)
        export_row.addStretch(1)
        root.addWidget(export_card)

        action_row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("导出", self)
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

        self._on_mode_changed(self.mode_combo.currentText())

    # ---- 文件加载 ----
    def _load_pdf(self, path: str):
        try:
            doc = pdf_service.open_pdf(path)
            self._total_pages = doc.page_count
            existing_toc = doc.get_toc()
            doc.close()
        except Exception as e:
            InfoBar.error("打开失败", str(e), parent=self, position=InfoBarPosition.TOP)
            return
        self._pdf_path = path
        self._toc = [{"level": lvl, "title": title, "page": page - 1}
                     for lvl, title, page in existing_toc]
        self._refresh_toc_ui()
        self.drop_card.set_file(path)
        self.start_btn.setEnabled(True)
        self.grid.build(self._total_pages)
        self._update_selected_label()

        self._stop_thumbnail_worker()
        if self._total_pages > self.AUTO_THUMB_MAX_PAGES:
            self.load_thumbs_btn.setText(
                f"生成全部 {self._total_pages} 页缩略图（页数较多，耗时较长）")
            self.load_thumbs_btn.setVisible(True)
        else:
            self.load_thumbs_btn.setVisible(False)
            self._start_thumbnail_worker()

    AUTO_THUMB_MAX_PAGES = 300

    def _start_thumbnail_worker(self):
        if not self._pdf_path:
            return
        self.load_thumbs_btn.setVisible(False)
        self._stop_thumbnail_worker()
        self._thumb_worker = ThumbnailWorker(self._pdf_path, self._total_pages, parent=self)
        self._thumb_worker.batch_ready.connect(self.grid.set_thumbnails_batch)
        self._thumb_worker.start()

    def _stop_thumbnail_worker(self):
        if self._thumb_worker:
            try:
                self._thumb_worker.batch_ready.disconnect(self.grid.set_thumbnails_batch)
            except (RuntimeError, TypeError):
                pass
            self._thumb_worker.cancel()
            self._thumb_worker = None

    # ---- 选择 ----
    def _on_selection(self, _pages):
        self._update_selected_label()

    def _on_build_progress(self, done: int, total: int):
        if done < total:
            self.selected_label.setText(f"共 {total} 页 · 正在加载页面卡片 {done}/{total}…")
        else:
            self._update_selected_label()

    def _update_selected_label(self):
        pages = self.grid.selected_pages()
        if not pages:
            self.selected_label.setText(f"共 {self._total_pages} 页 · 未选择任何页")
            return
        desc = pdf_service.compress_pages([p + 1 for p in pages])
        if len(desc) > 90:
            desc = desc[:90].rsplit(",", 1)[0] + ", …"
        self.selected_label.setText(
            f"共 {self._total_pages} 页 · 已选 {len(pages)} 页：{desc}")

    def _apply_range(self):
        if not self._pdf_path:
            return
        text = self.range_edit.text().strip()
        if not text:
            return
        try:
            pages = pdf_service.parse_page_range(text, self._total_pages)
        except pdf_service.PageRangeError as e:
            InfoBar.warning("页码范围有误", str(e), parent=self, position=InfoBarPosition.TOP)
            return
        self.grid.set_selected(pages)
        self._update_selected_label()

    def _set_all(self, checked: bool):
        if checked:
            self.grid.select_all()
        else:
            self.grid.select_none()
        self._update_selected_label()

    # ---- 目录快速节选 ----
    def _refresh_toc_ui(self):
        """根据 self._toc 刷新目录节选控件；无书签时显示"自动识别"按钮。"""
        has_toc = bool(self._toc)
        self._toc_checked = set()
        self.toc_summary.setText("")
        self.toc_select_btn.setVisible(has_toc)
        self.toc_detect_btn.setVisible(self._pdf_path is not None and not has_toc)

    def _open_toc_dialog(self):
        if not self._pdf_path or not self._toc:
            return
        dialog = TocSelectDialog(self._toc, self._toc_checked, self)
        if dialog.exec():
            self._toc_checked = dialog.checked_indexes()
            self._apply_toc_selection()

    def _apply_toc_selection(self):
        if not self._toc_checked:
            self.toc_summary.setText("")
            return
        pages: set[int] = set()
        for idx in self._toc_checked:
            if 0 <= idx < len(self._toc):
                pages.update(pdf_service.section_pages(self._toc, idx, self._total_pages))
        pages_sorted = sorted(pages)
        self.grid.set_selected(pages_sorted)
        self.range_edit.setText(pdf_service.compress_pages([p + 1 for p in pages_sorted]))
        self._update_selected_label()
        self.toc_summary.setText(
            f"已选 {len(self._toc_checked)} 个章节，共 {len(pages_sorted)} 页")

    def _detect_toc(self):
        if not self._pdf_path or self._toc_worker:
            return
        self.toc_detect_btn.setEnabled(False)
        self.toc_detect_btn.setText("正在识别目录…")
        self._toc_worker = DetectHeadingsWorker(self._pdf_path, "both", 3, self)
        self._toc_worker.finished_ok.connect(self._on_toc_detected)
        self._toc_worker.failed.connect(self._on_toc_failed)
        self._toc_worker.start()

    def _on_toc_detected(self, toc: list):
        self._toc_worker = None
        self.toc_detect_btn.setEnabled(True)
        self.toc_detect_btn.setText("未检测到书签，点击自动识别目录")
        if not toc:
            InfoBar.warning("未识别到目录", "该 PDF 可能是扫描件或标题样式不明显",
                            parent=self, position=InfoBarPosition.TOP)
            return
        self._toc = toc
        self._refresh_toc_ui()
        InfoBar.success("目录识别完成", f"识别到 {len(toc)} 个章节条目",
                        parent=self, position=InfoBarPosition.TOP)

    def _on_toc_failed(self, msg: str):
        self._toc_worker = None
        self.toc_detect_btn.setEnabled(True)
        self.toc_detect_btn.setText("未检测到书签，点击自动识别目录")
        InfoBar.error("目录识别失败", msg, parent=self, position=InfoBarPosition.TOP)

    def _on_mode_changed(self, mode: str):
        is_image = mode == "图片"
        self.format_combo.setEnabled(is_image)
        self.dpi_spin.setEnabled(is_image)

    # ---- 导出 ----
    def _start(self):
        if not self._pdf_path:
            return
        pages = self.grid.selected_pages()
        if not pages:
            InfoBar.warning("未选择页面", "请先勾选缩略图或输入页码范围",
                            parent=self, position=InfoBarPosition.TOP)
            return

        stem = os.path.splitext(os.path.basename(self._pdf_path))[0]
        if self.mode_combo.currentText() == "新 PDF":
            out_path, _ = QFileDialog.getSaveFileName(
                self, "保存新 PDF", f"{stem}_节选.pdf", "PDF 文件 (*.pdf)")
            if not out_path:
                return
            self._run_pdf_worker(pages, out_path)
        else:
            out_dir = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
            if not out_dir:
                return
            self._run_image_worker(pages, out_dir)

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

    def _run_pdf_worker(self, pages, out_path):
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # 忙等状态
        self._worker = ExtractPdfWorker(self._pdf_path, pages, out_path, self)
        self._worker.finished_ok.connect(
            lambda p: self._on_done(f"已导出：{p}"))
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _run_image_worker(self, pages, out_dir):
        self.progress.setVisible(True)
        self.progress.setRange(0, len(pages))
        self.progress.setValue(0)
        self._worker = ConvertImagesWorker(
            self._pdf_path, pages, out_dir,
            self.format_combo.currentText(), self.dpi_spin.value(), 90, False, self)
        self._worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self._worker.finished_ok.connect(
            lambda files: self._on_done(f"已生成 {len(files)} 张图片"))
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _cancel(self):
        if self._worker and hasattr(self._worker, "cancel"):
            self._worker.cancel()
        self._finish_ui()

    def _finish_ui(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _on_done(self, msg: str):
        self._finish_ui()
        self.progress.setVisible(False)
        InfoBar.success("导出完成", msg, parent=self,
                        position=InfoBarPosition.TOP, duration=5000)

    def _on_fail(self, msg: str):
        self._finish_ui()
        self.progress.setVisible(False)
        InfoBar.error("导出失败", msg, parent=self, position=InfoBarPosition.TOP)
