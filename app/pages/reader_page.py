"""阅读器：PDF 预览、手写笔标注（压感）、留言便签、全文查找（可选 OCR）。

手写输入按操作系统选择对应原生 API（见 core/pen_input.py：Windows→Windows Ink，
Android→MotionEvent 触控笔，macOS→NSEvent 数位板；iPadOS 无法运行本程序），
支持压感（笔迹粗细随压力变化）与笔的橡皮擦端；桌面平台鼠标也可书写（无压感），
触屏平台（Android）手指专用于滚动翻页、只有手写笔书写。
标注（墨迹 / 便签）即时写入 PDF 文档对象，「保存」增量写回原文件，
「另存为」导出副本，便签为标准 PDF 注释，其他阅读器可见。
"""
from __future__ import annotations

import os

import fitz  # PyMuPDF
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    MessageBox,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    TransparentToolButton,
)

from ..core import ocr_service, pen_input
from ..core.workers import SearchWorker, ThumbnailWorker

PEN_COLORS = {"红": (1.0, 0.0, 0.0), "黑": (0.0, 0.0, 0.0),
              "蓝": (0.0, 0.35, 1.0), "绿": (0.0, 0.6, 0.2)}
ERASE_RADIUS = 8.0  # 橡皮擦半径（PDF pt）


def _seg_dist(px: float, py: float, a: tuple, b: tuple) -> float:
    """点到线段 (a, b) 的距离。"""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


