# -*- mode: python ; coding: utf-8 -*-
"""Standalone macOS Apple Silicon application bundle."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


APP_VERSION = "1.3.2"

datas = [("assets/branding/pdf-converter-icon-512.png", "assets/branding")]
binaries = []
hiddenimports = []

llama_runtime = Path("_llama/runtime")
if not (llama_runtime / "llama-server").is_file():
    raise RuntimeError(
        "缺少 macOS ARM64 llama.cpp 运行时：_llama/runtime/llama-server"
    )
datas.append((str(llama_runtime), "llama"))

hiddenimports += collect_submodules("pymupdf")
hiddenimports += collect_submodules("app.pages")
for package in ("qfluentwidgets", "rapidocr"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "onnxruntime.quantization",
        "onnxruntime.tools",
        "onnxruntime.transformers",
        "shapely.tests",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDF转换工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/branding/pdf-converter-icon-512.png",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PDF转换工具",
)

app = BUNDLE(
    coll,
    name="PDF转换工具.app",
    icon="assets/branding/pdf-converter-icon-512.png",
    bundle_identifier="com.smallh0433.pdf-converter",
    version=APP_VERSION,
    info_plist={
        "CFBundleDisplayName": "PDF 转换工具",
        "CFBundleName": "PDF 转换工具",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeExtensions": ["pdf"],
                "CFBundleTypeName": "PDF Document",
                "CFBundleTypeRole": "Editor",
            }
        ],
    },
)
