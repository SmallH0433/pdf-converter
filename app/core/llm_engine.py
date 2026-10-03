"""内置 llama.cpp 推理运行时：脱离 LM Studio 直接加载 GGUF 模型。

打包时 llama-server（Vulkan 构建）随应用发布；源码运行时取项目根目录
``_llama/runtime/``。Vulkan 可用即自动跑在 GPU 上，否则回退 CPU。
"""
from __future__ import annotations

import atexit
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTEXT_SIZE = 32768
_start_lock = None  # 惰性创建，避免线程导入顺序问题
_proc: subprocess.Popen | None = None
_loaded_model: Path | None = None
_port: int | None = None


def runtime_dir() -> Path:
    """安装后存 exe 同级 _internal/llama；源码运行存项目根目录 _llama/runtime。"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        for cand in (base / "_internal" / "llama", base / "llama"):
            if (cand / "llama-server.exe").is_file():
                return cand
    return Path(__file__).resolve().parents[2] / "_llama" / "runtime"


def _server_exe() -> Path:
    exe = runtime_dir() / ("llama-server.exe" if os.name == "nt" else "llama-server")
    if not exe.is_file():
        raise RuntimeError(f"未找到内置推理运行时：{exe}（打包不完整）")
    return exe


def validate_model(source: str | Path) -> Path:
    path = Path(source).resolve()
    if path.suffix.lower() != ".gguf" or path.name.lower().startswith("mmproj-"):
        raise ValueError("请选择已下载完成的主模型 .gguf 文件（不要选择 mmproj 或 .part）")
    if not path.is_file():
        raise FileNotFoundError(f"模型文件不存在：{path}")
    with path.open("rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("所选文件不是有效的 GGUF 模型")
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _request(path: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{_port}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.load(resp)


def is_running() -> bool:
    if _proc is None or _proc.poll() is not None:
        return False
    try:
        _request("/health", timeout=2)
        return True
    except Exception:
        return False


def ensure_running(model_path: Path, status_cb=None) -> None:
    """启动（或复用）llama-server 并加载指定模型。"""
    global _proc, _loaded_model, _port
    model_path = Path(model_path)
    if is_running() and _loaded_model == model_path:
        return
    stop()
    exe = _server_exe()
    _port = _free_port()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if status_cb:
        status_cb("内置推理引擎正在加载模型（首次可能需要几十秒）…")
    _proc = subprocess.Popen(
        [str(exe), "-m", str(model_path), "--host", "127.0.0.1", "--port", str(_port),
         "-c", str(CONTEXT_SIZE), "-ngl", "99", "--no-warmup"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
    )
    _loaded_model = model_path
    deadline = time.time() + 300
    while time.time() < deadline:
        if _proc.poll() is not None:
            _proc = None
            raise RuntimeError("内置推理引擎启动失败（模型可能损坏或内存不足）")
        try:
            _request("/health", timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    stop()
    raise RuntimeError("内置推理引擎加载模型超时")


def stop() -> None:
    global _proc, _loaded_model
    if _proc is not None:
        try:
            _proc.terminate()
            _proc.wait(timeout=10)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
    _proc = None
    _loaded_model = None


atexit.register(stop)


def models() -> dict:
    return _request("/v1/models", timeout=5)


def chat(body: dict, timeout: int = 600) -> dict:
    """把应用内部的 LM-Studio 风格请求翻译成 OpenAI 兼容格式，再把回答翻译回来。"""
    prompt = body.get("input", "")
    system = body.get("system_prompt", "")
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    payload = {
        "model": "local",
        "messages": messages,
        "temperature": body.get("temperature", 0),
        "max_tokens": body.get("max_output_tokens", 4096),
    }
    resp = _request("/v1/chat/completions", payload, timeout=timeout)
    content = ""
    for choice in resp.get("choices", []):
        content += (choice.get("message") or {}).get("content") or ""
    # 兜底去掉思考标签（部分模板不支持 enable_thinking）
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return {"output": [{"type": "message", "content": content}]}
