"""用 LM Studio 的本地模型判断 PDF 标题候选，模型文件不随安装包发布。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import fitz

from . import pdf_service


API_BASE = "http://127.0.0.1:1234"
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


def _lms_executable() -> str:
    found = shutil.which("lms")
    if found:
        return found
    bundled = Path.home() / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms")
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError("未找到 LM Studio 命令行工具。请安装 LM Studio 并启动其本地服务。")


def _lms(*args: str, timeout: int = 120) -> str:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        [_lms_executable(), *args], capture_output=True, text=True,
        timeout=timeout, creationflags=flags,
    )
    if result.returncode:
        raise RuntimeError(f"LM Studio 操作失败：{(result.stderr or result.stdout).strip()}")
    return result.stdout


def _post_chat(body: dict, timeout: int = 600) -> dict:
    """发起对话请求；模型加载/切换期间 LM Studio 可能短暂返回 5xx，自动重试。"""
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
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    token = os.environ.get("LM_STUDIO_API_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API_BASE + path, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def _ensure_server() -> None:
    try:
        _json_request("/api/v1/models", timeout=2)
        return
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("LM Studio 本地服务需要密钥，请设置 LM_STUDIO_API_TOKEN") from exc
        raise
    except (urllib.error.URLError, TimeoutError):
        _lms("server", "start", timeout=30)
    for _ in range(20):
        try:
            _json_request("/api/v1/models", timeout=2)
            return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError("无法连接 LM Studio 本地服务（127.0.0.1:1234）")


def _same_file_content(a: Path, b: Path) -> bool:
    """抽样比对首尾各 4MB，避免对数 GB 模型做全量哈希。"""
    if a.stat().st_size != b.stat().st_size:
        return False
    sample = 4 * 1024 * 1024
    with a.open("rb") as fa, b.open("rb") as fb:
        if fa.read(sample) != fb.read(sample):
            return False
        if a.stat().st_size > sample:
            fa.seek(-sample, os.SEEK_END)
            fb.seek(-sample, os.SEEK_END)
            if fa.read(sample) != fb.read(sample):
                return False
    return True


def _import_copied_model(model_path: Path) -> str:
    """把项目内副本注册给 LM Studio；同盘优先硬链接，避免重复占用空间。"""
    folder = model_path.parent.name
    indexed_path = f"pdf-converter/{folder}/{model_path.name}"
    registry_path = lmstudio_models_dir() / indexed_path
    if not registry_path.exists():
        link_mode = "--hard-link" if registry_path.drive.casefold() == model_path.drive.casefold() else "--symbolic-link"
        _lms("import", str(model_path), link_mode, "--user-repo", f"pdf-converter/{folder}", "--yes")
    elif not registry_path.samefile(model_path):
        # 源码运行与安装版各自保存副本时，注册项可能链接到另一份同内容副本，直接复用
        if not _same_file_content(registry_path, model_path):
            raise RuntimeError("LM Studio 中已有同名但不同内容的模型，请重新选择")
    # LM Studio 对新导入模型的索引有短暂延迟，不能立刻回退到原模型。
    for attempt in range(20):
        models = json.loads(_lms("ls", "--llm", "--json"))
        for model in models:
            if model.get("path", "").replace("\\", "/").casefold() == indexed_path.casefold():
                return model["modelKey"]
        if attempt < 19:
            time.sleep(0.5)
    raise RuntimeError("模型副本已复制，但 LM Studio 尚未识别；请在 LM Studio 中刷新模型列表后重试")


def _original_model_key(source: str | Path) -> str | None:
    """无法注册副本时，仍可使用 LM Studio 模型目录中的原模型。"""
    try:
        relative = Path(source).resolve().relative_to(lmstudio_models_dir().resolve()).as_posix()
    except ValueError:
        return None
    for model in json.loads(_lms("ls", "--llm", "--json")):
        if model.get("path", "").replace("\\", "/").casefold() == relative.casefold():
            return model["modelKey"]
    return None


# 目录、前言、索引等无关页面：整页候选剔除，防止污染标题识别
# 书眉常在关键词前后带罗马数字页码（如 "Ⅱ 目录"），中文前言常带版次（如 "第六版前言"）
_ROMAN_PAD = r"[0-9ivxlcdmⅠ-Ⅻⅰ-ⅻ\s]*"
RE_TOC_MARKER = re.compile(rf"^{_ROMAN_PAD}(contents|目\s*录){_ROMAN_PAD}$", re.IGNORECASE)
RE_INDEX_MARKER = re.compile(rf"^{_ROMAN_PAD}((subject\s+)?index|索\s*引){_ROMAN_PAD}$", re.IGNORECASE)
RE_FRONT_MATTER_MARKER = re.compile(
    rf"^{_ROMAN_PAD}(第\s*[0-9一二三四五六七八九十]+\s*版\s*)?"
    rf"(preface|foreword|acknowledg\w*|前\s*言|序\s*言|序|致\s*谢|后\s*记|跋"
    rf"|answers(\s+to\s+[\w\s-]+)?|习题答案|答案){_ROMAN_PAD}$",
    re.IGNORECASE)
# 条目后跟页码（点线/省略号/逗号引导），是目录或索引条目的特征
RE_PAGE_REF = re.compile(r"(?:\.{3,}|…+|,)\s*\d{1,4}(?:\s*[-–,]\s*\d{1,4})*\s*$")
RE_ROMAN_LINE = re.compile(r"^\s*[ivxlcdm]{1,8}\s*$", re.IGNORECASE)
RE_NUM_LINE = re.compile(r"^\s*\d{1,4}\s*$")
# 只有数字、空格和点的碎片（"1 .2"、"13.1 5"），是 OCR 拆散的习题号或交叉引用，不是标题
RE_NUM_FRAGMENT = re.compile(r"^\d+(?:[\s.．]+\d*)*[.．]?$")
# 例题/习题题干：三级以上编号（允许 OCR 空格，如 "3. 3.1"）后紧跟题干
RE_EXAMPLE_NUM = re.compile(r"^\d+(?:\s*[.．]\s*\d+){2,}")
RE_EXAMPLE_LEAD = re.compile(r"^(设|已知|求|证明|解|画|计|若|判|试|讨论|分析|用|给)")
# 定理/例题等中文标签加编号（"定理2（有界性）"、"例3.1"）
RE_CN_LABEL_NUM = re.compile(r"^[【\[]?(定理|推论|引理|例)\s*\d")


def _looks_like_example(text: str) -> bool:
    """例题/习题题干不是标题：标签加编号，或三级编号后紧跟题干动词/句读。"""
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
    """目录/索引页条目密集且带页码，前言等页面标题无书签价值，整页跳过。"""
    for text in texts:
        if (RE_TOC_MARKER.match(text) or RE_INDEX_MARKER.match(text)
                or RE_FRONT_MATTER_MARKER.match(text)):
            return True
    strong = sum(1 for t in texts if RE_PAGE_REF.search(t))
    roman = sum(1 for t in texts if RE_ROMAN_LINE.match(t))
    # 单独的纯数字行只有在存在其他页码证据时才计入，避免把习题号误判成目录页码
    plain = sum(1 for t in texts if RE_NUM_LINE.match(t)) if (roman >= 3 or strong >= 3) else 0
    refs = strong + plain
    # 长页按绝对数量判，短页（目录续页）按比例判
    return (refs >= 12 and refs >= len(texts) * 0.35) or (refs >= 5 and refs >= len(texts) * 0.6)


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
        if RE_NUM_FRAGMENT.match(text) or _looks_like_example(text):
            continue
        if bbox[1] < row["page_height"] * 0.04 or bbox[3] > row["page_height"] * 0.96:
            continue
        if len(frequency[text]) >= max(4, page_count * 0.15):
            continue
        body = page_bodies.get(row["page"], default_body)
        numbered = bool(pdf_service.RE_EN_HEADING.match(text) or pdf_service.RE_CHINESE_HEADING.match(text)
                        or pdf_service.RE_NUM_HEADING.match(text))
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
        "封面页通常只有书名片段或作者名。只返回 JSON：{\"drop_pages\":[0,1]}；没有则返回 {\"drop_pages\":[]}。\n"
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
            "注意：在不同章节反复出现的编号小节名（如 \"1.概念\"）是真实小节标题，不要摘除。"
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
    return _reid([c for c in candidates if c["text"] not in drop_texts])


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
        status_cb("正在复制模型到应用目录（首次使用可能需要几分钟）…")
    last_percent = -1

    def on_copy(done: int, total: int) -> None:
        nonlocal last_percent
        percent = int(done * 100 / total)
        if status_cb and percent >= last_percent + 5:
            status_cb(f"正在复制模型到应用目录：{percent}%")
            last_percent = percent

    copied = copy_model_to_project(model_source, progress_cb=on_copy, cancel_check=cancel_check)
    _check_cancel(cancel_check)
    if status_cb:
        status_cb("正在通过 LM Studio 加载本地模型…")
    try:
        model_key = _import_copied_model(copied)
    except RuntimeError:
        model_key = _original_model_key(model_source)
        if model_key is None:
            raise
        if status_cb:
            status_cb("模型副本已保存在应用目录；无法注册副本，改用 LM Studio 原模型运行")
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
        prompt = (
            "以下是按 PDF 原顺序提取的标题候选（已剔除目录、前言、致谢、索引等无关页面及页眉页脚）。"
            "请仅选真正的章节/小节标题。必须排除：公式和变量、图表说明、页眉、正文句子"
            "（包括以数字开头的正文句，如 \"1 do not necessarily ...\"、\"55 construct ...\"）、"
            "参考文献条目、习题编号和习题引用（孤立或带空格的纯数字，如 \"1 .4\"、\"13.1 5\"）、"
            "章节引用（如 \"Sec. 2.3\"、\"Fig. 4\"、\"Table 1\"）、"
            "定理/推论等标签（THEOREM、COROLLARY、LEMMA、CASE、PROOF、DEFINITION，及中文 \"定理2（有界性）\" 这类）、"
            "例题和习题题干（编号后紧跟\"设\"\"已知\"\"求\"\"证明\"\"解\"\"画\"等动词或句中含逗号句号，如 \"1.1.4画出...\"、\"3. 3.1设...\"）、"
            "正文中的编号列表步骤（如 \"1. Find ...\"）、习题答案内容、封面和书名页文字，"
            "以及漏网的目录条目和索引词条。\n"
            "正文中加粗的段落引导句（如 \"The order of a differential equation\"）不是标题，不要选；"
            "无编号条目只有在独占页面（章标题页）时才是 level 1 标题。"
            "符合 \"N.M\" 编号格式且位于小节起始处的候选默认都应选中，不要遗漏（如 1.7、2.2 这类）。\n"
            "层级规则（严格遵守，包括第一批在内，不要参考上一批标题的层级）："
            "编号 \"N\"（如 \"13\"、\"第3章\"、\"第5讲\"）是章，level 1；\"N.M\"（如 \"13.1\"、\"1.1\"）是节，level 2；"
            "\"N.M.K\" 是子节，level 3；无编号但独占页面或字号明显最大的章标题也是 level 1；"
            "中文书中\"基础知识结构\"\"基础内容精讲\"\"基础例题精解\"\"基础习题精练\"等固定栏目是节，level 2；"
            "同一标题拆成多个连续片段时只选一个片段（优先含编号的；\"CHAPTER N\" 与紧随的书名文字属同一标题）。\n"
            "只返回 JSON，格式为 {\"headings\":[{\"id\":0,\"level\":1}]}。"
            "id 必须来自候选，level 为 1 到 " + str(max_level) + "。不要改写文字、不要编造页码。\n"
            "上一批已确认标题（仅用于理解顺序，不要模仿其层级）：" + json.dumps(recent, ensure_ascii=False) + "\n"
            "候选：" + json.dumps(batch, ensure_ascii=False)
        )
        valid_ids = {r["id"] for r in batch}
        budget = MAX_OUTPUT_TOKENS
        while True:
            _check_cancel(cancel_check)
            response = _post_chat({
                "model": model_key, "input": prompt, "system_prompt": "你是严格的 PDF 目录标题分类器，只输出合法 JSON。",
                "temperature": 0, "max_output_tokens": budget, "store": False,
            })
            answer = "\n".join(item.get("content", "") for item in response.get("output", [])
                               if item.get("type") == "message")
            try:
                selected = _parse_headings(answer, valid_ids, max_level)
                break
            except ValueError:
                if budget >= RETRY_OUTPUT_TOKENS:
                    raise
                budget = RETRY_OUTPUT_TOKENS
                if status_cb:
                    status_cb("模型输出被截断，正在加大输出上限重试本批…")
        for index, level in selected:
            row = candidates[index]
            level = _numbering_level(row["text"], max_level) or level
            toc.append({"title": row["text"], "page": row["page"], "level": level})
        if llm_progress_cb:
            llm_progress_cb(5 + start // MODEL_BATCH_SIZE, llm_total)
    return pdf_service.normalize_toc(toc)
