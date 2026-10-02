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

RE_CHINESE_HEADING = re.compile(r"^第\s*[0-9０-９一二三四五六七八九十百千零]+\s*([章节篇部卷回讲])")
CHAPTER_LEVEL = {"篇": 1, "部": 1, "卷": 1, "章": 1, "回": 1, "讲": 1, "节": 2}
RE_EN_HEADING = re.compile(
    r"^(chapter|part|section|appendix)\s*"
    r"([0-9]+(?:\s*\.\s*[0-9]+){0,4}|[IVXLC]+)\b",
    re.I,
)
RE_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+){0,5})\s*[、．.:：]?\s+\S")
RE_NUM_BARE = re.compile(r"^(\d+(?:\.\d+)+)\s*$")  # 单独成行的编号，如 "1.2"
RE_PAGENUM = re.compile(r"^[0-9０-９]{1,4}$|^[ivxlcdmIVXLCDM]{1,4}$")
RE_WORD = re.compile(r"[A-Za-z]{3,}|[一-鿿]{2,}")
RE_HEADING_START = re.compile(r"^([A-Z]|[^ -~])")  # 大写字母或非 ASCII（汉字等）开头
RE_MATH_RELATION = re.compile(r"(?:=|≠|≈|≤|≥|<|>)")
RE_MATH_SYMBOL = re.compile(r"[=+*/^<>≤≥≠≈∫∑√{}\[\]|\\]")


def _mostly_words(text: str) -> bool:
    """判断文本是否像自然语言标题，而不是变量、缩写或公式碎片。"""
    letters = sum(1 for c in text if c.isalpha() or "一" <= c <= "鿿")
    if letters < len(text) * 0.5 or not RE_WORD.search(text):
        return False
    if re.search(r"[一-鿿]{2,}", text):
        return True
    words = re.findall(r"[A-Za-z]{2,}", text)
    natural = [
        word for word in words
        if (word.islower() or word.istitle() or (word.isupper() and len(word) >= 5))
        and re.search(r"[AEIOUYaeiouy]", word)
    ]
    # 单词标题需要足够长；多词标题则允许 of / and 等短词。
    return any(len(word) >= 4 for word in natural) or len(natural) >= 2


def _looks_like_formula(text: str) -> bool:
    """识别不应进入书签的公式/变量行。编号标题仍会由编号规则单独判断。"""
    if RE_CHINESE_HEADING.match(text) or RE_EN_HEADING.match(text):
        return False
    compact = re.sub(r"\s+", "", text)
    if RE_MATH_RELATION.search(text):
        return True
    symbols = len(RE_MATH_SYMBOL.findall(text))
    if symbols >= 2 or (symbols and len(compact) <= 18):
        return True
    # 多个短变量（VTH、RoN、CLK2 等）通常来自电路图或公式，而非自然语言标题。
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:\([^)]*\))?", text)
    if tokens and all(len(token) <= 8 for token in tokens):
        variable_like = sum(
            1 for token in tokens
            if any(c.isdigit() for c in token)
            or (sum(c.isupper() for c in token) >= 2 and not token.isupper())
            or token.isupper()
        )
        if variable_like >= max(1, len(tokens) - 1) and len(tokens) <= 5:
            return True
    return False


