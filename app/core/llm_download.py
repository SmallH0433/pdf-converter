"""推荐模型的一键下载：empero-ai/Qwen3.8-4B-Distill-GGUF（Q4_K_M）。

默认走 hf-mirror.com（国内可达），失败回退 huggingface.co。
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

RECOMMENDED_REPO = "empero-ai/Qwen3.8-4B-Distill-GGUF"
RECOMMENDED_FILE = "Qwen3.8-4B-Q4_K_M.gguf"
RECOMMENDED_LABEL = "Qwen3.8-4B-Distill（推荐）"
MIRRORS = ("https://hf-mirror.com", "https://huggingface.co")


def recommended_path(store: Path) -> Path:
    return store / "recommended" / RECOMMENDED_FILE


def is_recommended(path: Path) -> bool:
    """推荐模型的主文件名（Qwen3.8-4B 的 Q4_K_M 量化版）。"""
    return path.name.casefold() == RECOMMENDED_FILE.casefold()


def download_recommended(dest_dir: Path, progress_cb=None, cancel_check=None,
                         status_cb=None) -> Path:
    """流式下载推荐模型到 dest_dir，返回最终路径。支持取消与镜像回退。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / RECOMMENDED_FILE
    part = target.with_name(target.name + ".part")
    last_exc: Exception | None = None
    for mirror in MIRRORS:
        url = f"{mirror}/{RECOMMENDED_REPO}/resolve/main/{RECOMMENDED_FILE}"
        try:
            if status_cb:
                status_cb(f"正在从 {urllib.request.urlparse(url).hostname} 下载推荐模型…")
            _download(url, part, progress_cb, cancel_check)
            os.replace(part, target)
            return target
        except _Cancelled:
            part.unlink(missing_ok=True)
            raise RuntimeError("已取消模型下载")
        except Exception as exc:  # noqa: BLE001 换镜像重试
            last_exc = exc
    part.unlink(missing_ok=True)
    raise RuntimeError(f"推荐模型下载失败：{last_exc}")


class _Cancelled(Exception):
    pass


def _download(url: str, part: Path, progress_cb, cancel_check) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "pdf-converter"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with part.open("wb") as f:
            while True:
                if cancel_check and cancel_check():
                    raise _Cancelled()
                chunk = resp.read(4 * 1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
