"""用内置 llama.cpp 引擎加载本地 GGUF 模型判断 PDF 标题候选，模型文件不随安装包发布。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
from pathlib import Path

import fitz

from . import pdf_service


MODEL_BATCH_SIZE = 24
# 思考类模型（如 Qwen3）的推理过程同样占用 max_output_tokens，
# 预算过低会导致推理耗尽配额、JSON 被截断为空，因此需要留足空间。
MAX_OUTPUT_TOKENS = 4096
RETRY_OUTPUT_TOKENS = 12288


def model_store_dir() -> Path:
    """源码运行存项目根目录；安装后存 exe 同级的可写目录。"""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    return base / "llm_models"


def lmstudio_models_dir() -> Path:
    settings = Path.home() / ".lmstudio" / "settings.json"
    try:
        configured = json.loads(settings.read_text(encoding="utf-8")).get("downloadsFolder")
        if configured:
            return Path(configured).expanduser()
    except (OSError, ValueError, TypeError):
        pass
    return Path.home() / ".lmstudio" / "models"


def list_local_models() -> list[Path]:
    """只列出已完成的主 GGUF，不显示下载中的分片和视觉投影文件。
    同一模型的副本、硬链接和符号链接只显示一次。"""
    found: dict[str, Path] = {}
    seen_inodes: set[tuple[int, int]] = set()
    seen_content: set[tuple[str, int]] = set()
    for root in (model_store_dir(), lmstudio_models_dir()):
        if not root.is_dir():
            continue
        for path in root.rglob("*.gguf"):
            if path.name.lower().startswith("mmproj-") or not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            inode = (stat.st_dev, stat.st_ino)
            content = (path.name.casefold(), stat.st_size)
            if inode in seen_inodes or content in seen_content:
                continue
            seen_inodes.add(inode)
            seen_content.add(content)
            found[str(path.resolve()).casefold()] = path
    return sorted(found.values(), key=lambda p: (p.stat().st_size, p.name.casefold()))


def _check_cancel(cancel_check) -> None:
    if cancel_check and cancel_check():
        raise RuntimeError("已取消本地模型书签识别")


def copy_model_to_project(source: str | Path, progress_cb=None, cancel_check=None) -> Path:
    source = Path(source).resolve()
    if source.suffix.lower() != ".gguf" or source.name.lower().startswith("mmproj-"):
        raise ValueError("请选择已下载完成的主模型 .gguf 文件（不要选择 mmproj 或 .part）")
    if not source.is_file():
        raise FileNotFoundError(f"模型文件不存在：{source}")
    with source.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("所选文件不是有效的 GGUF 模型")
    store = model_store_dir().resolve()
    if source.is_relative_to(store):
        return source
    model_id = hashlib.sha256(str(source).casefold().encode("utf-8")).hexdigest()[:12]
    target = store / model_id / source.name
    if target.is_file() and target.stat().st_size == source.stat().st_size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    size = source.stat().st_size
    if shutil.disk_usage(target.parent).free < size + 256 * 1024 * 1024:
        raise OSError("应用目录空间不足，无法复制模型；请释放空间或选择较小的模型")
    part = target.with_name(target.name + ".copying")
    copied = 0
    try:
        with source.open("rb") as src, part.open("wb") as dst:
            while chunk := src.read(8 * 1024 * 1024):
                _check_cancel(cancel_check)
                dst.write(chunk)
                copied += len(chunk)
                if progress_cb:
                    progress_cb(copied, size)
        if source.stat().st_size != copied:
            raise OSError("模型复制期间源文件发生变化，请重新选择")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return target






def _post_chat(body: dict, timeout: int = 600) -> dict:
    """发起对话请求；引擎加载/切换模型期间可能短暂返回 5xx，自动重试。"""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            return _json_request("/api/v1/chat", body, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in (500, 502, 503, 504) or attempt == 3:
                raise
            last_exc = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 3:
                raise
            last_exc = exc
        time.sleep(3 * (attempt + 1))
    raise last_exc  # pragma: no cover


def _json_request(path: str, body: dict | None = None, timeout: int = 30) -> dict:
    """内部仍沿用 LM-Studio 风格的路径与响应形状，实际由内置 llama.cpp 引擎处理。"""
    from . import llm_engine
    if path == "/api/v1/chat":
        return llm_engine.chat(body or {}, timeout=timeout)
    if path == "/api/v1/models":
        return llm_engine.models()
    raise ValueError(f"未知接口：{path}")


def _ensure_server() -> None:
    """内置引擎的健康检查由 ensure_running 负责；此处仅确认进程存活。"""
    from . import llm_engine
    if not llm_engine.is_running():
        raise RuntimeError("内置推理引擎未运行，请先加载模型")


# 只有数字、空格和点的碎片（"1 .2"、"13.1 5"），是 OCR 拆散的习题号或交叉引用，不是标题
RE_NUM_FRAGMENT = re.compile(r"^\d+(?:[\s.．]+\d*)*[.．]?$")
# 例题/习题题干：编号（允许 OCR 空格，如 "3. 3.1"、"1. 7"）后紧跟题干
RE_EXAMPLE_NUM = re.compile(r"^\d+(?:\s*[.．]\s*\d+){1,}")
RE_EXAMPLE_LEAD = re.compile(r"^(设|已知|求|证明|解|画|计|若|判|试|讨论|分析|用|给)")
# 定理/例题等中文标签加编号（"定理2（有界性）"、"例3.1"）
RE_CN_LABEL_NUM = re.compile(r"^[【\[]?(定理|推论|引理|例)\s*\d")
# 图表说明（"图3.1 ..."、"Fig. 4 ..."）永远不是书签标题
RE_FIGURE_CAPTION = pdf_service.RE_FIGURE_CAPTION
# 中文序号小节标题（"一、实验设计目标"），全书反复出现也是真实标题
RE_CN_ORDINAL_HEADING = pdf_service.RE_CN_ORDINAL_HEADING
# 条目后跟页码（点线/省略号引导），是漏网目录/索引条目的特征
RE_PAGE_REF = pdf_service.RE_PAGE_REF


def _looks_like_example(text: str) -> bool:
    """例题/习题题干不是标题：标签加编号，或编号后紧跟题干动词/句读。"""
    if RE_CN_LABEL_NUM.match(text):
        return True
    m = RE_EXAMPLE_NUM.match(text)
    if not m:
        return False
    rest = text[m.end():].lstrip()
    return bool(RE_EXAMPLE_LEAD.match(rest) or re.search(r"[,，。；;：:]", rest))


def _numbering_level(text: str, max_level: int) -> int | None:
    """编号标题的层级由编号段数确定，不依赖模型判断。"""
    m = re.match(r"^(\d+(?:\.\d+)+)\D", text)
    if m:
        return min(m.group(1).count(".") + 1, max_level)
    # 章号后跟大写字母或汉字才是章标题；"1 do not ..." 一类小写开头是正文句子
    if re.match(r"^\d+\s+[A-Z\u4e00-\u9fff]", text) or pdf_service.RE_CHINESE_HEADING.match(text):
        return 1
    return None


def _is_non_content_page(texts: list[str]) -> bool:
    """无关页面整页剔除（实现与规则见 pdf_service，非 LLM 模式共用）。"""
    return pdf_service._is_non_content_page(texts)


def _extract_candidates(pdf_path: str, use_ocr: bool, progress_cb=None, cancel_check=None) -> list[dict]:
    doc = fitz.open(pdf_path)
    rows: list[dict] = []
    page_bodies: dict[int, float] = {}
    try:
        for page_number in range(doc.page_count):
            _check_cancel(cancel_check)
            page = doc.load_page(page_number)
            page_rows: list[dict] = []
            page_texts: list[str] = []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans") or []
                    text = "".join(s.get("text", "") for s in spans).strip()
                    # 清洗行首的项目符号、私用区字形（Wingdings 符号 \uf0b2 等）和孤立公式符号
                    text = re.sub(r"^[·•‧▪◦*\-–—-\s]+", "", text)
                    # 行尾的教材页码指引（"1、人生观     P16"、"P227 P233"）是注释不是标题文字
                    text = re.sub(r"\s*[PpＰｐ]\s*\d+(?:\s*[PpＰｐ]\s*\d+)*\s*$", "", text)
                    # 标题左侧同行的公式前缀（"SE·nda 矢量场的通量"、"ε0 真空电容率"）剥到首个汉字；
                    # 编号前缀（"1.1 ..."）和助词开头的标题（"K 的确定"）不动
                    m_cjk = re.search(r"[一-鿿]", text)
                    if m_cjk and m_cjk.start() > 0:
                        prefix, suffix = text[:m_cjk.start()], text[m_cjk.start():]
                        if (re.fullmatch(r"[A-Za-z0-9_.·=∂×∫∮∇ερσλ/()+\-\s]{1,20}", prefix)
                                and not re.match(r"^\d+\s*[.．]", text)
                                and not re.match(r"^[的和与及或在中等是，。、]", suffix)):
                            text = suffix
                    if not text:
                        continue
                    page_texts.append(text)
                    if not 2 <= len(text) <= 140:
                        continue
                    sizes = [float(s.get("size", 0)) for s in spans if s.get("text", "").strip()]
                    if not sizes:
                        continue
                    page_rows.append({
                        "page": page_number, "text": text, "size": max(sizes),
                        "bold": any((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans),
                        "bbox": tuple(line.get("bbox", ())), "page_height": page.rect.height,
                        "order": len(rows) + len(page_rows),
                    })
            if use_ocr and not page_rows:
                from . import ocr_service
                for line in ocr_service.ocr_page(doc, page):
                    text = line["text"].strip()
                    if not text:
                        continue
                    page_texts.append(text)
                    if 2 <= len(text) <= 140:
                        page_rows.append({
                            "page": page_number, "text": text, "size": float(line["size"]),
                            "bold": False, "bbox": tuple(line.get("rect") or ()),
                            "page_height": page.rect.height, "order": len(rows) + len(page_rows),
                        })
            if _is_non_content_page(page_texts):
                if progress_cb:
                    progress_cb(page_number + 1, doc.page_count)
                continue
            long_sizes = [r["size"] for r in page_rows if len(r["text"]) >= 30]
            if long_sizes:
                page_bodies[page_number] = sorted(long_sizes)[len(long_sizes) // 2]
            rows.extend(page_rows)
            if progress_cb:
                progress_cb(page_number + 1, doc.page_count)
    finally:
        doc.close()
    if not rows:
        return []
    rows = pdf_service._merge_numbered_row_fragments(rows)
    default_body = sorted((r["size"] for r in rows))[len(rows) // 2]
    frequency: dict[str, set[int]] = {}
    for row in rows:
        frequency.setdefault(row["text"], set()).add(row["page"])
    page_count = max(r["page"] for r in rows) + 1
    candidates = []
    for row in rows:
        text = row["text"]
        bbox = row["bbox"]
        if not bbox or len(bbox) != 4 or pdf_service.RE_PAGENUM.fullmatch(text):
            continue
        if RE_NUM_FRAGMENT.match(text) or _looks_like_example(text) or RE_FIGURE_CAPTION.match(text):
            continue
        # 候选文字本身带点线/省略号+页码结尾，是漏网的目录/索引条目，不是标题
        if RE_PAGE_REF.search(text):
            continue
        # 无汉字且含公式运算符的纯公式行（"× E = - ∂B"），不是标题
        if not re.search(r"[一-鿿]", text) and re.search(r"[=∂∫∮∇×]", text):
            continue
        if bbox[1] < row["page_height"] * 0.04 or bbox[3] > row["page_height"] * 0.96:
            continue
        numbered = bool(pdf_service.RE_EN_HEADING.match(text) or pdf_service.RE_CHINESE_HEADING.match(text)
                        or pdf_service.RE_NUM_HEADING.match(text) or RE_CN_ORDINAL_HEADING.match(text))
        # 带编号的标题（"一、实验设计目标"、"3.2 ..."）可能在全书反复出现，
        # 不能像页眉一样按频率剔除；是否页眉交给后续 LLM 步骤判断
        if not numbered and len(frequency[text]) >= max(4, page_count * 0.15):
            continue
        body = page_bodies.get(row["page"], default_body)
        if not (numbered or (len(text) <= 100 and (row["bold"] or row["size"] >= body * 1.1))):
            continue
        candidates.append({"id": len(candidates), "page": row["page"], "text": text,
                           "size": round(row["size"], 1), "body_size": round(body, 1),
                           "bold": row["bold"]})
    return candidates


def _load_json_loose(answer: str):
    """从模型回答中宽松提取 JSON（容忍代码围栏和前后缀文字）。"""
    content = answer.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[^\n]*\n?", "", content)
        content = re.sub(r"\s*```\s*$", "", content).strip()
    starts = [pos for char in ("{", "[") if (pos := content.find(char)) >= 0]
    if not starts:
        raise ValueError("模型没有返回书签 JSON，请换用指令模型重试")
    try:
        data, _ = json.JSONDecoder().raw_decode(content[min(starts):])
    except json.JSONDecodeError as exc:
        raise ValueError("模型返回的书签 JSON 无法解析，请重试或换用其他模型") from exc
    return data


def _parse_headings(answer: str, valid_ids: set[int], max_level: int) -> list[tuple[int, int]]:
    data = _load_json_loose(answer)
    headings = data.get("headings") if isinstance(data, dict) else data
    if not isinstance(headings, list):
        raise ValueError("模型返回的书签格式无效")
    selected = []
    seen = set()
    for item in headings:
        if not isinstance(item, dict) or type(item.get("id")) is not int or type(item.get("level")) is not int:
            continue
        index, level = item["id"], item["level"]
        if index in valid_ids and 1 <= level <= max_level and index not in seen:
            selected.append((index, level))
            seen.add(index)
    return sorted(selected)


def _chat_once(model_key: str, prompt: str) -> str:
    """流水线前置步骤的单次问答；推理模型同样会消耗输出预算，给足余量。"""
    response = _post_chat({
        "model": model_key, "input": prompt,
        "system_prompt": "你是严谨的 PDF 结构分析助手，只输出要求的内容。",
        "temperature": 0, "max_output_tokens": MAX_OUTPUT_TOKENS, "store": False,
    })
    return "\n".join(item.get("content", "") for item in response.get("output", [])
                     if item.get("type") == "message")


def _page_previews(pdf_path: str, max_pages: int = 20, lines_per_page: int = 3) -> list[str]:
    previews = []
    doc = fitz.open(pdf_path)
    try:
        for pno in range(min(max_pages, doc.page_count)):
            text = doc.load_page(pno).get_text("text")
            lines = [l.strip() for l in text.splitlines() if l.strip()][:lines_per_page]
            previews.append(f"页{pno}: " + (" / ".join(lines) if lines else "（无文字）"))
    finally:
        doc.close()
    return previews


def _reid(candidates: list[dict]) -> list[dict]:
    for i, c in enumerate(candidates):
        c["id"] = i
    return candidates


def _detect_book_title(pdf_path: str, model_key: str) -> str:
    """第 1 步：识别书名。文件名与元数据仅作参考，以封面/书名页文字为准。"""
    fallback = Path(pdf_path).stem
    doc = fitz.open(pdf_path)
    try:
        meta_title = (doc.metadata or {}).get("title") or ""
        first_text = "\n".join(
            doc.load_page(p).get_text("text")[:500] for p in range(min(5, doc.page_count)))
    finally:
        doc.close()
    if not first_text.strip():
        return fallback
    prompt = (
        "请判断这本书的书名（不是 PDF 文件名；文件名和元数据标题可能不准确，仅作参考，"
        "以封面/书名页的文字为准）。只回答书名本身，不要解释、不要标点。\n"
        f"文件名：{fallback}\n元数据标题：{meta_title}\n前几页文字：\n{first_text[:2500]}"
    )
    try:
        answer = _chat_once(model_key, prompt)
    except Exception:
        return fallback
    title = answer.strip().splitlines()[0].strip().strip("《》\"' ") if answer.strip() else ""
    return title if 2 <= len(title) <= 80 else fallback


def _llm_drop_front_matter(pdf_path: str, candidates: list[dict],
                           model_key: str, title: str) -> list[dict]:
    """第 2 步：在确定性页面过滤之上，由模型确认封面、版权、前言、目录等无关页。"""
    if not candidates:
        return candidates
    previews = _page_previews(pdf_path, max_pages=20)
    prompt = (
        f"这本书的书名是《{title}》。以下是本书前 20 页的开头文字。"
        "请判断哪些页属于封面、版权页、出版说明、前言、序言、目录、致谢等无关部分（不是正文章节）；"
        "封面页通常只有书名片段或作者名。"
        "把全书章节罗列在一起的课程结构/内容概览页（如 \"教材基本内容\"\"本课程结构\"\"内容安排\"，"
        "表现为连续多行 \"第一章…\"\"第二章…\" 的列表）也算目录类无关页，一并摘除。"
        "注意：目录常常跨越多页，续页开头不会再出现\"目录\"二字，"
        "只要某页主要由带点线（......）和页码的条目列表构成，它也是目录页，必须一并摘除。"
        "但每页预览只显示前几行且可能以重复的页眉书名开头，判断目录续页时该页必须几乎全是带点线的条目；"
        "若页面中出现不带点线的章节标题或正文句子，则该页是正文页，绝不能摘除。"
        "只返回 JSON：{\"drop_pages\":[0,1]}；没有则返回 {\"drop_pages\":[]}。\n"
        + "\n".join(previews)
    )
    try:
        data = _load_json_loose(_chat_once(model_key, prompt))
        pages = data.get("drop_pages") if isinstance(data, dict) else None
        if not isinstance(pages, list):
            return candidates
        drop = {p for p in pages if type(p) is int and 0 <= p < 10_000}
    except Exception:
        return candidates
    if not drop:
        return candidates
    # 防误摘：模型可能把目录续页之后的正文第一页也摘掉。
    # 含章节标题样式文字（且该文字不是带点线的目录条目）的页是正文页，不接受摘除。
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        doc = None
    if doc is None:
        return _reid([c for c in candidates if c["page"] not in drop])
    try:
        for p in sorted(drop):
            if p >= doc.page_count:
                continue
            lines = [l.strip() for l in doc.load_page(p).get_text("text").splitlines() if l.strip()]
            # 纯标题列表页（章节概览）没有正文长行，不受保护
            if not any(len(l) >= 40 for l in lines):
                continue
            for line in lines:
                if RE_PAGE_REF.search(line):
                    continue
                if (pdf_service.RE_CHINESE_HEADING.match(line) or pdf_service.RE_EN_HEADING.match(line)
                        or RE_CN_ORDINAL_HEADING.match(line)):
                    drop.discard(p)
                    break
    finally:
        doc.close()
    if not drop:
        return candidates
    return _reid([c for c in candidates if c["page"] not in drop])


def _llm_drop_running_heads(candidates: list[dict], model_key: str, title: str) -> list[dict]:
    """第 3 步：摘除每页重复的页眉/页脚（书名、章节名、装饰文字等）。"""
    if not candidates:
        return candidates
    freq: dict[str, set[int]] = {}
    for c in candidates:
        freq.setdefault(c["text"], set()).add(c["page"])
    suspects = sorted(t for t, pages in freq.items() if len(pages) >= 3)
    drop_texts: set[str] = set()
    # 书名或其片段是典型页眉，直接摘除
    if title:
        for t in suspects:
            if t in title or (len(t) >= 4 and t.upper() in title.upper()):
                drop_texts.add(t)
    if suspects:
        listing = json.dumps([{"text": t, "pages": len(freq[t])} for t in suspects[:80]],
                             ensure_ascii=False)
        prompt = (
            f"这本书的书名是《{title}》。以下文本在书中多个页面重复出现。"
            "请判断哪些是页眉/页脚内容（重复出现的书名、章节名、装饰文字、栏目名等）。"
            "注意：在不同章节反复出现的编号小节名（如 \"1.概念\"）是真实小节标题，不要摘除；"
            "\"习题\"\"小结\"\"参考文献\" 这类每章末尾固定出现一次的栏目名也是真实小节标题，不要摘除。"
            "只返回 JSON：{\"drop\":[\"文本\",\"...\"]}；没有则返回 {\"drop\":[]}。\n"
            + listing
        )
        try:
            data = _load_json_loose(_chat_once(model_key, prompt))
            drops = data.get("drop") if isinstance(data, dict) else None
            if isinstance(drops, list):
                drop_texts.update(d for d in drops if isinstance(d, str))
        except Exception:
            pass
    if not drop_texts:
        return candidates
    # 频率守卫：真正的页眉页脚会出现在大量页面上；
    # "习题""小结" 这类每章一次的栏目名是真实小节标题，即使模型误判也不摘
    page_count = max(c["page"] for c in candidates) + 1
    min_head_pages = max(5, int(page_count * 0.08))
    drop_texts = {t for t in drop_texts
                  if len(freq.get(t, ())) >= min_head_pages
                  or len(freq.get(t, ())) >= page_count * 0.2}
    if not drop_texts:
        return candidates
    return _reid([c for c in candidates if c["text"] not in drop_texts])


def _batch_prompt(batch: list[dict], recent: list[dict], max_level: int) -> str:
    return (
        "以下是按 PDF 原顺序提取的标题候选（已剔除目录、前言、致谢、索引等无关页面及页眉页脚）。"
        "请仅选真正的章节/小节标题。必须排除：公式和变量、图表说明、页眉、正文句子"
        "（包括以数字开头的正文句，如 \"1 do not necessarily ...\"、\"55 construct ...\"）、"
        "参考文献条目、习题编号和习题引用（孤立或带空格的纯数字，如 \"1 .4\"、\"13.1 5\"）、"
        "章节引用（如 \"Sec. 2.3\"、\"Fig. 4\"、\"Table 1\"）、"
        "定理/推论等标签（THEOREM、COROLLARY、LEMMA、CASE、PROOF、DEFINITION，及中文 \"定理2（有界性）\" 这类）、"
        "例题和习题题干（编号后紧跟\"设\"\"已知\"\"求\"\"证明\"\"解\"\"画\"等动词或句中含逗号句号，如 \"1.1.4画出...\"、\"3. 3.1设...\"）、"
        "位于 \"习题\"\"练习题\"\"Problems\" 标题之后的所有编号条目（那是习题编号不是小节，如 \"1. 14 圆柱坐标系中...\"、\"3. 6 边长分别为...\"）、"
        "正文中的编号列表步骤（如 \"1. Find ...\"）、习题答案内容、封面和书名页文字，"
        "以冒号结尾的正文枚举项（如 \"1. 有界性：\"、\"（1）可去间断点：\"、\"（2）规范性：\" 这类句中列表，不是标题；"
        "但冒号在中间、后面还有标题文字的候选是标题，如 \"3、凑微分法：要求熟练掌握各类导数\"），"
        "带括号的小编号项（如 \"（1）\"\"(2)\"\"（Ⅱ）\" 开头的候选一律不选），"
        "编号后接 20 字以上完整句子的候选（如 \"6.1 AD 输入接口接实验平台的信号源输出，DA 输出接示波器\"），那是正文不是标题，"
        "以及漏网的目录条目和索引词条。\n"
        "正文中加粗的段落引导句（完整的句子或带主谓结构的短语，如 \"The order of a differential equation\"）不是标题，不要选；"
        "但无编号、加粗或字号大于正文、独立成行的短名词性概念标题（如 \"电场\"、\"点乘\"、\"单位法向量\"，"
        "一般 2-15 字、不含动词和标点）是小节标题，应选中并定为 level 3（或按上下文归入合适层级）；"
        "无编号条目只有在独占页面（章标题页）时才是 level 1 标题。"
        "符合 \"N.M\" 编号格式且位于小节起始处的候选默认都应选中，不要遗漏（如 1.7、2.2 这类）。\n"
        "层级规则（严格遵守，包括第一批在内，不要参考上一批标题的层级）："
        "编号前的固定前缀（第、实验、项目、案例、Chapter、Lesson 等）不影响层级，层级只由编号段数决定："
        "\"实验三\"与\"第3章\"同为章级，\"实验2.2\"与\"2.2\"同为节级；"
        "编号 \"N\"（如 \"13\"、\"第3章\"、\"第5讲\"）是章，level 1；\"N.M\"（如 \"13.1\"、\"1.1\"）是节，level 2；"
        "\"N.M.K\" 是子节，level 3；无编号但独占页面或字号明显最大的章标题也是 level 1；"
        "中文序号\"一、二、三…\"式栏目是所属章节下的小节，层级 = 父级 + 1（不超过最大层级），且全书必须同一层级；"
        "中文书中\"基础知识结构\"\"基础内容精讲\"\"基础例题精解\"\"基础习题精练\"等固定栏目是节，level 2；"
        "同一章内同一编号风格必须层级一致：\"一、二、三\"式、\"1. 2. 3.\"式、\"题型N\"式各自内部的层级不得忽高忽低；"
        "同一标题拆成多个连续片段时只选一个片段（优先含编号的；\"CHAPTER N\" 与紧随的书名文字属同一标题）。\n"
        "只返回 JSON，格式为 {\"headings\":[{\"id\":0,\"level\":1}]}。"
        "id 必须来自候选，level 为 1 到 " + str(max_level) + "。不要改写文字、不要编造页码。\n"
        "上一批已确认标题（仅用于理解顺序，不要模仿其层级）：" + json.dumps(recent, ensure_ascii=False) + "\n"
        "候选：" + json.dumps(batch, ensure_ascii=False)
    )


def detect_headings(pdf_path: str, model_source: str, max_level: int = 3,
                    use_ocr: bool = False, progress_cb=None, status_cb=None,
                    cancel_check=None, llm_progress_cb=None) -> list[dict]:
    if status_cb:
        status_cb("正在扫描 PDF 标题候选…")
    candidates = _extract_candidates(pdf_path, use_ocr, progress_cb, cancel_check)
    _check_cancel(cancel_check)
    if not candidates:
        return []
    batch_count = (len(candidates) + MODEL_BATCH_SIZE - 1) // MODEL_BATCH_SIZE
    llm_total = 4 + batch_count
    if llm_progress_cb:
        llm_progress_cb(0, llm_total)
    if status_cb:
        status_cb("内置推理引擎正在加载模型…")
    from . import llm_engine
    model_path = llm_engine.validate_model(model_source)
    llm_engine.ensure_running(model_path, status_cb=status_cb)
    _check_cancel(cancel_check)
    model_key = "local"  # llama-server 单模型服务，名称仅作占位
    _ensure_server()
    if llm_progress_cb:
        llm_progress_cb(1, llm_total)
    # 第 1 步：识别书名（供后续步骤判断封面文字和页眉）
    _check_cancel(cancel_check)
    if status_cb:
        status_cb("正在识别书名…")
    book_title = _detect_book_title(pdf_path, model_key)
    if llm_progress_cb:
        llm_progress_cb(2, llm_total)
    # 第 2 步：摘除封面、前言、目录等无关部分
    _check_cancel(cancel_check)
    if status_cb:
        status_cb("正在摘除封面、前言、目录等无关部分…")
    candidates = _llm_drop_front_matter(pdf_path, candidates, model_key, book_title)
    if llm_progress_cb:
        llm_progress_cb(3, llm_total)
    if not candidates:
        if llm_progress_cb:
            llm_progress_cb(llm_total, llm_total)
        return []
    # 第 3 步：摘除每页重复的页眉页脚
    _check_cancel(cancel_check)
    if status_cb:
        status_cb("正在摘除页眉页脚…")
    candidates = _llm_drop_running_heads(candidates, model_key, book_title)
    if not candidates:
        if llm_progress_cb:
            llm_progress_cb(llm_total, llm_total)
        return []
    # 前置步骤可能删掉大量候选，按最终批次数修正总进度，确保任务完成时能走满。
    batch_count = (len(candidates) + MODEL_BATCH_SIZE - 1) // MODEL_BATCH_SIZE
    llm_total = 4 + batch_count
    if llm_progress_cb:
        llm_progress_cb(4, llm_total)
    # 第 4 步：筛选章节与小节
    toc = []
    for start in range(0, len(candidates), MODEL_BATCH_SIZE):
        _check_cancel(cancel_check)
        batch = candidates[start:start + MODEL_BATCH_SIZE]
        if status_cb:
            status_cb(f"本地模型正在判断标题：{min(start + len(batch), len(candidates))}/{len(candidates)}")
        recent = [{"title": h["title"], "level": h["level"]} for h in toc[-5:]]
        prompt = _batch_prompt(batch, recent, max_level)
        def ask(sub_batch: list[dict]) -> list[tuple[int, int]] | None:
            """问一批；失败返回 None。先标准预算，截断则加大预算，再失败拆半递归。"""
            sub_valid = {r["id"] for r in sub_batch}
            sub_prompt = prompt if sub_batch is batch else _batch_prompt(sub_batch, recent, max_level)
            for budget in (MAX_OUTPUT_TOKENS, RETRY_OUTPUT_TOKENS):
                _check_cancel(cancel_check)
                response = _post_chat({
                    "model": model_key, "input": sub_prompt,
                    "system_prompt": "你是严格的 PDF 目录标题分类器，只输出合法 JSON。",
                    "temperature": 0, "max_output_tokens": budget, "store": False,
                })
                answer = "\n".join(item.get("content", "") for item in response.get("output", [])
                                   if item.get("type") == "message")
                try:
                    return _parse_headings(answer, sub_valid, max_level)
                except ValueError:
                    if budget == MAX_OUTPUT_TOKENS and status_cb:
                        status_cb("模型输出被截断，正在加大输出上限重试本批…")
            if len(sub_batch) > 1:
                mid = len(sub_batch) // 2
                left = ask(sub_batch[:mid])
                right = ask(sub_batch[mid:])
                if left is None or right is None:
                    return None
                return left + right
            return None

        selected = ask(batch)
        if selected is None:
            if status_cb:
                status_cb(f"第 {start // MODEL_BATCH_SIZE + 1} 批模型多次未返回有效 JSON，已跳过该批候选")
            selected = []
        for index, level in selected:
            row = candidates[index]
            level = _numbering_level(row["text"], max_level) or level
            toc.append({"title": row["text"], "page": row["page"], "level": level})
        if llm_progress_cb:
            llm_progress_cb(5 + start // MODEL_BATCH_SIZE, llm_total)
    return pdf_service.finalize_toc(toc)