def _merge_numbered_row_fragments(raw: list[dict]) -> list[dict]:
    """合并 PDF 把同一视觉行拆开的 ``1.2``、标题词组。

    只从点号编号开始、只向右合并同字号且间距很小的片段，并跳过页眉页脚区域，
    避免把双栏正文或页眉中的 ``Section 1.2`` 拼进正文标题。
    """
    consumed: set[int] = set()
    replacements: dict[int, dict] = {}
    by_page: dict[int, list[int]] = {}
    for idx, item in enumerate(raw):
        by_page.setdefault(item["page"], []).append(idx)

    for idx, item in enumerate(raw):
        if idx in consumed:
            continue
        match = RE_NUM_HEADING.match(item["text"]) or RE_NUM_BARE.match(item["text"])
        bbox = item.get("bbox")
        page_height = item.get("page_height", 0)
        if not match or not bbox or not page_height:
            continue
        if bbox[1] < page_height * 0.06 or bbox[3] > page_height * 0.94:
            continue
        cy = (bbox[1] + bbox[3]) / 2
        candidates = []
        for other_idx in by_page[item["page"]]:
            if other_idx == idx or other_idx in consumed:
                continue
            other = raw[other_idx]
            obox = other.get("bbox")
            if not obox or obox[0] < bbox[2] - 1:
                continue
            ocy = (obox[1] + obox[3]) / 2
            if abs(ocy - cy) <= max(2.0, (bbox[3] - bbox[1]) * 0.2) \
                    and abs(other["size"] - item["size"]) <= max(1.0, item["size"] * 0.12):
                candidates.append((obox[0], other_idx))
        candidates.sort()

        parts = [(bbox[0], item["text"], idx)]
        right = bbox[2]
        for x0, other_idx in candidates:
            other = raw[other_idx]
            obox = other["bbox"]
            if x0 - right > max(40.0, item["size"] * 4.0):
                break
            parts.append((x0, other["text"], other_idx))
            right = max(right, obox[2])
        if len(parts) == 1:
            continue
        merged = dict(item)
        merged["text"] = " ".join(part[1].strip() for part in parts if part[1].strip())
        merged["bbox"] = (bbox[0], bbox[1], right, bbox[3])
        replacements[idx] = merged
        consumed.update(part[2] for part in parts[1:])

    return [replacements.get(idx, item) for idx, item in enumerate(raw) if idx not in consumed]


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
                    raw.append({
                        "page": i, "text": text, "size": rsize, "bold": bold,
                        "bbox": tuple(line.get("bbox", ())),
                        "page_height": page.rect.height,
                        "order": len(raw),
                    })
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
                    rect = ol.get("rect")
                    raw.append({
                        "page": i, "text": text, "size": rsize, "bold": False,
                        "bbox": tuple(rect) if rect is not None else (),
                        "page_height": page.rect.height,
                        "order": len(raw),
                    })
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

    # 很多排版型 PDF 会把 ``1.2 标题文字`` 拆成同一基线上的多个文本行。
    # 在套用编号规则前先按几何位置还原，否则裸编号会因“不含单词”而被漏掉。
    raw = _merge_numbered_row_fragments(raw)

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
            keyword = m.group(1).lower()
            number = re.sub(r"\s+", "", m.group(2))
            comps = [int(c) for c in number.split(".")] if number[0].isdigit() else None
            if comps and (comps[0] < 1 or any(c > 99 for c in comps)):
                return None
            level = max(2, len(comps)) if keyword == "section" and comps else (
                2 if keyword == "section" else 1
            )
            return min(level, max_level), "strong", comps
        m = RE_NUM_HEADING.match(text) or RE_NUM_BARE.match(text)
        if m:
            comps = [int(c) for c in m.group(1).split(".")]
            if comps[0] < 1 or len(comps) > 5 or any(c > 99 for c in comps):
                return None  # 小数（3.14）、年份（2024）等
            kind = "dotted" if "." in m.group(1) else "plain"
            return min(len(comps), max_level), kind, comps
        return None

    # 明显大于本页正文的字号 → 层级（字号越大层级越高）
    # 标题通常是短行、以词开头，借此过滤 OCR 文本层里的大号公式碎片
    font_sizes = sorted(
        {r["size"] for r in raw
         if use_font and len(r["text"]) <= 60 and _mostly_words(r["text"])
         and not _looks_like_formula(r["text"])
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
        if _looks_like_formula(text):
            continue
        body = body_of(r["page"])
        numbered = numbering_level(text) if use_num else None
        nlvl = numbered[0] if numbered else None
        level = None
        num_comps = None
        if numbered is not None and len(text) <= 80:
            kind = numbered[1]
            if kind == "strong" and _mostly_words(text):
                level = nlvl
            elif kind == "dotted" and _mostly_words(text) \
                    and (r["bold"] or r["size"] >= body * 0.72):
                # 带点编号（如 "1.2 xxx"），序列一致性本身已有较强佐证，因此允许
                # 章节标题明显小于正文；老旧教材常用 8pt 小节名搭配 10pt 正文。
                # 需以词为主体，过滤 "1.2 V=IR" 之类的公式行
                level = nlvl
                num_comps = numbered[2][:nlvl]
            elif kind == "plain" and _mostly_words(text) \
                    and (r["bold"] or r["size"] >= body * 1.08):
                # 单整数编号（如 "1 xxx"）最易误伤习题号、年份，需粗体或明显大字号佐证
                level = nlvl
                num_comps = numbered[2][:nlvl]
        if level is None and use_font and len(text) <= 60 \
                and _mostly_words(text) and RE_HEADING_START.match(text) \
                and r["size"] in size_level and r["size"] >= body * 1.12:
            level = size_level[r["size"]]
        if level is None:
            continue
        # 反复出现的页眉页脚文本，除非明显是标题（带编号或字号很大）
        if text in repeated and not (nlvl is not None or r["size"] >= body * 1.3):
            continue
        entry = {
            "level": level, "title": text, "page": r["page"],
            "_bbox": r.get("bbox"), "_order": r.get("order", 0),
        }
        if num_comps:
            # 编号类标题记录上下文信息，供序列一致性过滤
            entry.update(num=num_comps, bold=r["bold"], size=r["size"])
        headings.append(entry)

    headings = _filter_numbering_by_sequence(headings)

    # 只合并原文中真正相邻、版面上也紧邻的标题行。旧逻辑会把同页相距很远的
    # 公式和标题拼在一起，形成“公式 + 标题”的假书签。
    merged: list[dict] = []
    for h in headings:
        prev = merged[-1] if merged else None
        pbox = prev.get("_bbox") if prev else None
        hbox = h.get("_bbox")
        close_in_source = prev is not None and h["_order"] <= prev["_order"] + 1
        close_on_page = bool(
            pbox and hbox
            and -2 <= hbox[1] - pbox[3] <= max(30, (pbox[3] - pbox[1]) * 1.8)
            and abs(hbox[0] - pbox[0]) <= 90
        )
        if (prev and prev["page"] == h["page"] and prev["level"] == h["level"]
                and close_in_source and close_on_page
                and len(prev["title"]) + len(h["title"]) + 1 <= 100):
            merged[-1]["title"] += " " + h["title"]
            merged[-1]["_bbox"] = (
                min(pbox[0], hbox[0]), min(pbox[1], hbox[1]),
                max(pbox[2], hbox[2]), max(pbox[3], hbox[3]),
            )
            merged[-1]["_order"] = h["_order"]
        else:
            merged.append(dict(h))

    for item in merged:
        item.pop("_bbox", None)
        item.pop("_order", None)
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
