"""PyMuPDF 核心逻辑：打开 PDF、解析页码范围、渲染图片、节选导出。"""
from __future__ import annotations

import io
import os
import re
import zipfile

import fitz  # PyMuPDF

IMAGE_FORMATS = ["PNG", "JPG", "WEBP", "BMP", "TIFF"]
EXT_MAP = {"PNG": ".png", "JPG": ".jpg", "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff"}


class PageRangeError(ValueError):
    pass


def compress_pages(pages: list[int]) -> str:
    """把页码列表压缩为区间形式：[1,2,3,5,10,11] -> "1-3, 5, 10-11"。"""
    if not pages:
        return ""
    pages = sorted(set(pages))
    parts: list[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = p
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(parts)


def parse_page_range(text: str, total: int) -> list[int]:
    """解析 "1-3,5" 形式的页码（1 起始），返回 0 起始的升序去重列表。"""
    text = (text or "").strip()
    if not text:
        return list(range(total))
    pages: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not m:
            raise PageRangeError(f"无法识别的页码片段：「{part}」，正确格式如 1-3,5")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a > b:
            a, b = b, a
        if a < 1 or b > total:
            raise PageRangeError(f"页码 {a}-{b} 超出范围（共 {total} 页）")
        pages.update(range(a - 1, b))
    if not pages:
        raise PageRangeError("未指定任何有效页码")
    return sorted(pages)


def open_pdf(path: str) -> fitz.Document:
    return fitz.open(path)


def render_page(doc: fitz.Document, page_index: int, dpi: int) -> fitz.Pixmap:
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix


def pixmap_to_bytes(pix: fitz.Pixmap, fmt: str, jpg_quality: int = 90) -> bytes:
    fmt_upper = fmt.upper()
    if fmt_upper == "JPG":
        return pix.tobytes("jpg", jpg_quality=jpg_quality)
    return pix.tobytes(fmt_upper.lower())


def export_pages_as_images(
    pdf_path: str,
    pages: list[int],
    out_dir: str,
    fmt: str = "PNG",
    dpi: int = 150,
    jpg_quality: int = 90,
    make_zip: bool = False,
    zip_name: str | None = None,
    progress_cb=None,
    cancel_check=None,
) -> list[str]:
    """把指定页渲染为图片写入 out_dir，返回生成的文件路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    ext = EXT_MAP[fmt.upper()]
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    written: list[str] = []
    doc = fitz.open(pdf_path)
    try:
        for i, p in enumerate(pages):
            if cancel_check and cancel_check():
                break
            pix = render_page(doc, p, dpi)
            data = pixmap_to_bytes(pix, fmt, jpg_quality)
            pix = None  # 尽早释放
            out_path = os.path.join(out_dir, f"{stem}_第{p + 1}页{ext}")
            with open(out_path, "wb") as f:
                f.write(data)
            written.append(out_path)
            if progress_cb:
                progress_cb(i + 1, len(pages))
    finally:
        doc.close()

    if make_zip and written:
        zip_path = os.path.join(out_dir, zip_name or f"{stem}_图片.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in written:
                zf.write(p, arcname=os.path.basename(p))
        written.append(zip_path)
    return written


def extract_pages_to_pdf(
    pdf_path: str,
    pages: list[int],
    out_path: str,
) -> str:
    """把指定页节选为新 PDF（保留原始矢量内容，不重渲染）。"""
    src = fitz.open(pdf_path)
    try:
        dst = fitz.open()
        dst.insert_pdf(src, from_page=min(pages), to_page=max(pages))
        # insert_pdf 是连续区间；若页不连续，改用 select 保持精确
        if pages != list(range(min(pages), max(pages) + 1)):
            dst.close()
            dst = fitz.open()
            for p in pages:
                dst.insert_pdf(src, from_page=p, to_page=p)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        dst.save(out_path, garbage=4, deflate=True)
        dst.close()
    finally:
        src.close()
    return out_path


# ---- 书签自动生成 ----

RE_CHINESE_HEADING = re.compile(r"^第\s*[0-9０-９一二三四五六七八九十百千零]+\s*([章节篇部卷回])")
CHAPTER_LEVEL = {"篇": 1, "部": 1, "卷": 1, "章": 1, "回": 1, "节": 2}
RE_EN_HEADING = re.compile(r"^(chapter|part|section|appendix)\s+[\dIVXLC]+", re.I)
RE_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+){0,5})\s*[、．.:：]?\s+\S")
RE_NUM_BARE = re.compile(r"^(\d+(?:\.\d+)+)\s*$")  # 单独成行的编号，如 "1.2"
RE_PAGENUM = re.compile(r"^[0-9０-９]{1,4}$|^[ivxlcdmIVXLCDM]{1,4}$")
RE_WORD = re.compile(r"[A-Za-z]{3,}|[一-鿿]{2,}")
RE_HEADING_START = re.compile(r"^([A-Z]|[^ -~])")  # 大写字母或非 ASCII（汉字等）开头


def normalize_toc(toc: list[dict]) -> list[dict]:
    """规整层级：首项必须为 1，且每层最多比上一层深一级（set_toc 的要求）。"""
    out: list[dict] = []
    prev = 0
    for item in toc:
        level = max(1, item["level"])
        if not out:
            level = 1
        elif level > prev + 1:
            level = prev + 1
        out.append({**item, "level": level})
        prev = level
    return out


def detect_headings(
    pdf_path: str,
    mode: str = "both",       # both / numbering / font
    max_level: int = 3,
    use_ocr: bool = False,    # 页面无文字层时调用 OCR 识别文字（扫描件）
    progress_cb=None,
    cancel_check=None,
) -> list[dict]:
    """根据字号、粗体和章节编号模式识别标题，返回 [{'level','title','page'(0 起始)}]。

    编号类标题（1.2 / 1 xxx 等）需通过上下文一致性过滤：同级同前缀的编号须形成
    递增序列才保留，以此剔除孤立的小数（3.14）、公式编号和正文中的交叉引用。
    OCR 路径默认不识别用户添加的批注/留言墨迹。
    """
    if use_ocr:
        from . import ocr_service
        ocr_service.get_engine()  # 提前加载模型，依赖缺失时尽早报错
    doc = fitz.open(pdf_path)
    total = doc.page_count
    raw: list[dict] = []
    size_counter: dict[float, int] = {}
    page_size_counter: list[dict[float, int]] = []
    try:
        for i in range(total):
            if cancel_check and cancel_check():
                break
            page = doc.load_page(i)
            page_counter: dict[float, int] = {}
            had_text = False
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans") or []
                    text = "".join(s.get("text", "") for s in spans).strip()
                    if len(text) < 2 or len(text) > 120:
                        continue
                    had_text = True
                    # 行字号取字符数最多的 span 的字号，避免行内个别大字符（公式符号等）拉高整行
                    span_chars: dict[float, int] = {}
                    for s in spans:
                        st = s.get("text", "")
                        if st.strip():
                            rs = round(s.get("size", 0.0) * 2) / 2
                            span_chars[rs] = span_chars.get(rs, 0) + len(st)
                    if not span_chars:
                        continue
                    rsize = max(span_chars, key=span_chars.get)
                    bold = any(
                        (s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower()
                        for s in spans
                    )
                    raw.append({"page": i, "text": text, "size": rsize, "bold": bold})
                    size_counter[rsize] = size_counter.get(rsize, 0) + len(text)
                    # 正文字号按长文本行统计，避免标题行干扰
                    if len(text) >= 30:
                        page_counter[rsize] = page_counter.get(rsize, 0) + len(text)
            if use_ocr and not had_text:
                # 扫描页：OCR 识别文字，字号用文本框高度近似；默认不识别批注/留言墨迹
                from . import ocr_service
                for ol in ocr_service.ocr_page(doc, page):
                    text = ol["text"]
                    if len(text) < 2 or len(text) > 120:
                        continue
                    rsize = round(ol["size"] * 2) / 2
                    raw.append({"page": i, "text": text, "size": rsize, "bold": False})
                    size_counter[rsize] = size_counter.get(rsize, 0) + len(text)
                    if len(text) >= 30:
                        page_counter[rsize] = page_counter.get(rsize, 0) + len(text)
            page_size_counter.append(page_counter)
            if progress_cb:
                progress_cb(i + 1, total)
    finally:
        doc.close()

    if not raw:
        return []
    global_body = max(size_counter, key=size_counter.get)

    def body_threshold(counter: dict[float, int]) -> float:
        """正文的字号上限：长文本行中，字符数达到众数 25% 的字号都视为正文。"""
        if not counter:
            return global_body
        mx = max(counter.values())
        return max(s for s, c in counter.items() if c >= mx * 0.25)

    # 每页单独估算正文字号（混合来源的 PDF 各页正文大小可能不同）
    page_bodies: dict[int, float] = {}
    for i, counter in enumerate(page_size_counter):
        page_bodies[i] = body_threshold(counter)

    def body_of(page: int) -> float:
        return page_bodies.get(page, global_body)

    # 页眉页脚：同一短文本出现在大量页面上
    freq: dict[str, set] = {}
    for r in raw:
        if len(r["text"]) <= 60:
            freq.setdefault(r["text"], set()).add(r["page"])
    repeated = {t for t, pages in freq.items() if len(pages) >= max(4, total * 0.15)}

    use_font = mode in ("both", "font")
    use_num = mode in ("both", "numbering")

    def numbering_level(text: str) -> tuple[int, str, list[int] | None] | None:
        """返回 (层级, 类型, 编号各段数值)：strong=章节关键词，dotted=带点编号，plain=单整数编号。

        编号首段须 ≥1、每段 ≤99、最多 5 段，否则视为小数/年份等非章节编号。
        """
        m = RE_CHINESE_HEADING.match(text)
        if m:
            return min(CHAPTER_LEVEL.get(m.group(1), 1), max_level), "strong", None
        m = RE_EN_HEADING.match(text)
        if m:
            return (2 if m.group(1).lower() == "section" else 1), "strong", None
        m = RE_NUM_HEADING.match(text) or RE_NUM_BARE.match(text)
        if m:
            comps = [int(c) for c in m.group(1).split(".")]
            if comps[0] < 1 or len(comps) > 5 or any(c > 99 for c in comps):
                return None  # 小数（3.14）、年份（2024）等
            kind = "dotted" if "." in m.group(1) else "plain"
            return min(len(comps), max_level), kind, comps
        return None

    def mostly_words(text: str) -> bool:
        """字母/汉字占比过半且含完整词才算文本行，过滤公式行（大号积分号等会拉高行字号）。"""
        alnum = sum(1 for c in text if c.isalpha() or "一" <= c <= "鿿")
        return alnum >= len(text) * 0.5 and bool(RE_WORD.search(text))

    # 明显大于本页正文的字号 → 层级（字号越大层级越高）
    # 标题通常是短行、以词开头，借此过滤 OCR 文本层里的大号公式碎片
    font_sizes = sorted(
        {r["size"] for r in raw
         if use_font and len(r["text"]) <= 60 and mostly_words(r["text"])
         and RE_HEADING_START.match(r["text"])
         and r["size"] >= body_of(r["page"]) * 1.12},
        reverse=True,
    )
    size_level = {s: min(idx + 1, max_level) for idx, s in enumerate(font_sizes)}

    headings: list[dict] = []
    for r in raw:
        text = r["text"]
        if RE_PAGENUM.match(text):
            continue
        body = body_of(r["page"])
        numbered = numbering_level(text) if use_num else None
        nlvl = numbered[0] if numbered else None
        level = None
        num_comps = None
        if numbered is not None and len(text) <= 80:
            kind = numbered[1]
            if kind == "strong" and mostly_words(text):
                level = nlvl
            elif kind == "dotted" and mostly_words(text) \
                    and (r["bold"] or r["size"] >= body * 0.9):
                # 带点编号（如 "1.2 xxx" 或单独成行的 "1.2"），容忍 OCR 缩放导致的轻微偏小；
                # 需以词为主体，过滤 "1.2 V=IR" 之类的公式行
                level = nlvl
                num_comps = numbered[2][:nlvl]
            elif kind == "plain" and mostly_words(text) \
                    and (r["bold"] or r["size"] >= body * 1.08):
                # 单整数编号（如 "1 xxx"）最易误伤习题号、年份，需粗体或明显大字号佐证
                level = nlvl
                num_comps = numbered[2][:nlvl]
        if level is None and use_font and len(text) <= 60 \
                and mostly_words(text) and RE_HEADING_START.match(text) \
                and r["size"] in size_level and r["size"] >= body * 1.12:
            level = size_level[r["size"]]
        if level is None:
            continue
        # 反复出现的页眉页脚文本，除非明显是标题（带编号或字号很大）
        if text in repeated and not (nlvl is not None or r["size"] >= body * 1.3):
            continue
        entry = {"level": level, "title": text, "page": r["page"]}
        if num_comps:
            # 编号类标题记录上下文信息，供序列一致性过滤
            entry.update(num=num_comps, bold=r["bold"], size=r["size"])
        headings.append(entry)

    headings = _filter_numbering_by_sequence(headings)

    # 同页连续的同级标题行合并为一个（多行排版的标题会被拆成多条）
    merged: list[dict] = []
    for h in headings:
        if (merged and merged[-1]["page"] == h["page"]
                and merged[-1]["level"] == h["level"]
                and len(merged[-1]["title"]) + len(h["title"]) + 1 <= 100):
            merged[-1]["title"] += " " + h["title"]
        else:
            merged.append(dict(h))

    return normalize_toc(merged)


def _filter_numbering_by_sequence(headings: list[dict]) -> list[dict]:
    """编号类标题的上下文一致性过滤：同一组编号（同级、同前缀）必须按页面先后
    形成递增序列（步长 ≤10）才保留；孤立编号（小数、公式编号、交叉引用等）剔除。

    重复编号（正文中的交叉引用，如 "3.2 节所述"）只保留最像标题的一处
    （优先粗体、再大字号、再靠前者）。
    """
    groups: dict[tuple, list[int]] = {}
    for idx, h in enumerate(headings):
        comps = h.get("num")
        if comps:
            key = (h["level"], tuple(comps[:-1]))
            groups.setdefault(key, []).append(idx)
    if not groups:
        for h in headings:
            h.pop("num", None)
            h.pop("bold", None)
            h.pop("size", None)
        return headings

    drop: set[int] = set()
    for key, idxs in groups.items():
        vals = {i: headings[i]["num"][-1] for i in idxs}
        # 在首次出现的编号序列上找递增段（段长 ≥2 才算有上下文佐证）
        supported_vals: set[int] = set()
        run: list[int] = []
        prev: int | None = None
        seen: set[int] = set()
        for i in idxs:
            v = vals[i]
            if v in seen:
                continue  # 重复编号不参与序列构建
            seen.add(v)
            if prev is None or (v > prev and v - prev <= 10):
                run.append(v)
            else:
                if len(run) >= 2:
                    supported_vals.update(run)
                run = [v]
            prev = v
        if len(run) >= 2:
            supported_vals.update(run)
        # 每个被支持的编号只留最像标题的一处
        best: dict[int, int] = {}
        for i in idxs:
            v = vals[i]
            if v not in supported_vals:
                drop.add(i)
                continue
            h = headings[i]
            if v not in best:
                best[v] = i
                continue
            b = headings[best[v]]
            if (h["bold"], h["size"]) > (b["bold"], b["size"]):
                drop.add(best[v])
                best[v] = i
            else:
                drop.add(i)

    out = []
    for i, h in enumerate(headings):
        if i in drop:
            continue
        h.pop("num", None)
        h.pop("bold", None)
        h.pop("size", None)
        out.append(h)
    return out


def section_pages(toc: list[dict], index: int, total_pages: int) -> list[int]:
    """目录第 index 条覆盖的页码（0 起始）：从本条起，到下一个同级或更高级条目之前。"""
    start = toc[index]["page"]
    level = toc[index]["level"]
    end = total_pages - 1
    for item in toc[index + 1:]:
        if item["level"] <= level:
            end = item["page"] - 1
            break
    end = max(start, min(end, total_pages - 1))
    return list(range(start, end + 1))


def write_bookmarks(pdf_path: str, toc: list[dict], out_path: str) -> str:
    """把书签写入 PDF 并另存（会替换原有书签）。"""
    doc = fitz.open(pdf_path)
    try:
        doc.set_toc([[item["level"], item["title"], item["page"] + 1] for item in toc])
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        doc.save(out_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return out_path


# ---- 图片转 PDF ----

PAGE_SIZES = {"A4": (595.28, 841.89), "A5": (419.53, 595.28), "Letter": (612.0, 792.0)}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def images_to_pdf(
    image_paths: list[str],
    out_path: str,
    page_size: tuple[float, float] | None = None,  # None = 原始尺寸（1px = 1pt）
    margin_pt: float = 0,
    progress_cb=None,
    cancel_check=None,
) -> str:
    """把多张图片合成为一个 PDF。指定页面大小时图片等比缩放居中，横向图片自动用横版。"""
    doc = fitz.open()
    try:
        for i, path in enumerate(image_paths):
            if cancel_check and cancel_check():
                break
            pix = fitz.Pixmap(path)
            if pix.alpha or (pix.colorspace and pix.colorspace.n > 3):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if page_size is None:
                pw, ph = float(pix.width), float(pix.height)
            else:
                pw, ph = page_size
                if pix.width > pix.height:
                    pw, ph = ph, pw  # 横向图片用横版
            page = doc.new_page(width=pw, height=ph)
            area = fitz.Rect(margin_pt, margin_pt, pw - margin_pt, ph - margin_pt)
            page.insert_image(area, pixmap=pix, keep_proportion=True)
            pix = None
            if progress_cb:
                progress_cb(i + 1, len(image_paths))
        if doc.page_count == 0:
            raise ValueError("没有可导出的图片")
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        doc.save(out_path, garbage=4, deflate=True)
    finally:
        doc.close()
    return out_path


def thumbnail_bytes(pdf_path: str, page_index: int, width: int = 140) -> bytes:
    """生成单页缩略图（PNG 字节）。"""
    doc = fitz.open(pdf_path)
    try:
        return thumbnail_bytes_from_doc(doc, page_index, width)
    finally:
        doc.close()


def thumbnail_bytes_from_doc(doc: fitz.Document, page_index: int, width: int = 140) -> bytes:
    """在已打开的文档上生成单页缩略图（供批量调用，避免反复开关文件）。"""
    page = doc.load_page(page_index)
    zoom = width / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")
