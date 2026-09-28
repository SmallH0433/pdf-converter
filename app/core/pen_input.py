"""手写笔输入的平台抽象层：按当前操作系统选择对应的原生手写 API。

Qt 会把各系统的原生手写输入统一路由到 QTabletEvent，本模块负责：
按平台识别实际生效的后端、声明其能力（压感 / 橡皮擦端 / 倾斜），
并给出各平台下的交互策略（如 Android 上手指滚动、手写笔书写）。

- Windows        → Windows Ink（Qt6 默认手写板 API）
- Android        → Android Stylus / MotionEvent（S Pen 等，AXIS_PRESSURE）
- iPadOS         → Apple Pencil / UIKit——PySide6 无法运行，标记为不支持
- macOS          → NSEvent 数位板事件（外接数位板；Apple Pencil 仅 iPad 可用）
- Linux          → X11 / Wayland 数位板事件（libinput）
- 其他/触屏无笔  → 回退为鼠标书写（无压感）
"""
from __future__ import annotations

import platform
import sys

BACKENDS: dict[str, dict] = {
    "windows": {
        "name": "Windows Ink",
        "pressure": True, "eraser": True, "tilt": True,
        # 桌面平台允许鼠标书写（无压感兜底）
        "mouse_draws": True, "finger_scrolls": True,
    },
    "android": {
        "name": "Android Stylus (MotionEvent)",
        "pressure": True, "eraser": True, "tilt": True,
        # 触屏设备：手指用于滚动/翻页，只有手写笔书写，避免误触笔迹
        "mouse_draws": False, "finger_scrolls": True,
    },
    "ipados": {
        # PySide6 不支持 iPadOS，实际不会走到；保留条目以明确能力边界
        "name": "Apple Pencil（iPadOS 不支持运行本程序）",
        "pressure": False, "eraser": False, "tilt": False,
        "mouse_draws": False, "finger_scrolls": True,
    },
    "macos": {
        "name": "macOS 数位板事件 (NSEvent)",
        "pressure": True, "eraser": True, "tilt": True,
        "mouse_draws": True, "finger_scrolls": True,
    },
    "linux": {
        "name": "X11/Wayland 数位板事件 (libinput)",
        "pressure": True, "eraser": True, "tilt": True,
        "mouse_draws": True, "finger_scrolls": True,
    },
    "other": {
        "name": "通用手写板事件",
        "pressure": True, "eraser": False, "tilt": False,
        "mouse_draws": True, "finger_scrolls": False,
    },
}


def current_platform() -> str:
    """当前操作系统：windows / android / ipados / macos / linux / other。"""
    if hasattr(sys, "getandroidapilevel"):
        return "android"
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        # iPadOS 上 Python 会报 Darwin，但 PySide6 无法在 iPadOS 构建运行；
        # 若未来出现可用运行时，按 machine 信息进一步区分
        if "iPad" in platform.machine() or "iPad" in platform.node():
            return "ipados"
        return "macos"
    if system == "Linux":
        return "linux"
    return "other"


def backend() -> dict:
    """当前平台的手写后端描述（见 BACKENDS 各字段）。"""
    return BACKENDS.get(current_platform(), BACKENDS["other"])


def backend_name() -> str:
    return backend()["name"]


def supports_pressure() -> bool:
    return backend()["pressure"]


def supports_eraser() -> bool:
    return backend()["eraser"]


def mouse_draws() -> bool:
    """非笔指针（鼠标/手指）是否允许书写。Android 上手指专用于滚动翻页。"""
    return backend()["mouse_draws"]


def pen_kind(event) -> str:
    """手写板事件的指针类别：'pen' / 'eraser' / 'finger' / 'cursor' / 'unknown'。"""
    try:
        return event.pointerType().name.lower()
    except Exception:  # noqa: BLE001
        return "unknown"


def status_text() -> str:
    """界面展示用的手写能力描述。"""
    b = backend()
    caps = []
    if b["pressure"]:
        caps.append("压感")
    if b["eraser"]:
        caps.append("橡皮擦端")
    if b["mouse_draws"]:
        caps.append("鼠标可书写")
    suffix = "、".join(caps) if caps else "仅鼠标"
    return f"手写后端：{b['name']}（{suffix}）"


def enable_kinetic_scroll(scroll_area) -> None:
    """给滚动区挂接触摸手势滚动（惯性滚动）。

    用 TouchGesture 而非 LeftMouseButtonGesture：后者会把鼠标左键拖拽也当作
    页面滚动，与按住左键手写标注冲突；触摸手势只响应触摸输入，鼠标完全留给标注。
    """
    if not backend()["finger_scrolls"]:
        return
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() == "offscreen":
            return  # 离屏（测试）平台无手势识别器，挂接会在退出时崩溃
        from PySide6.QtWidgets import QScroller
        QScroller.grabGesture(scroll_area.viewport(),
                              QScroller.ScrollerGestureType.TouchGesture)
    except Exception:  # noqa: BLE001
        pass
