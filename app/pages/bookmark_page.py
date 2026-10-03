"""目录/书签自动生成页面：根据 PDF 内容自动识别标题，生成目录书签并导出。"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from ..core import llm_bookmarks, llm_download, ocr_service, pdf_service
from ..core.workers import DetectHeadingsWorker, DownloadModelWorker, WriteBookmarksWorker
from .widgets import DropCard

MODES = [
    ("标题样式 + 章节编号", "both"),
    ("仅章节编号", "numbering"),
    ("仅标题样式（字号/粗体）", "font"),
]


class AddBookmarkDialog(MessageBoxBase):
    """手动添加书签标题、页码和层级。"""

    def __init__(self, total_pages: int, default_page: int = 1,
                 default_level: int = 1, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("添加书签", self)
        self.viewLayout.addWidget(self.titleLabel)

        form = QFormLayout()
        self.title_edit = LineEdit(self)
        self.title_edit.setPlaceholderText("输入书签标题")
        form.addRow("标题：", self.title_edit)

        self.page_spin = SpinBox(self)
        self.page_spin.setRange(1, max(1, total_pages))
        self.page_spin.setValue(max(1, min(default_page, total_pages)))
        form.addRow("页码：", self.page_spin)

        self.level_spin = SpinBox(self)
        self.level_spin.setRange(1, 6)
        self.level_spin.setValue(max(1, min(default_level, 6)))
        form.addRow("层级：", self.level_spin)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("添加")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)
        self.title_edit.textChanged.connect(
            lambda text: self.yesButton.setEnabled(bool(text.strip())))
        self.widget.setMinimumWidth(400)

    def bookmark(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "page": self.page_spin.value() - 1,
            "level": self.level_spin.value(),
        }


class BookmarkPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bookmarkPage")
        self._pdf_path: str | None = None
        self._total_pages = 0
        self._toc: list[dict] = []
        self._worker = None
        self._dl_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(14)

        root.addWidget(StrongBodyLabel("目录/书签自动生成", self))
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

        llm_card = CardWidget(self)
        llm_layout = QVBoxLayout(llm_card)
        llm_layout.setContentsMargins(20, 12, 20, 12)
        llm_row = QHBoxLayout()
        self.llm_check = CheckBox("使用本地大模型识别书签", self)
        self.llm_check.toggled.connect(self._toggle_llm)
        llm_row.addWidget(self.llm_check)
        self.model_combo = ComboBox(self)
        self.model_combo.setMinimumWidth(330)
        self.model_combo.setMaximumWidth(500)
        self.model_combo.setEnabled(False)
        llm_row.addWidget(self.model_combo, 1)
        self.model_refresh_btn = PushButton("刷新模型", self)
        self.model_refresh_btn.clicked.connect(self._refresh_models)
        self.model_refresh_btn.setEnabled(False)
        llm_row.addWidget(self.model_refresh_btn)
        self.model_browse_btn = PushButton("自选 GGUF…", self)
        self.model_browse_btn.clicked.connect(self._browse_model)
        self.model_browse_btn.setEnabled(False)
        llm_row.addWidget(self.model_browse_btn)
        self.model_download_btn = PrimaryPushButton("一键下载推荐模型", self)
        self.model_download_btn.setToolTip(
            f"{llm_download.RECOMMENDED_REPO}（{llm_download.RECOMMENDED_FILE}，约 2.6 GB）")
        self.model_download_btn.clicked.connect(self._download_model)
        self.model_download_btn.setEnabled(False)
        llm_row.addWidget(self.model_download_btn)
        llm_layout.addLayout(llm_row)
        # 模型下载进度（默认隐藏）
        self.dl_row = QHBoxLayout()
        self.dl_status = CaptionLabel("", self)
        self.dl_row.addWidget(self.dl_status, 1)
        self.dl_progress = ProgressBar(self)
        self.dl_progress.setMinimumWidth(220)
        self.dl_row.addWidget(self.dl_progress)
        self.dl_cancel_btn = PushButton("取消下载", self)
        self.dl_cancel_btn.clicked.connect(self._cancel_download)
        self.dl_row.addWidget(self.dl_cancel_btn)
        llm_layout.addLayout(self.dl_row)
        self._set_download_ui_visible(False)
        llm_hint = CaptionLabel(
            "模型由应用内置的 llama.cpp 引擎直接加载（有显卡则自动使用 GPU），无需安装 LM Studio。"
            "推荐 Qwen3.8-4B-Distill，可点「一键下载推荐模型」自动获取；也可自选本机 GGUF 模型。", self)
        llm_hint.setWordWrap(True)
        llm_layout.addWidget(llm_hint)
        root.addWidget(llm_card)
        self._refresh_models()

        # 操作行
        action_row = QHBoxLayout()
        self.detect_btn = PrimaryPushButton("开始识别", self)
        self.detect_btn.setEnabled(False)
        self.detect_btn.clicked.connect(self._start_detect)
        self.cancel_btn = PushButton("取消", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_detect)
        self.add_btn = PushButton("添加书签", self)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add_bookmark)
        self.delete_btn = PushButton("删除勾选/选中条目", self)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.select_all_btn = PushButton("全选结果", self)
        self.select_all_btn.setEnabled(False)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.clear_selection_btn = PushButton("取消全选", self)
        self.clear_selection_btn.setEnabled(False)
        self.clear_selection_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.export_btn = PrimaryPushButton("导出带书签的 PDF", self)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        action_row.addWidget(self.detect_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.add_btn)
        action_row.addWidget(self.delete_btn)
        action_row.addWidget(self.select_all_btn)
        action_row.addWidget(self.clear_selection_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.export_btn)
        root.addLayout(action_row)

        self.progress = ProgressBar(self)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.ocr_progress_label = CaptionLabel("OCR 进度", self)
        self.ocr_progress_label.setVisible(False)
        root.addWidget(self.ocr_progress_label)
        self.ocr_progress = ProgressBar(self)
        self.ocr_progress.setVisible(False)
        root.addWidget(self.ocr_progress)

        self.llm_progress_label = CaptionLabel("LLM 识别进度", self)
        self.llm_progress_label.setVisible(False)
        root.addWidget(self.llm_progress_label)
        self.llm_progress = ProgressBar(self)
        self.llm_progress.setVisible(False)
        root.addWidget(self.llm_progress)

        self.status_label = CaptionLabel("尚未加载文件", self)
        root.addWidget(self.status_label)
        edit_hint = CaptionLabel(
            "可手动添加书签；双击标题、页码或层级可直接编辑；勾选多条结果后可批量删除。", self)
        root.addWidget(edit_hint)

        # 书签预览树
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["标题", "页码", "层级"])
        self.tree.setColumnWidth(0, 560)
        self.tree.setColumnWidth(1, 90)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._edit_item)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setMinimumHeight(240)
        root.addWidget(self.tree, 1)

    def showEvent(self, e):
        super().showEvent(e)
        # OCR 组件可能在「PDF OCR」页刚装完，进入本页时刷新勾选框可用性
        ok, reason = ocr_service.ocr_available()
        self.ocr_check.setEnabled(ok)
        if not ok:
            self.ocr_check.setToolTip(f"OCR 不可用：{reason}")

    def _toggle_llm(self, enabled: bool):
        self.model_combo.setEnabled(enabled)
        self.model_refresh_btn.setEnabled(enabled)
        self.model_browse_btn.setEnabled(enabled)
        self.mode_combo.setEnabled(not enabled)
        self._update_download_btn()

    def _update_download_btn(self):
        has_recommended = any(
            llm_download.is_recommended(Path(self.model_combo.itemData(i)))
            for i in range(self.model_combo.count()) if self.model_combo.itemData(i))
        self.model_download_btn.setEnabled(
            self.llm_check.isChecked() and not has_recommended
            and not (self._dl_worker and self._dl_worker.isRunning()))
        self.model_download_btn.setVisible(not has_recommended)

    def _set_download_ui_visible(self, visible: bool):
        self.dl_status.setVisible(visible)
        self.dl_progress.setVisible(visible)
        self.dl_cancel_btn.setVisible(visible)

    def _download_model(self):
        if self._dl_worker and self._dl_worker.isRunning():
            return
        dest = llm_download.recommended_path(llm_bookmarks.model_store_dir()).parent
        self._set_download_ui_visible(True)
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setValue(0)
        self.dl_status.setText("正在下载推荐模型…")
        self.model_download_btn.setEnabled(False)
        self._dl_worker = DownloadModelWorker(dest, self)
        self._dl_worker.progress.connect(self._on_download_progress)
        self._dl_worker.status.connect(self.dl_status.setText)
        self._dl_worker.finished_ok.connect(self._on_downloaded)
        self._dl_worker.failed.connect(self._on_download_failed)
        self._dl_worker.start()

    def _cancel_download(self):
        if self._dl_worker:
            self._dl_worker.cancel()

    def _on_download_progress(self, done: int, total: int):
        if total > 0:
            self.dl_progress.setRange(0, total)
            self.dl_progress.setValue(done)
            self.dl_status.setText(
                f"正在下载推荐模型：{done / 2**30:.2f} / {total / 2**30:.2f} GB")
        else:
            self.dl_status.setText(f"正在下载推荐模型：{done / 2**30:.2f} GB")

    def _on_downloaded(self, path: str):
        self._set_download_ui_visible(False)
        self._refresh_models()
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == path:
                self.model_combo.setCurrentIndex(i)
                break
        InfoBar.success("下载完成", "推荐模型已就绪，可直接开始识别", parent=self,
                        position=InfoBarPosition.TOP)
        self._update_download_btn()

    def _on_download_failed(self, msg: str):
        self._set_download_ui_visible(False)
        self._update_download_btn()
        InfoBar.error("模型下载失败", msg, parent=self, position=InfoBarPosition.TOP)

    def _refresh_models(self):
        previous = self.model_combo.currentData()
        self.model_combo.clear()
        models = llm_bookmarks.list_local_models()
        recommended_idx = -1
        for path in models:
            size_gb = path.stat().st_size / (1024 ** 3)
            label = f"{path.name} · {size_gb:.1f} GB"
            if llm_download.is_recommended(path):
                label = f"{llm_download.RECOMMENDED_LABEL} · {size_gb:.1f} GB"
                recommended_idx = self.model_combo.count()
            self.model_combo.addItem(label, userData=str(path))
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index) == previous:
                self.model_combo.setCurrentIndex(index)
                break
        else:
            # 默认选中推荐模型，没有则选第一个
            if recommended_idx >= 0:
                self.model_combo.setCurrentIndex(recommended_idx)
        self._update_download_btn()

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择已下载完成的 GGUF 模型", str(llm_bookmarks.lmstudio_models_dir()),
            "GGUF 模型 (*.gguf)")
        if not path:
            return
        for index in range(self.model_combo.count()):
            if self.model_combo.itemData(index) == path:
                self.model_combo.setCurrentIndex(index)
                return
        self.model_combo.addItem(os.path.basename(path), userData=path)
        self.model_combo.setCurrentIndex(self.model_combo.count() - 1)

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
        self.add_btn.setEnabled(True)
        self._toc = []
        self.tree.clear()
        self.export_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.clear_selection_btn.setEnabled(False)
        msg = f"共 {self._total_pages} 页"
        if existing:
            msg += f" · 已有 {len(existing)} 条书签（导出时将被替换）"
        self.status_label.setText(msg)

    # ---- 识别 ----
    def _start_detect(self):
        if not self._pdf_path:
            return
        model_path = self.model_combo.currentData() if self.llm_check.isChecked() else None
        if self.llm_check.isChecked() and not model_path:
            InfoBar.warning("尚未选择模型", "请选择一个已下载完成的 GGUF 模型", parent=self,
                            position=InfoBarPosition.TOP)
            return
        mode = MODES[self.mode_combo.currentIndex()][1]
        self.detect_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.add_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        use_ocr = self.ocr_check.isChecked()
        self._last_use_ocr = use_ocr
        use_llm = bool(model_path)
        self._show_detect_progress(use_ocr, use_llm)
        self._worker = DetectHeadingsWorker(
            self._pdf_path, mode, self.level_spin.value(), use_ocr,
            self, model_path=model_path)
        if not use_ocr and not use_llm:
            self._worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self._worker.ocr_progress.connect(self._update_ocr_progress)
        self._worker.llm_progress.connect(self._update_llm_progress)
        self._worker.status.connect(self.status_label.setText)
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
            self.export_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.select_all_btn.setEnabled(False)
            self.clear_selection_btn.setEnabled(False)
            # 无文字层的扫描件：弹窗询问是否启用 OCR 重试
            ocr_ok, _ = ocr_service.ocr_available()
            if (not getattr(self, "_last_use_ocr", False) and ocr_ok
                    and self._pdf_path and not pdf_service.has_text_layer(self._pdf_path)):
                box = MessageBox(
                    "未识别到文字",
                    "未能从该 PDF 提取到文字，可能是扫描件。是否启用 OCR 重新识别？（较慢）",
                    self)
                box.yesButton.setText("启用 OCR 重试")
                box.cancelButton.setText("取消")
                if box.exec():
                    self.ocr_check.setChecked(True)
                    self._start_detect()
                    return
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
        self.select_all_btn.setEnabled(True)
        self.clear_selection_btn.setEnabled(True)

    def _on_fail(self, msg: str):
        self._finish_detect_ui()
        self.export_btn.setEnabled(bool(self._toc))
        # 失败/取消后必须更新状态文字，否则会一直停留在最后一条进度提示，看起来像卡死
        self.status_label.setText(msg)
        InfoBar.error("操作失败", msg, parent=self, position=InfoBarPosition.TOP)

    def _finish_detect_ui(self):
        self.detect_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.add_btn.setEnabled(bool(self._pdf_path))
        self._hide_progress()

    def _hide_progress(self):
        self.progress.setVisible(False)
        self.ocr_progress_label.setVisible(False)
        self.ocr_progress.setVisible(False)
        self.llm_progress_label.setVisible(False)
        self.llm_progress.setVisible(False)

    def _show_detect_progress(self, use_ocr: bool, use_llm: bool):
        self._hide_progress()
        if use_ocr:
            self.ocr_progress_label.setText("OCR 进度：0/{} 页".format(self._total_pages))
            self.ocr_progress_label.setVisible(True)
            self.ocr_progress.setVisible(True)
            self.ocr_progress.setRange(0, self._total_pages)
            self.ocr_progress.setValue(0)
        elif not use_llm:
            self.progress.setVisible(True)
            self.progress.setRange(0, self._total_pages)
            self.progress.setValue(0)
        if use_llm:
            self.llm_progress_label.setText("LLM 识别进度：等待 OCR/候选扫描完成")
            self.llm_progress_label.setVisible(True)
            self.llm_progress.setVisible(True)
            self.llm_progress.setRange(0, 1)
            self.llm_progress.setValue(0)

    def _update_ocr_progress(self, done: int, total: int):
        self.ocr_progress.setRange(0, total)
        self.ocr_progress.setValue(done)
        self.ocr_progress_label.setText(f"OCR 进度：{done}/{total} 页")

    def _update_llm_progress(self, done: int, total: int):
        self.llm_progress.setRange(0, total)
        self.llm_progress.setValue(done)
        self.llm_progress_label.setText(f"LLM 识别进度：{done}/{total}")

    # ---- 预览树 ----
    def _rebuild_tree(self, checked_indices: set[int] | None = None):
        checked_indices = checked_indices or set()
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            stack: list[tuple[int, QTreeWidgetItem]] = []
            for idx, item_data in enumerate(self._toc):
                node = QTreeWidgetItem([
                    item_data["title"], str(item_data["page"] + 1), str(item_data["level"]),
                ])
                node.setData(0, Qt.ItemDataRole.UserRole, idx)
                node.setCheckState(
                    0, Qt.CheckState.Checked if idx in checked_indices else Qt.CheckState.Unchecked)
                node.setFlags(node.flags() | Qt.ItemFlag.ItemIsEditable)
                node.setToolTip(0, "双击编辑标题；勾选后可批量删除")
                node.setToolTip(1, "双击编辑页码")
                node.setToolTip(2, "双击编辑层级（1 到 6）")
                while stack and stack[-1][0] >= item_data["level"]:
                    stack.pop()
                if stack:
                    stack[-1][1].addChild(node)
                else:
                    self.tree.addTopLevelItem(node)
                stack.append((item_data["level"], node))
            self.tree.expandAll()
        finally:
            self.tree.blockSignals(False)

    def _edit_item(self, item: QTreeWidgetItem, column: int):
        if column in (0, 1, 2):
            self.tree.editItem(item, column)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is None or not 0 <= idx < len(self._toc):
            return
        if column == 0:
            title = item.text(0).strip()
            if title:
                self._toc[idx]["title"] = title
            else:
                self.tree.blockSignals(True)
                item.setText(0, self._toc[idx]["title"])
                self.tree.blockSignals(False)
                InfoBar.warning("标题不能为空", "请为书签输入标题", parent=self,
                                position=InfoBarPosition.TOP)
        elif column == 1:
            try:
                page = int(item.text(1).strip())
            except ValueError:
                page = 0
            if 1 <= page <= self._total_pages:
                self._toc[idx]["page"] = page - 1
            else:
                self.tree.blockSignals(True)
                item.setText(1, str(self._toc[idx]["page"] + 1))
                self.tree.blockSignals(False)
                InfoBar.warning("页码无效", f"请输入 1 到 {self._total_pages} 之间的页码",
                                parent=self, position=InfoBarPosition.TOP)
        elif column == 2:
            try:
                level = int(item.text(2).strip())
            except ValueError:
                level = 0
            if 1 <= level <= self.level_spin.maximum():
                checked = self._checked_indices()
                self._toc[idx]["level"] = level
                self._toc = pdf_service.normalize_toc(self._toc)
                self._rebuild_tree(checked)
            else:
                self.tree.blockSignals(True)
                item.setText(2, str(self._toc[idx]["level"]))
                self.tree.blockSignals(False)
                InfoBar.warning("层级无效", f"请输入 1 到 {self.level_spin.maximum()} 之间的层级",
                                parent=self, position=InfoBarPosition.TOP)

    def _all_tree_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        try:
            for item in self._all_tree_items():
                item.setCheckState(0, state)
        finally:
            self.tree.blockSignals(False)

    def _checked_indices(self) -> set[int]:
        return {
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self._all_tree_items()
            if item.checkState(0) == Qt.CheckState.Checked
        }

    def _add_bookmark(self):
        if not self._pdf_path or self._total_pages < 1:
            return
        default_page = 1
        default_level = 1
        current = self.tree.currentItem()
        if current is not None:
            idx = current.data(0, Qt.ItemDataRole.UserRole)
            if idx is not None and 0 <= idx < len(self._toc):
                default_page = self._toc[idx]["page"] + 1
                default_level = self._toc[idx]["level"]
        dialog = AddBookmarkDialog(
            self._total_pages, default_page=default_page,
            default_level=default_level, parent=self)
        if dialog.exec():
            self._insert_bookmark(dialog.bookmark())

    def _insert_bookmark(self, bookmark: dict):
        """按页码插入手动书签，并保持现有勾选状态。"""
        title = str(bookmark.get("title", "")).strip()
        page = int(bookmark.get("page", -1))
        level = int(bookmark.get("level", 1))
        if not title or not 0 <= page < self._total_pages or not 1 <= level <= 6:
            raise ValueError("手动书签数据无效")

        insert_at = next(
            (i for i, item in enumerate(self._toc) if item["page"] > page),
            len(self._toc),
        )
        checked = {
            idx if idx < insert_at else idx + 1
            for idx in self._checked_indices()
        }
        self._toc.insert(insert_at, {"title": title, "page": page, "level": level})
        self._toc = pdf_service.normalize_toc(self._toc)
        self._rebuild_tree(checked)
        for item in self._all_tree_items():
            if item.data(0, Qt.ItemDataRole.UserRole) == insert_at:
                self.tree.setCurrentItem(item)
                break

        self.export_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.select_all_btn.setEnabled(True)
        self.clear_selection_btn.setEnabled(True)
        self.status_label.setText(
            f"共 {len(self._toc)} 条书签 · 已添加“{title}”（第 {page + 1} 页）")

    def _delete_selected(self):
        items = list(self.tree.selectedItems())
        items.extend(item for item in self._all_tree_items()
                     if item.checkState(0) == Qt.CheckState.Checked and item not in items)
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
        self.select_all_btn.setEnabled(has)
        self.clear_selection_btn.setEnabled(has)
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
        self._hide_progress()
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self._worker = WriteBookmarksWorker(self._pdf_path, self._toc, out_path, self)
        self._worker.finished_ok.connect(self._on_exported)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_exported(self, path: str):
        self._hide_progress()
        self.export_btn.setEnabled(True)
        InfoBar.success("导出完成", f"已导出：{path}", parent=self,
                        position=InfoBarPosition.TOP, duration=5000)
