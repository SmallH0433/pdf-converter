"""命令行入口：python ocr_pdf.py 输入.pdf [输出.pdf]

为扫描版 PDF 添加 OCR 文字层。有 NVIDIA GPU 且装好 CUDA 运行库时自动使用 GPU。
功能与 GUI 的「PDF OCR」页面共用 app.core.ocr_service。
"""
from __future__ import annotations

import sys
import time

from app.core.ocr_service import backend_name, ocr_pdf


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "数字电子技术基础 第6版.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".pdf", 1)[0] + "_ocr.pdf"
    print(f"OCR 后端：{backend_name()}", flush=True)
    t0 = time.time()

    def on_progress(done: int, total: int) -> None:
        el = time.time() - t0
        eta = el / done * (total - done) if done else 0
        print(f"[{done}/{total}] 已用 {el / 60:.1f} 分钟 · 预计剩余 {eta / 60:.1f} 分钟",
              flush=True)

    result = ocr_pdf(src, out, progress_cb=on_progress)
    print("完成：" + result if result else "已取消", flush=True)


if __name__ == "__main__":
    main()
