"""PDF OCR 页面：为扫描版 PDF 添加可搜索的隐形文字层；OCR 组件按需一键安装。"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
)

from ..core import ocr_service
from ..core.workers import OcrInstallWorker, OcrPdfWorker
from .widgets import DropCard


class OcrPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ocrPage")
        self._pdf_path: str | None = None
        self._worker = None
        self._install_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(14)

        root.addWidget(StrongBodyLabel("PDF OCR 文字识别", self))
        hint = CaptionLabel(
            "为扫描版 PDF 添加隐形文字层（页面外观不变），识别后文字可搜索、可复制，"
            "「书签生成」等功能也能正常读取。已有文字的页面会自动跳过。", self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.drop_card = DropCard(self)
        self.drop_card.pdf_selected.connect(self._load_pdf)
        root.addWidget(self.drop_card)

        # 引擎状态与 GPU 加速一键安装（加速包可装多个，开始任务时自动选择最佳后端）
        self.engine_card = CardWidget(self)
        engine_col = QVBoxLayout(self.engine_card)
        engine_col.setContentsMargins(20, 14, 20, 14)
        engine_col.setSpacing(10)
        self.engine_label = BodyLabel("", self)
        self.engine_label.setWordWrap(True)
        engine_col.addWidget(self.engine_label)
        self.accel_btn_row = QHBoxLayout()
        self.accel_btn_row.setSpacing(10)
        self.accel_btn_row.addStretch(1)
        engine_col.addLayout(self.accel_btn_row)
        root.addWidget(self.engine_card)

        # 是否识别批注/留言（默认不识别，与「书签生成」的 OCR 行为一致）
        self.annots_check = CheckBox(
            "识别页面上的批注与留言（手写批注墨迹一并识别，留言文字写入文字层）", self)
        root.addWidget(self.annots_check)

        # 操作行
        action_row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("开始识别", self)
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

        self.status_label = CaptionLabel("尚未加载文件", self)
        root.addWidget(self.status_label)
        root.addStretch(1)

        self._refresh_engine_ui()

    # ---- 引擎状态 / GPU 加速一键安装 ----
    _POWER_NAMES = {'ac': '插电', 'battery': '离电（电池）', 'unknown': '未知/台式机'}

    def _refresh_engine_ui(self):
        ok, reason = ocr_service.ocr_available()
        if not ok:
            self.engine_label.setText(reason)
        else:
            gpus = '、'.join(ocr_service.gpu_names()) or '未检测到'
            power = self._POWER_NAMES[ocr_service.power_state()]
            self.engine_label.setText(
                f"OCR 引擎：RapidOCR 中文模型 · 推理后端：{ocr_service.backend_name()}"
                f" · 显卡：{gpus} · 当前供电：{power}"
                f"（装有多个加速后端时，开始任务时按供电状态自动选择最佳 GPU）")
        # 重建加速包安装按钮（可装多个后端）
        while self.accel_btn_row.count() > 1:
            item = self.accel_btn_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        offers = ocr_service.accel_offers() if ok else []
        for kind, label in offers:
            btn = PrimaryPushButton(label, self)
            btn.setToolTip("安装后与其他加速后端共存，开始任务时自动选择")
            btn.clicked.connect(lambda _=False, k=kind: self._install_accel(k))
            self.accel_btn_row.insertWidget(self.accel_btn_row.count() - 1, btn)
        self.start_btn.setEnabled(ok and bool(self._pdf_path))

    def _install_accel(self, kind: str):
        for i in range(self.accel_btn_row.count()):
            w = self.accel_btn_row.itemAt(i).widget()
            if w:
                w.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status_label.setText("正在下载安装，请保持网络畅通…")
        self._install_worker = OcrInstallWorker(kind, self)
        self._install_worker.log.connect(
            lambda line: self.status_label.setText(line[:100]))
        self._install_worker.finished_ok.connect(self._on_installed)
        self._install_worker.failed.connect(self._on_install_fail)
        self._install_worker.start()

    def _on_installed(self, msg: str):
        self.progress.setVisible(False)
        self._refresh_engine_ui()
        self.status_label.setText(msg)
        InfoBar.success("安装完成", msg, parent=self,
                        position=InfoBarPosition.TOP, duration=5000)

    def _on_install_fail(self, msg: str):
        self.progress.setVisible(False)
        self._refresh_engine_ui()
        self.status_label.setText("安装失败")
        InfoBar.error("安装失败", msg, parent=self,
                      position=InfoBarPosition.TOP, duration=8000)

    # ---- 文件加载 ----
    def _load_pdf(self, path: str):
        self._pdf_path = path
        self.drop_card.set_file(path)
        ok, _ = ocr_service.ocr_available()
        self.start_btn.setEnabled(ok)
        try:
            import fitz
            doc = fitz.open(path)
            empty = sum(1 for i in range(min(doc.page_count, 20))
                        if not doc.load_page(i).get_text().strip())
            total = doc.page_count
            doc.close()
            if empty == 0:
                self.status_label.setText(f"共 {total} 页 · 前 20 页均有文字层，可能无需 OCR")
            else:
                self.status_label.setText(
                    f"共 {total} 页 · 前 20 页中 {empty} 页无文字层（扫描页），建议 OCR")
        except Exception as e:  # noqa: BLE001
            self.status_label.setText(f"读取失败：{e}")

    # ---- 识别 ----
    def _start(self):
        if not self._pdf_path:
            return
        stem = os.path.splitext(os.path.basename(self._pdf_path))[0]
        out_path, _ = QFileDialog.getSaveFileName(
            self, "保存 OCR 后的 PDF", f"{stem}_ocr.pdf", "PDF 文件 (*.pdf)")
        if not out_path:
            return
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # 总页数未知，先转圈，首帧进度后改为确定值
        self._worker = OcrPdfWorker(self._pdf_path, out_path,
                                    include_annots=self.annots_check.isChecked(),
                                    parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_progress(self, done: int, total: int):
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_label.setText(f"识别中… {done}/{total} 页")

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
            self.status_label.setText("正在取消…")

    def _finish_ui(self):
        ok, _ = ocr_service.ocr_available()
        self.start_btn.setEnabled(ok and bool(self._pdf_path))
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)

    def _on_done(self, path: str):
        self._finish_ui()
        self.status_label.setText(f"已完成：{path}")
        InfoBar.success("OCR 完成", f"已导出：{path}", parent=self,
                        position=InfoBarPosition.TOP, duration=5000)

    def _on_cancelled(self):
        self._finish_ui()
        self.status_label.setText("已取消，未生成文件")
        InfoBar.warning("已取消", "OCR 任务已取消，未生成文件",
                        parent=self, position=InfoBarPosition.TOP)

    def _on_fail(self, msg: str):
        self._finish_ui()
        InfoBar.error("操作失败", msg, parent=self, position=InfoBarPosition.TOP)
