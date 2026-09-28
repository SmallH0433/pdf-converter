"""把本程序注册到 Windows 的 .pdf「打开方式」（HKCU，无需管理员权限）。"""
from __future__ import annotations

import os
import platform
import sys

PROGID = "PDFConverterTool.pdf"
_CLASSES = r"Software\Classes"


def supported() -> bool:
    return platform.system() == "Windows"


def _open_command() -> str:
    """打开命令：打包版直接调用 exe；源码运行用 pythonw + run.py。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    python = pythonw if os.path.exists(pythonw) else sys.executable
    run_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "run.py"))
    return f'"{python}" "{run_py}" "%1"'


def _exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def register() -> None:
    """注册 ProgId 并加入 .pdf 的 OpenWithProgids 列表。"""
    if not supported():
        raise RuntimeError("仅支持 Windows")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{_CLASSES}\{PROGID}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "PDF 文档 (PDF 转换工具)")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          rf"{_CLASSES}\{PROGID}\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{_exe_path()}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          rf"{_CLASSES}\{PROGID}\shell\open") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "用 PDF 转换工具打开")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          rf"{_CLASSES}\{PROGID}\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _open_command())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          rf"{_CLASSES}\.pdf\OpenWithProgids") as k:
        winreg.SetValueEx(k, PROGID, 0, winreg.REG_SZ, "")


def unregister() -> None:
    """移除注册（ProgId 树与 OpenWithProgids 项）。"""
    if not supported():
        return
    import winreg
    for sub in (rf"{PROGID}\shell\open\command", rf"{PROGID}\shell\open",
                rf"{PROGID}\shell", rf"{PROGID}\DefaultIcon", PROGID):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{_CLASSES}\{sub}")
        except OSError:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            rf"{_CLASSES}\.pdf\OpenWithProgids", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, PROGID)
    except OSError:
        pass


def is_registered() -> bool:
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            rf"{_CLASSES}\{PROGID}\shell\open\command") as k:
            cmd, _ = winreg.QueryValueEx(k, "")
            return bool(cmd)
    except OSError:
        return False
