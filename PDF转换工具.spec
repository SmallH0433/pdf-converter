# -*- mode: python ; coding: utf-8 -*-
# 文件夹版（onedir）打包：OCR 组件（rapidocr/onnxruntime-gpu/cv2/numpy 等）随包发布、开箱即用；
# GPU 加速所需的 nvidia CUDA 运行库不打包，由用户在「PDF OCR」页一键安装到 exe 同级
# ocr_modules/（因此捆绑 pip 供运行时安装）。onnxruntime-gpu 缺 CUDA 库时自动退回 CPU。
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import copy_metadata
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# onnxruntime 的 CPU/CUDA/DirectML 发行版会写入同一个包目录。混装时 pip 元数据
# 看似正常，实际 DLL 可能来自不同版本，最终只剩 CPU Provider 或在目标机加载失败。
# 构建阶段直接阻止污染环境进入安装包。
conflicting_ort = []
for package in ('onnxruntime', 'onnxruntime-directml', 'rapidocr-onnxruntime'):
    try:
        conflicting_ort.append(f'{package}=={version(package)}')
    except PackageNotFoundError:
        pass
if conflicting_ort:
    raise RuntimeError(
        '检测到与 onnxruntime-gpu 冲突的发行版：' + ', '.join(conflicting_ort)
        + '。请先卸载冲突包并强制重装 requirements.txt 后再打包。')

datas = [
    ('assets/branding/pdf-converter.ico', 'assets/branding'),
]
# 内置 llama.cpp 推理运行时（llama-server，Vulkan 构建，GPU 可用即用、否则 CPU）
datas += [('_llama/runtime', 'llama')]
binaries = []
hiddenimports = []
hiddenimports += collect_submodules('pymupdf')
tmp_ret = collect_all('qfluentwidgets')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# OCR 组件（含模型文件、onnxruntime 的 CUDA provider DLL）
tmp_ret = collect_all('rapidocr')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shapely')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# 运行时一键安装 GPU 加速包需要 pip（含版本元数据、cacert.pem、distlib 启动器）与证书
hiddenimports += collect_submodules('pip')
datas += copy_metadata('pip')
datas += collect_data_files('pip')
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

excludes = []

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
# Qt6Core.dll 在 Windows 上调用系统 ICU 的无版本后缀接口。构建机 PATH 中的
# Poppler 可能带有同名 icuuc.dll（导出 ucnv_open_78 而不是 ucnv_open），
# PyInstaller 会误收集它，导致安装后在导入 QtWidgets 时立即崩溃。
# Windows 10/11 自带兼容的 icuuc.dll；不要把外部 Poppler 的 ICU 打进包。
incompatible_icu = {'icuuc.dll', 'icudt78.dll'}
a.binaries = [
    entry for entry in a.binaries
    if Path(entry[0]).name.lower() not in incompatible_icu
]
# 用户选择的本地 LLM 只保存在 exe 同级 llm_models/，绝不进入分发包。
def is_local_model(entry):
    target = Path(entry[0])
    return (any(part.lower() == 'llm_models' for part in target.parts)
            or target.name.lower().endswith(('.gguf', '.gguf.part', '.gguf.copying')))


a.datas = [entry for entry in a.datas if not is_local_model(entry)]
a.binaries = [entry for entry in a.binaries if not is_local_model(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF转换工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/branding/pdf-converter.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PDF转换工具',
)