class PageCanvas(QWidget):
    """单页画布：渲染页面位图，处理手写 / 橡皮 / 便签交互，叠加搜索高亮。"""

    annot_added = Signal(int)      # 新建注释的 xref
    annot_deleted = Signal(int)    # 被擦除注释的 xref
    note_place = Signal(float, float)  # 请求在 (x, y)（PDF 坐标）放置留言
    note_clicked = Signal(object)      # 点击了已有便签（fitz.Annot）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking, True)
        self._doc: fitz.Document | None = None
        self._page_index = 0
        self.zoom = 1.5
        self.tool = "select"  # select / pen / note / eraser
        self.pen_color = PEN_COLORS["红"]
        self.pen_width = 3
        self._pixmap: QPixmap | None = None
        self._stroke: list[tuple[float, float, float]] = []
        self._stroking = False
        self._erasing = False
        self._highlights: list[tuple[fitz.Rect, bool]] = []

    # ---- 渲染 ----

    def set_document(self, doc: fitz.Document | None, page_index: int = 0):
        self._doc = doc
        self._page_index = page_index
        self._stroke = []
        self._stroking = self._erasing = False
        self.render()

    def render(self):
        """按当前缩放重渲染页面（注释由 MuPDF 画进位图）。"""
        if not self._doc:
            self._pixmap = None
            self.update()
            return
        page = self._doc.load_page(self._page_index)
        dpr = self.devicePixelRatioF()
        m = fitz.Matrix(self.zoom * dpr, self.zoom * dpr)
        pix = page.get_pixmap(matrix=m, alpha=False, annots=True)
        stride = getattr(pix, "stride", pix.width * 3)
        img = QImage(pix.samples, pix.width, pix.height, stride,
                     QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img.copy())
        pm.setDevicePixelRatio(dpr)
        self._pixmap = pm
        self.setFixedSize(max(1, round(page.rect.width * self.zoom)),
                          max(1, round(page.rect.height * self.zoom)))
        self.update()

    def set_highlights(self, items: list[tuple[fitz.Rect, bool]]):
        """搜索高亮：[(页面矩形, 是否当前条)]。"""
        self._highlights = items
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        if not self._pixmap:
            p.setPen(QColor(150, 150, 150))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "尚未加载 PDF")
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(QPointF(0, 0), self._pixmap)
        # 搜索高亮
        z = self.zoom
        for rect, current in self._highlights:
            r = QRectF(rect.x0 * z, rect.y0 * z,
                       rect.width * z, rect.height * z)
            color = QColor(255, 140, 0, 130) if current else QColor(255, 235, 59, 110)
            p.fillRect(r, color)
        # 进行中的笔画（压感宽度）
        if self._stroke:
            c = self.pen_color
            color = QColor.fromRgbF(c[0], c[1], c[2])
            if len(self._stroke) == 1:
                x, y, pr = self._stroke[0]
                p.setPen(QPen(color, max(0.6, self.pen_width * pr * z),
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawPoint(QPointF(x * z, y * z))
            else:
                for i in range(1, len(self._stroke)):
                    x0, y0, p0 = self._stroke[i - 1]
                    x1, y1, p1 = self._stroke[i]
                    w = max(0.6, self.pen_width * (p0 + p1) / 2 * z)
                    p.setPen(QPen(color, w, Qt.PenStyle.SolidLine,
                                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    p.drawLine(QPointF(x0 * z, y0 * z), QPointF(x1 * z, y1 * z))

    # ---- 坐标换算 ----

    def _to_pdf(self, pos: QPointF) -> tuple[float, float]:
        return pos.x() / self.zoom, pos.y() / self.zoom

    # ---- 手写笔（各平台原生手写 API → QTabletEvent，见 core/pen_input.py） ----

    def tabletEvent(self, e):
        kind = pen_input.pen_kind(e)  # pen / eraser / finger / cursor
        if kind == "finger":
            e.ignore()  # 手指交给滚动手势（Android 等触屏平台）
            return
        etype = e.type()
        if self.tool == "eraser" or (self.tool == "pen" and kind == "eraser"):
            if etype == QEvent.Type.TabletPress:
                self._erasing = True
                self._erase_at(e.position())
                e.accept()
            elif etype == QEvent.Type.TabletMove and self._erasing:
                self._erase_at(e.position())
                e.accept()
            elif etype == QEvent.Type.TabletRelease:
                self._erasing = False
                e.accept()
            return
        if self.tool == "pen":
            if etype == QEvent.Type.TabletPress:
                self._begin_stroke(e.position(), max(e.pressure(), 0.05))
                e.accept()
            elif etype == QEvent.Type.TabletMove and self._stroking:
                self._extend_stroke(e.position(), max(e.pressure(), 0.05))
                e.accept()
            elif etype == QEvent.Type.TabletRelease and self._stroking:
                self._end_stroke()
                e.accept()
            return
        e.ignore()

    # ---- 鼠标（无压感兜底；便签 / 选择点击） ----

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self._doc:
            return
        pos = e.position()
        if self.tool == "pen":
            if not pen_input.mouse_draws():
                return  # Android 等触屏平台：手指用于滚动翻页，仅手写笔书写
            self._begin_stroke(pos, 0.6)
        elif self.tool == "eraser":
            if not pen_input.mouse_draws():
                return
            self._erasing = True
            self._erase_at(pos)
        else:  # note / select：点击已有便签则编辑，note 工具点空白则新建
            x, y = self._to_pdf(pos)
            annot = self._text_annot_at(x, y)
            if annot is not None:
                self.note_clicked.emit(annot)
            elif self.tool == "note":
                self.note_place.emit(x, y)

    def mouseMoveEvent(self, e):
        if self._stroking and e.buttons() & Qt.MouseButton.LeftButton:
            self._extend_stroke(e.position(), 0.6)
        elif self._erasing and e.buttons() & Qt.MouseButton.LeftButton:
            self._erase_at(e.position())

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._stroking:
            self._end_stroke()
        self._erasing = False

    # ---- 笔画 ----

    def _begin_stroke(self, pos: QPointF, pressure: float):
        if not self._doc:
            return
        self._stroking = True
        x, y = self._to_pdf(pos)
        self._stroke = [(x, y, pressure)]

    def _extend_stroke(self, pos: QPointF, pressure: float):
        if not self._stroking:
            return
        x, y = self._to_pdf(pos)
        lx, ly, _ = self._stroke[-1]
        if abs(x - lx) + abs(y - ly) < 0.4:  # 忽略过密采样点
            return
        self._stroke.append((x, y, pressure))
        self.update()

    def _end_stroke(self):
        self._stroking = False
        pts = self._stroke
        self._stroke = []
        if not pts or not self._doc:
            return
        if len(pts) == 1:  # 单击成点
            x, y, pr = pts[0]
            pts = [(x, y, pr), (x + 0.01, y + 0.01, pr)]
        page = self._doc.load_page(self._page_index)
        annot = page.add_ink_annot([[(x, y) for x, y, _ in pts]])
        avg_p = sum(p for _, _, p in pts) / len(pts)
        annot.set_colors(stroke=self.pen_color)
        annot.set_border(width=max(0.4, self.pen_width * avg_p))
        annot.update()
        self.annot_added.emit(annot.xref)
        self.render()

    # ---- 橡皮擦 ----

    def _erase_at(self, pos: QPointF):
        if not self._doc:
            return
        x, y = self._to_pdf(pos)
        r = ERASE_RADIUS
        hit = fitz.Rect(x - r, y - r, x + r, y + r)
        page = self._doc.load_page(self._page_index)
        deleted = False
        for annot in list(page.annots(types=(fitz.PDF_ANNOT_INK,))):
            if annot.rect.intersects(hit) and self._ink_near(annot, x, y, r):
                xref = annot.xref
                page.delete_annot(annot)
                self.annot_deleted.emit(xref)
                deleted = True
        if deleted:
            self.render()

    @staticmethod
    def _ink_near(annot, x: float, y: float, r: float) -> bool:
        """点 (x, y) 到笔画任意线段的距离不超过 r 视为命中。"""
        try:
            for stroke in annot.vertices or []:
                pts = [(pt[0], pt[1]) for pt in stroke]
                for i in range(1, len(pts)):
                    if _seg_dist(x, y, pts[i - 1], pts[i]) <= r:
                        return True
                if len(pts) == 1 and _seg_dist(x, y, pts[0], pts[0]) <= r:
                    return True
        except (TypeError, IndexError):
            return True  # 顶点结构异常时按包围盒判定
        return False

    # ---- 便签命中 ----

    def _text_annot_at(self, x: float, y: float):
        page = self._doc.load_page(self._page_index)
        pt = fitz.Point(x, y)
        for annot in page.annots(types=(fitz.PDF_ANNOT_TEXT,)):
            r = annot.rect
            if fitz.Rect(r.x0 - 4, r.y0 - 4, r.x1 + 4, r.y1 + 4).contains(pt):
                return annot
        return None


class NoteDialog(MessageBoxBase):
    """留言编辑对话框：新建 / 编辑 / 删除。"""

    def __init__(self, text: str = "", deletable: bool = False, parent=None):
        super().__init__(parent)
        self.deleted = False
        self.titleLabel = SubtitleLabel("留言", self)
        self.edit = QPlainTextEdit(self)
        self.edit.setPlainText(text)
        self.edit.setMinimumSize(360, 120)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.edit)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        if deletable:
            self.delete_btn = PushButton("删除", self)
            self.delete_btn.clicked.connect(self._on_delete)
            self.buttonLayout.insertWidget(1, self.delete_btn)

    def _on_delete(self):
        self.deleted = True
        self.done(2)

    def text(self) -> str:
        return self.edit.toPlainText().strip()


class ReaderPage(QWidget):
    """阅读器页面。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("readerPage")
        self.setAcceptDrops(True)
        self._doc: fitz.Document | None = None
        self._pdf_path: str | None = None
        self._page_index = 0
        self._dirty = False
        self._undo_stack: list[tuple[int, int]] = []  # (页码, 注释 xref)
        self._thumb_worker: ThumbnailWorker | None = None
        self._search_worker: SearchWorker | None = None
        self._hits: list[dict] = []
        self._current_hit = -1
        self._fit_width = True

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)

        # ---- 工具行 1：文件 / 翻页 / 缩放 ----
        bar1 = CardWidget(self)
        row1 = QHBoxLayout(bar1)
        row1.setContentsMargins(14, 8, 14, 8)
        row1.setSpacing(8)
        self.open_btn = PushButton("打开 PDF", bar1)
        self.open_btn.clicked.connect(self._open_dialog)
        row1.addWidget(self.open_btn)
        self.file_label = CaptionLabel("可拖入 PDF 文件", bar1)
        row1.addWidget(self.file_label)
        row1.addStretch(1)

        self.prev_btn = TransparentToolButton(FIF.LEFT_ARROW, bar1)
        self.next_btn = TransparentToolButton(FIF.RIGHT_ARROW, bar1)
        self.prev_btn.setToolTip("上一页")
        self.next_btn.setToolTip("下一页")
        self.prev_btn.clicked.connect(lambda: self._goto_page(self._page_index - 1))
        self.next_btn.clicked.connect(lambda: self._goto_page(self._page_index + 1))
        self.page_edit = LineEdit(bar1)
        self.page_edit.setFixedWidth(56)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.returnPressed.connect(self._on_page_input)
        self.page_total = BodyLabel(" / 0", bar1)
        for w in (self.prev_btn, self.page_edit, self.page_total, self.next_btn):
            row1.addWidget(w)
        row1.addStretch(1)

        self.zoom_out_btn = TransparentToolButton(FIF.ZOOM_OUT, bar1)
        self.zoom_in_btn = TransparentToolButton(FIF.ZOOM_IN, bar1)
        self.fit_btn = TransparentToolButton(FIF.FIT_PAGE, bar1)
        self.fit_btn.setCheckable(True)
        self.fit_btn.setChecked(True)
        self.zoom_out_btn.setToolTip("缩小")
        self.zoom_in_btn.setToolTip("放大")
        self.fit_btn.setToolTip("适合宽度")
        self.zoom_out_btn.clicked.connect(lambda: self._zoom_by(0.85))
        self.zoom_in_btn.clicked.connect(lambda: self._zoom_by(1.18))
        self.fit_btn.clicked.connect(self._toggle_fit)
        self.zoom_label = BodyLabel("", bar1)
        self.zoom_label.setFixedWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self.zoom_out_btn, self.zoom_label, self.zoom_in_btn, self.fit_btn):
            row1.addWidget(w)
        root.addWidget(bar1)

        # ---- 工具行 2：标注工具 / 保存 / 查找 ----
        bar2 = CardWidget(self)
        row2 = QHBoxLayout(bar2)
        row2.setContentsMargins(14, 8, 14, 8)
        row2.setSpacing(8)
        self.tool_btns: dict[str, ToolButton] = {}
        for key, icon, tip in (
            ("select", FIF.MOVE, "选择（点击便签可编辑）"),
            ("pen", FIF.PENCIL_INK, f"手写标注（{pen_input.backend_name()}，支持压感）"),
            ("note", FIF.QUICK_NOTE, "留言便签"),
            ("eraser", FIF.ERASE_TOOL, "橡皮擦（手写笔橡皮端自动切换）"),
        ):
            btn = ToolButton(icon, bar2)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, k=key: self._set_tool(k))
            self.tool_btns[key] = btn
            row2.addWidget(btn)
        self.tool_btns["select"].setChecked(True)

        row2.addWidget(CaptionLabel("笔色", bar2))
        self.color_combo = ComboBox(bar2)
        self.color_combo.addItems(PEN_COLORS.keys())
        self.color_combo.setFixedWidth(84)
        self.color_combo.currentTextChanged.connect(self._on_pen_style)
        row2.addWidget(self.color_combo)
        row2.addWidget(CaptionLabel("粗细", bar2))
        self.width_spin = SpinBox(bar2)
        self.width_spin.setRange(1, 12)
        self.width_spin.setValue(3)
        # fluent SpinBox 右侧内嵌上下按钮约占 71px，宽度太小会把数字挤出可视区
        self.width_spin.setFixedWidth(120)
        self.width_spin.valueChanged.connect(self._on_pen_style)
        row2.addWidget(self.width_spin)

        self.undo_btn = ToolButton(FIF.HISTORY, bar2)
        self.undo_btn.setToolTip("撤销上一笔 (Ctrl+Z)")
        self.undo_btn.clicked.connect(self._undo)
        row2.addWidget(self.undo_btn)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._undo)

        row2.addStretch(1)
        self.search_btn = ToolButton(FIF.SEARCH, bar2)
        self.search_btn.setCheckable(True)
        self.search_btn.setToolTip("查找内容")
        self.search_btn.clicked.connect(self._toggle_search_panel)
        row2.addWidget(self.search_btn)
        self.save_btn = ToolButton(FIF.SAVE, bar2)
        self.save_btn.setToolTip("保存（写回原文件）")
        self.save_btn.clicked.connect(self._save)
        self.save_as_btn = ToolButton(FIF.SAVE_AS, bar2)
        self.save_as_btn.setToolTip("另存为副本")
        self.save_as_btn.clicked.connect(self._save_as)
        row2.addWidget(self.save_btn)
        row2.addWidget(self.save_as_btn)
        root.addWidget(bar2)

        # ---- 主体：缩略图 / 画布 / 查找面板 ----
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.thumb_list = ListWidget(splitter)
        self.thumb_list.setMinimumWidth(150)
        self.thumb_list.setMaximumWidth(220)
        self.thumb_list.setIconSize(self.thumb_list.iconSize())
        self.thumb_list.currentRowChanged.connect(self._on_thumb_row)
        splitter.addWidget(self.thumb_list)

        self.canvas = PageCanvas()
        self.canvas.annot_added.connect(self._on_annot_added)
        self.canvas.annot_deleted.connect(self._on_annot_deleted)
        self.canvas.note_place.connect(self._place_note)
        self.canvas.note_clicked.connect(self._edit_note)
        self.scroll = ScrollArea(splitter)
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.viewport().installEventFilter(self)
        pen_input.enable_kinetic_scroll(self.scroll)  # 触屏平台手势/惯性滚动
        splitter.addWidget(self.scroll)

        # 查找面板
        self.search_panel = CardWidget(splitter)
        self.search_panel.setMinimumWidth(260)
        self.search_panel.setMaximumWidth(360)
        sp = QVBoxLayout(self.search_panel)
        sp.setContentsMargins(16, 12, 16, 12)
        sp.setSpacing(8)
        sp.addWidget(StrongBodyLabel("查找内容", self.search_panel))
        self.search_edit = SearchLineEdit(self.search_panel)
        self.search_edit.setPlaceholderText("输入要查找的文本，回车开始")
        self.search_edit.searchSignal.connect(lambda _t: self._start_search())
        sp.addWidget(self.search_edit)
        self.ocr_check = CheckBox("识别扫描页 (OCR，较慢)", self.search_panel)
        ok, reason = ocr_service.ocr_available()
        self.ocr_check.setEnabled(ok)
        if not ok:
            self.ocr_check.setToolTip(reason)
        sp.addWidget(self.ocr_check)
        nav = QHBoxLayout()
        self.hit_prev = PushButton("上一条", self.search_panel)
        self.hit_next = PushButton("下一条", self.search_panel)
        self.hit_prev.clicked.connect(lambda: self._step_hit(-1))
        self.hit_next.clicked.connect(lambda: self._step_hit(1))
        nav.addWidget(self.hit_prev)
        nav.addWidget(self.hit_next)
        nav.addStretch(1)
        sp.addLayout(nav)
        self.search_progress = ProgressBar(self.search_panel)
        self.search_progress.setVisible(False)
        sp.addWidget(self.search_progress)
        self.search_status = CaptionLabel("", self.search_panel)
        self.search_status.setWordWrap(True)
        sp.addWidget(self.search_status)
        self.result_list = ListWidget(self.search_panel)
        self.result_list.currentRowChanged.connect(self._on_result_row)
        sp.addWidget(self.result_list, 1)
        self.search_panel.setVisible(False)
        splitter.addWidget(self.search_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter, 1)

        self.status_label = CaptionLabel(
            f"打开或拖入 PDF 开始阅读 · {pen_input.status_text()}", self)
        root.addWidget(self.status_label)

        self._update_ui_state()

    # ---- 文件打开 / 拖放 ----

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "",
                                              "PDF 文件 (*.pdf)")
        if path:
            self.load_pdf(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(
                u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.load_pdf(path)
                break

    def load_pdf(self, path: str):
        if not self.confirm_discard():
            return
        self._stop_workers()
        if self._doc:
            self._doc.close()
            self._doc = None
        try:
            self._doc = fitz.open(path)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("打开失败", str(e), parent=self,
                          position=InfoBarPosition.TOP)
            return
        self._pdf_path = path
        self._page_index = 0
        self._dirty = False
        self._undo_stack = []
        self._hits = []
        self._current_hit = -1
        self.result_list.clear()
        self.search_status.setText("")
        total = self._doc.page_count
        self.page_total.setText(f" / {total}")
        self.page_edit.setText("1")
        self.file_label.setText(os.path.basename(path))
        self.status_label.setText(
            f"{path} · 共 {total} 页 · {pen_input.status_text()}")

        # 缩略图
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        self.thumb_list.blockSignals(False)
        for i in range(total):
            item = QListWidgetItem(f"第 {i + 1} 页")
            self.thumb_list.addItem(item)
        self.thumb_list.setCurrentRow(0)
        self._thumb_worker = ThumbnailWorker(path, total, width=150, parent=self)
        self._thumb_worker.batch_ready.connect(self._on_thumbs)
        self._thumb_worker.start()

        self._fit_width = True
        self.fit_btn.setChecked(True)
        from PySide6.QtCore import QTimer
        # 等布局完成后再走完整的翻页流程（set_document + 适合宽度渲染）
        QTimer.singleShot(0, lambda: self._goto_page(0))
        self._update_ui_state()

    def _stop_workers(self):
        for w in (self._thumb_worker, self._search_worker):
            if w and w.isRunning():
                w.cancel()
                w.wait(2000)
        self._thumb_worker = None
        self._search_worker = None

    def stop_workers(self):
        """应用退出前调用：停止后台线程，避免线程运行中销毁导致崩溃。"""
        self._stop_workers()

    def _on_thumbs(self, batch: list):
        from PySide6.QtGui import QIcon
        for page_index, data in batch:
            item = self.thumb_list.item(page_index)
            if item:
                pm = QPixmap()
                pm.loadFromData(data)
                item.setIcon(QIcon(pm))
        if batch:
            self.thumb_list.setIconSize(self.thumb_list.iconSize())

    # ---- 翻页 / 缩放 ----

    def _goto_page(self, index: int):
        if not self._doc:
            return
        total = self._doc.page_count
        index = max(0, min(index, total - 1))
        self._page_index = index
        self.page_edit.setText(str(index + 1))
        self.thumb_list.blockSignals(True)
        self.thumb_list.setCurrentRow(index)
        self.thumb_list.blockSignals(False)
        if self._fit_width:
            self.canvas.zoom = self._fit_zoom()
        self.canvas.set_document(self._doc, index)
        self._refresh_highlights()
        self.scroll.verticalScrollBar().setValue(0)
        self._update_ui_state()

    def _on_page_input(self):
        try:
            self._goto_page(int(self.page_edit.text()) - 1)
        except ValueError:
            self.page_edit.setText(str(self._page_index + 1))

    def _on_thumb_row(self, row: int):
        if self._doc and 0 <= row < self._doc.page_count and row != self._page_index:
            self._goto_page(row)

    def _fit_zoom(self) -> float:
        if not self._doc:
            return 1.5
        page = self._doc.load_page(self._page_index)
        w = max(200, self.scroll.viewport().width() - 36)
        return w / page.rect.width

    def _fit_to_width(self):
        if self._doc:
            self.canvas.zoom = self._fit_zoom()
            self.canvas.render()
            self._update_zoom_label()

    def _toggle_fit(self, checked: bool):
        self._fit_width = checked
        if checked:
            self._fit_to_width()

    def _zoom_by(self, factor: float):
        if not self._doc:
            return
        self._fit_width = False
        self.fit_btn.blockSignals(True)
        self.fit_btn.setChecked(False)
        self.fit_btn.blockSignals(False)
        self.canvas.zoom = max(0.2, min(6.0, self.canvas.zoom * factor))
        self.canvas.render()
        self._update_zoom_label()

    def _update_zoom_label(self):
        self.zoom_label.setText(f"{round(self.canvas.zoom * 100)}%")

    def eventFilter(self, obj, event):
        if (obj is self.scroll.viewport()
                and event.type() == QEvent.Type.Resize
                and self._fit_width and self._doc):
            self._fit_to_width()
        return super().eventFilter(obj, event)

    # ---- 工具 / 标注 ----

    def _set_tool(self, key: str):
        self.canvas.tool = key
        for k, btn in self.tool_btns.items():
            btn.blockSignals(True)
            btn.setChecked(k == key)
            btn.blockSignals(False)
        self.canvas.setCursor(
            Qt.CursorShape.CrossCursor if key in ("pen", "eraser")
            else Qt.CursorShape.ArrowCursor)

    def _on_pen_style(self):
        self.canvas.pen_color = PEN_COLORS[self.color_combo.currentText()]
        self.canvas.pen_width = self.width_spin.value()

    def _on_annot_added(self, xref: int):
        self._undo_stack.append((self._page_index, xref))
        self._dirty = True
        self._update_ui_state()

    def _on_annot_deleted(self, xref: int):
        self._undo_stack = [(p, x) for p, x in self._undo_stack if x != xref]
        self._dirty = True
        self._update_ui_state()

    def _undo(self):
        if not self._doc:
            return
        while self._undo_stack:
            page_i, xref = self._undo_stack.pop()
            page = self._doc.load_page(page_i)
            for annot in page.annots():
                if annot.xref == xref:
                    page.delete_annot(annot)
                    self._dirty = True
                    if page_i == self._page_index:
                        self.canvas.render()
                    self._update_ui_state()
                    return

    # ---- 留言 ----

    def _place_note(self, x: float, y: float):
        if not self._doc:
            return
        dlg = NoteDialog(parent=self)
        if dlg.exec() and dlg.text():
            page = self._doc.load_page(self._page_index)
            annot = page.add_text_annot(fitz.Point(x, y), dlg.text())
            annot.set_info(title="阅读器", content=dlg.text())
            annot.update()
            self._undo_stack.append((self._page_index, annot.xref))
            self._dirty = True
            self.canvas.render()
            self._update_ui_state()

    def _edit_note(self, annot):
        old = annot.info.get("content", "")
        dlg = NoteDialog(text=old, deletable=True, parent=self)
        dlg.exec()
        if dlg.deleted:
            annot.parent.delete_annot(annot)
            self._undo_stack = [(p, x) for p, x in self._undo_stack
                                if x != annot.xref]
            self._dirty = True
            self.canvas.render()
        elif not dlg.deleted and dlg.text() and dlg.text() != old:
            annot.set_info(content=dlg.text())
            annot.update()
            self._dirty = True
            self.canvas.render()
        self._update_ui_state()

    # ---- 保存 ----

    def _save(self):
        if not self._doc:
            return
        if not self._dirty:
            InfoBar.info("无需保存", "没有未保存的修改", parent=self,
                         position=InfoBarPosition.TOP)
            return
        try:
            self._doc.saveIncr()
            self._dirty = False
            InfoBar.success("已保存", "修改已写回原文件",
                            parent=self, position=InfoBarPosition.TOP)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("保存失败", f"{e}；请改用「另存为」",
                          parent=self, position=InfoBarPosition.TOP, duration=6000)
        self._update_ui_state()

    def _save_as(self):
        if not self._doc:
            return
        stem = os.path.splitext(os.path.basename(self._pdf_path))[0]
        out, _ = QFileDialog.getSaveFileName(
            self, "另存为", f"{stem}_标注.pdf", "PDF 文件 (*.pdf)")
        if not out:
            return
        try:
            if os.path.abspath(out) == os.path.abspath(self._pdf_path):
                self._doc.saveIncr()
                self._dirty = False
            else:
                self._doc.save(out, garbage=4, deflate=True)
                # 原文件仍未包含这些修改，保持未保存标记
            InfoBar.success("已导出", out, parent=self,
                            position=InfoBarPosition.TOP, duration=5000)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("导出失败", str(e), parent=self,
                          position=InfoBarPosition.TOP)
        self._update_ui_state()

    def confirm_discard(self) -> bool:
        """有未保存修改时询问；返回是否可以继续（关闭/换文件）。"""
        if not self._dirty:
            return True
        box = MessageBox("未保存的修改",
                         "当前 PDF 有未保存的标注或留言，继续操作将丢失这些修改。",
                         self)
        box.yesButton.setText("保存")
        box.cancelButton.setText("放弃修改")
        if box.exec():
            self._save()
            return not self._dirty
        return True

    # ---- 查找 ----

    def _toggle_search_panel(self, checked: bool):
        self.search_panel.setVisible(checked)
        if checked:
            self.search_edit.setFocus()

    def _start_search(self):
        if not self._doc or not self._pdf_path:
            return
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
            self.search_status.setText("正在取消…")
            return
        needle = self.search_edit.text().strip()
        if not needle:
            return
        self._hits = []
        self._current_hit = -1
        self.result_list.clear()
        self.canvas.set_highlights([])
        self.search_progress.setVisible(True)
        self.search_progress.setRange(0, 0)
        use_ocr = self.ocr_check.isChecked() and self.ocr_check.isEnabled()
        self.search_status.setText("查找中…（再次回车可取消）" if use_ocr else "查找中…")
        self._search_worker = SearchWorker(
            self._pdf_path, needle, use_ocr=use_ocr, parent=self)
        self._search_worker.progress.connect(self._on_search_progress)
        self._search_worker.finished_ok.connect(self._on_search_done)
        self._search_worker.failed.connect(self._on_search_failed)
        self._search_worker.start()

    def _on_search_progress(self, done: int, total: int):
        if self.search_progress.maximum() != total:
            self.search_progress.setRange(0, total)
        self.search_progress.setValue(done)
        self.search_status.setText(f"查找中… {done}/{total} 页")

    def _on_search_done(self, hits: list):
        self.search_progress.setVisible(False)
        self._hits = hits
        for i, hit in enumerate(hits):
            item = QListWidgetItem(f"第 {hit['page'] + 1} 页 · {hit['snippet']}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setToolTip(hit["snippet"])
            self.result_list.addItem(item)
        if hits:
            self.search_status.setText(f"共 {len(hits)} 条结果")
            self.result_list.setCurrentRow(0)
            self._show_hit(0)
        else:
            self.search_status.setText("未找到匹配内容"
                                       + ("（扫描页可勾选 OCR 后重试）"
                                          if not self.ocr_check.isChecked() else ""))

    def _on_search_failed(self, msg: str):
        self.search_progress.setVisible(False)
        self.search_status.setText(f"查找失败：{msg}")
        InfoBar.error("查找失败", msg, parent=self,
                      position=InfoBarPosition.TOP)

    def _show_hit(self, index: int):
        if not (0 <= index < len(self._hits)):
            return
        self._current_hit = index
        self.result_list.blockSignals(True)
        self.result_list.setCurrentRow(index)
        self.result_list.blockSignals(False)
        hit = self._hits[index]
        if hit["page"] != self._page_index:
            self._goto_page(hit["page"])
        else:
            self._refresh_highlights()
        # 滚动到当前高亮附近
        r = hit["rects"][0]
        bar = self.scroll.verticalScrollBar()
        bar.setValue(max(0, int(r.y0 * self.canvas.zoom
                                - self.scroll.viewport().height() / 3)))

    def _step_hit(self, delta: int):
        if self._hits:
            self._show_hit((self._current_hit + delta) % len(self._hits))

    def _on_result_row(self, row: int):
        item = self.result_list.item(row)
        if item is not None:
            self._show_hit(item.data(Qt.ItemDataRole.UserRole))

    def _refresh_highlights(self):
        items = []
        for idx, hit in enumerate(self._hits):
            if hit["page"] == self._page_index:
                for r in hit["rects"]:
                    items.append((r, idx == self._current_hit))
        self.canvas.set_highlights(items)

    # ---- 状态 ----

    def _update_ui_state(self):
        has_doc = self._doc is not None
        total = self._doc.page_count if has_doc else 0
        self.prev_btn.setEnabled(has_doc and self._page_index > 0)
        self.next_btn.setEnabled(has_doc and self._page_index < total - 1)
        self.page_edit.setEnabled(has_doc)
        for btn in self.tool_btns.values():
            btn.setEnabled(has_doc)
        self.undo_btn.setEnabled(bool(self._undo_stack))
        self.save_btn.setEnabled(has_doc)
        self.save_as_btn.setEnabled(has_doc)
        self.search_btn.setEnabled(has_doc)
        self.zoom_in_btn.setEnabled(has_doc)
        self.zoom_out_btn.setEnabled(has_doc)
        self.fit_btn.setEnabled(has_doc)
        if has_doc:
            self._update_zoom_label()
