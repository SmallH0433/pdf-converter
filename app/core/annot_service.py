"""阅读器核心逻辑：全文查找（可选 OCR 识别扫描页）。"""
from __future__ import annotations

import fitz  # PyMuPDF


def _snippet(page: fitz.Page, rect: fitz.Rect) -> str:
    """取命中位置前后的一小段文字作为结果摘录。"""
    clip = fitz.Rect(rect.x0 - 80, rect.y0 - 4, rect.x1 + 80, rect.y1 + 4) & page.rect
    return " ".join(page.get_text("text", clip=clip).split())[:80]


def search_text(
    pdf_path: str,
    needle: str,
    use_ocr: bool = False,
    progress_cb=None,
    cancel_check=None,
) -> list[dict]:
    """在整个 PDF 中查找文本，返回 [{'page'(0 起始), 'rects', 'snippet'}]。

    use_ocr=True 时，无文字层的页面（扫描页）调用 RapidOCR 识别后按行匹配；
    大小写不敏感，匹配时忽略空白差异。不修改 PDF 文件本身。
    """
    needle = (needle or "").strip()
    if not needle:
        return []
    if use_ocr:
        from . import ocr_service
        ok, reason = ocr_service.ocr_available()
        if not ok:
            raise RuntimeError(reason)

    hits: list[dict] = []
    doc = fitz.open(pdf_path)
    try:
        total = doc.page_count
        low = needle.lower().replace(" ", "")
        for i in range(total):
            if cancel_check and cancel_check():
                break
            page = doc.load_page(i)
            rects = page.search_for(needle)  # 自带大小写不敏感、可跨行
            for r in rects:
                hits.append({"page": i, "rects": [r], "snippet": _snippet(page, r)})
            if not rects and use_ocr and not page.get_text().strip():
                from . import ocr_service
                for line in ocr_service.ocr_page(doc, page):
                    if low in line["text"].lower().replace(" ", ""):
                        hits.append({"page": i, "rects": [line["rect"]],
                                     "snippet": line["text"][:80]})
            if progress_cb:
                progress_cb(i + 1, total)
    finally:
        doc.close()
    return hits
