"""后台任务线程：避免导出时界面卡死。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from . import pdf_service


class ConvertImagesWorker(QThread):
    """PDF 指定页 → 图片。"""

    progress = Signal(int, int)          # 已完成, 总数
    finished_ok = Signal(list)           # 生成的文件路径
    failed = Signal(str)

    def __init__(self, pdf_path, pages, out_dir, fmt, dpi, jpg_quality, make_zip, parent=None):
        super().__init__(parent)
        self._args = (pdf_path, pages, out_dir, fmt, dpi, jpg_quality, make_zip)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        pdf_path, pages, out_dir, fmt, dpi, jpg_quality, make_zip = self._args

        def on_progress(done, total):
            self.progress.emit(done, total)
            self.msleep(1)  # 让出 GIL，避免高 DPI 渲染时主线程被饿死

        try:
            files = pdf_service.export_pages_as_images(
                pdf_path, pages, out_dir, fmt, dpi, jpg_quality, make_zip,
                progress_cb=on_progress,
                cancel_check=lambda: self._cancelled,
            )
            self.finished_ok.emit(files)
        except Exception as e:  # noqa: BLE001 - 透传给界面提示
            self.failed.emit(str(e))


class ExtractPdfWorker(QThread):
    """PDF 指定页 → 新 PDF。"""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, pdf_path, pages, out_path, parent=None):
        super().__init__(parent)
        self._args = (pdf_path, pages, out_path)

    def run(self):
        pdf_path, pages, out_path = self._args
        try:
            result = pdf_service.extract_pages_to_pdf(pdf_path, pages, out_path)
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DetectHeadingsWorker(QThread):
    """扫描 PDF 文本，识别标题候选；use_ocr 时对无文字层的页面先 OCR。"""

    progress = Signal(int, int)          # 已扫描页, 总页数
    finished_ok = Signal(list)           # [{'level','title','page'}, ...]
    failed = Signal(str)

    def __init__(self, pdf_path, mode, max_level, use_ocr=False, parent=None):
        super().__init__(parent)
        self._args = (pdf_path, mode, max_level, use_ocr)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        pdf_path, mode, max_level, use_ocr = self._args

        def on_progress(done, total):
            self.progress.emit(done, total)
            self.msleep(1)

        try:
            toc = pdf_service.detect_headings(
                pdf_path, mode, max_level, use_ocr=use_ocr,
                progress_cb=on_progress,
                cancel_check=lambda: self._cancelled,
            )
            self.finished_ok.emit(toc)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class OcrPdfWorker(QThread):
    """整个 PDF → OCR 文字层，另存新文件。"""

    progress = Signal(int, int)          # 已完成页, 总页数
    finished_ok = Signal(str)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, pdf_path, out_path, parent=None):
        super().__init__(parent)
        self._args = (pdf_path, out_path)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from . import ocr_service
        pdf_path, out_path = self._args

        def on_progress(done, total):
            self.progress.emit(done, total)
            self.msleep(1)

        try:
            result = ocr_service.ocr_pdf(
                pdf_path, out_path,
                progress_cb=on_progress,
                cancel_check=lambda: self._cancelled,
            )
            if result is None:
                self.cancelled.emit()
            else:
                self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class OcrInstallWorker(QThread):
    """一键安装 GPU 加速包（CUDA 运行库 / DirectML 运行库，可安装多个）。"""

    log = Signal(str)                    # pip 日志行
    finished_ok = Signal(str)            # 完成提示语
    failed = Signal(str)

    def __init__(self, kind, parent=None):  # kind: 'cuda' / 'directml'
        super().__init__(parent)
        self._kind = kind

    def run(self):
        from . import ocr_service
        try:
            msg = ocr_service.install_gpu(self._kind, log_cb=self.log.emit)
            self.finished_ok.emit(msg)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class WriteBookmarksWorker(QThread):
    """把书签写入 PDF 并另存。"""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, pdf_path, toc, out_path, parent=None):
        super().__init__(parent)
        self._args = (pdf_path, toc, out_path)

    def run(self):
        pdf_path, toc, out_path = self._args
        try:
            result = pdf_service.write_bookmarks(pdf_path, toc, out_path)
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ImagesToPdfWorker(QThread):
    """多张图片 → 单个 PDF。"""

    progress = Signal(int, int)          # 已完成, 总数
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, image_paths, out_path, page_size, margin_pt, parent=None):
        super().__init__(parent)
        self._args = (image_paths, out_path, page_size, margin_pt)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        image_paths, out_path, page_size, margin_pt = self._args

        def on_progress(done, total):
            self.progress.emit(done, total)
            self.msleep(1)

        try:
            result = pdf_service.images_to_pdf(
                image_paths, out_path, page_size, margin_pt,
                progress_cb=on_progress,
                cancel_check=lambda: self._cancelled,
            )
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ThumbnailWorker(QThread):
    """批量生成缩略图（按批发送，减轻主线程布局压力）。"""

    batch_ready = Signal(list)             # [(页码0起始, PNG字节), ...]
    finished_all = Signal()

    BATCH = 8

    def __init__(self, pdf_path, total_pages, width=140, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._total = total_pages
        self._width = width
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        import fitz
        doc = fitz.open(self._pdf_path)  # 全程只打开一次（1130 页文档差异巨大）
        batch: list = []
        try:
            for i in range(self._total):
                if self._cancelled:
                    break
                try:
                    data = pdf_service.thumbnail_bytes_from_doc(doc, i, self._width)
                    batch.append((i, data))
                except Exception:  # noqa: BLE001 - 单页失败不阻塞整体
                    continue
                if len(batch) >= self.BATCH:
                    self.batch_ready.emit(batch)
                    batch = []
                    self.msleep(1)  # 让出 GIL：PyMuPDF C 渲染持锁，否则主线程被饿死
        finally:
            doc.close()
        if batch and not self._cancelled:
            self.batch_ready.emit(batch)
        self.finished_all.emit()
