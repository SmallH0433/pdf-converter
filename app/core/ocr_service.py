"""扫描件 OCR：RapidOCR 中文模型，为无文字层的 PDF 添加可搜索的隐形文字层。

OCR 组件（rapidocr / onnxruntime-gpu 等）随主程序打包，开箱即用。
GPU 加速包可按需安装多个（NVIDIA CUDA 与 DirectML 互存），开始 OCR 任务时
按当时的状态（插电/离电等）自动选择最佳后端：

- NVIDIA（Windows/Linux）：CUDA —— 加速包装到 ocr_modules/（约 1.1GB）
- AMD / Intel / 高通（Windows 10+，含核显）：DirectML —— 装到 ocr_modules_dml/（约 250MB）
- 苹果 Mac（源码运行）：CoreML —— onnxruntime 官方 macOS 版自带，无需安装
- 华为海思（麒麟/马良/Ascend）：ONNX Runtime 无可用桌面后端，识别后明确提示；
  华为 Windows 笔记本的实际显卡是 Intel/AMD，由 DirectML 覆盖

两个后端对应的 onnxruntime 发行版互斥（包名同为 onnxruntime），因此 DirectML 版
放在独立目录，引擎首次创建时才按选择加载其一；插电优先 CUDA（独显性能最高），
离电时若装有 DirectML 则改走 DirectML（默认使用当前显示输出 GPU：独显直连用独显、
混合输出用核显），更省电。

手机（联发科/高通/海思/苹果的 Android/iOS）无法运行本程序，需用 onnxruntime-mobile
等移动端框架另行开发 App。
"""
from __future__ import annotations

import contextlib
import glob
import importlib
import os
import platform
import re
import shutil
import subprocess
import sys
import threading

import fitz  # PyMuPDF

# CUDA 加速包：onnxruntime-gpu 已内置于程序，只需补 CUDA 运行库
CUDA_PACKAGES = [
    "nvidia-cuda-runtime-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cublas-cu12",
    "nvidia-cufft-cu12",
]
# DirectML 加速包：与内置 onnxruntime 同版本，--no-deps 避免依赖遮蔽内置包
DML_PACKAGES = ["--no-deps", "onnxruntime-directml==1.22.0"]
PIP_INDEXES = ["https://pypi.tuna.tsinghua.edu.cn/simple", "https://pypi.org/simple"]

_engine = None
_active_backend: str | None = None
_engine_lock = threading.Lock()
_dll_dir_handles: list = []
_added_dll_dirs: set[str] = set()
_NOT_INSTALLED = "OCR 组件缺失（rapidocr 未安装）"


# ---- 组件目录与环境 ----

def modules_dir() -> str:
    """CUDA 加速包安装目录：打包后为 exe 同级 ocr_modules/，开发时为项目根 ocr_modules/。"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(base, 'ocr_modules')


def dml_modules_dir() -> str:
    """DirectML 加速包安装目录（与 CUDA 包分开存放，避免 onnxruntime 同名冲突）。"""
    return modules_dir().replace('ocr_modules', 'ocr_modules_dml')


_dir_finders_installed: set[str] = set()


def _install_dir_finder(d: str) -> None:
    """让目录 d 中的顶层包可优先于打包内嵌的同名模块被导入（frozen 模式必需）。"""
    if d in _dir_finders_installed:
        return
    import importlib.machinery

    class _ModulesDirFinder:
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            if path is not None:  # 子模块由父包 __path__ 正常解析
                return None
            if (os.path.isdir(os.path.join(d, fullname))
                    or os.path.exists(os.path.join(d, fullname + '.py'))):
                return importlib.machinery.PathFinder.find_spec(fullname, [d])
            return None

    sys.meta_path.insert(0, _ModulesDirFinder)
    _dir_finders_installed.add(d)


def _use_modules_dir(d: str) -> None:
    """把组件目录加入模块搜索路径（dev 模式靠 sys.path 优先级，frozen 模式再加 finder）。"""
    if not os.path.isdir(d):
        return
    if d not in sys.path:
        sys.path.insert(0, d)
    if getattr(sys, 'frozen', False):
        _install_dir_finder(d)


def _candidate_dll_dirs() -> list[str]:
    """nvidia CUDA 运行库可能所在的 bin 目录（加速包目录 / 打包内嵌 / 开发 venv）。"""
    roots = [modules_dir()]
    if getattr(sys, 'frozen', False):
        roots.append(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))
    roots.append(os.path.abspath(
        os.path.join(os.path.dirname(sys.executable), '..', 'Lib', 'site-packages')))
    out: list[str] = []
    for root in roots:
        out.extend(d for d in glob.glob(os.path.join(root, 'nvidia', '*', 'bin'))
                   if os.path.isdir(d))
    return out


def _setup_cuda_dlls() -> None:
    """把 nvidia-* CUDA 运行库加入 DLL 搜索路径（Windows）。"""
    for d in _candidate_dll_dirs():
        if d in _added_dll_dirs:
            continue
        try:
            # 返回的句柄必须在进程生命周期内保持引用；否则 CPython 会立即撤销目录。
            _dll_dir_handles.append(os.add_dll_directory(d))
        except (AttributeError, OSError):
            pass
        os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')
        _added_dll_dirs.add(d)


# ---- 显卡、供电状态与后端检测 ----

_gpu_names_cache: list[str] | None = None


def gpu_names() -> list[str]:
    """本机显卡型号列表（Windows 经 WMI 查询；其他平台尽力而为）。"""
    global _gpu_names_cache
    if _gpu_names_cache is not None:
        return _gpu_names_cache
    names: list[str] = []
    if platform.system() == 'Windows':
        try:
            out = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            names = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        except Exception:
            names = []
    elif platform.system() == 'Darwin':
        try:
            out = subprocess.run(['system_profiler', 'SPDisplaysDataType'],
                                 capture_output=True, text=True, timeout=15)
            names = [l.strip().rstrip(':') for l in out.stdout.splitlines()
                     if 'Chipset Model' in l or 'Chip:' in l]
        except Exception:
            names = []
    _gpu_names_cache = names
    return names


def has_nvidia_gpu() -> bool:
    if shutil.which('nvidia-smi') is not None:
        return True
    return any('nvidia' in n.lower() for n in gpu_names())


def has_hisilicon() -> bool:
    """是否检测到华为海思芯片（麒麟/昇腾/马良等）。"""
    return any(k in n.lower() for n in gpu_names()
               for k in ('hisilicon', 'kirin', 'ascend', 'maleoon'))


def gpu_kind() -> str:
    """显卡厂商类别：nvidia / hisilicon / other（AMD·Intel·高通等）/ apple / none。"""
    if has_nvidia_gpu():
        return 'nvidia'
    if has_hisilicon():
        return 'hisilicon'
    if platform.system() == 'Darwin':
        return 'apple'  # Apple Silicon / 核显均可走 CoreML
    names = [n.lower() for n in gpu_names()]
    if any(k in n for n in names for k in ('amd', 'radeon', 'intel', 'arc', 'qualcomm', 'adreno')):
        return 'other'
    return 'none' if not names else 'other'


def power_state() -> str:
    """供电状态：'ac' 插电 / 'battery' 离电 / 'unknown'（台式机或非 Windows 平台）。"""
    if platform.system() != 'Windows':
        return 'unknown'
    try:
        import ctypes

        class _SPS(ctypes.Structure):
            _fields_ = [('ACLineStatus', ctypes.c_byte), ('BatteryFlag', ctypes.c_byte),
                        ('BatteryLifePercent', ctypes.c_byte), ('Reserved1', ctypes.c_byte),
                        ('BatteryLifeTime', ctypes.c_ulong),
                        ('BatteryFullLifeTime', ctypes.c_ulong)]

        sps = _SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            return 'unknown'
        return {0: 'battery', 1: 'ac'}.get(sps.ACLineStatus, 'unknown')
    except Exception:
        return 'unknown'


# ---- OCR 组件可用性 ----

def _pkg_exists(name: str) -> bool:
    """检查包是否可被找到（按文件判断，不 import，避免连带 import onnxruntime 提前锁定后端）。"""
    roots = [modules_dir(), dml_modules_dir()]
    if getattr(sys, 'frozen', False):
        roots.append(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))
    roots.append(os.path.abspath(
        os.path.join(os.path.dirname(sys.executable), '..', 'Lib', 'site-packages')))
    return any(os.path.isdir(os.path.join(r, name)) for r in roots)


def ocr_available() -> tuple[bool, str]:
    """检查 OCR 组件是否就绪，返回 (是否可用, 不可用原因)。纯文件检测。"""
    if _pkg_exists('rapidocr') and _pkg_exists('cv2') and _pkg_exists('numpy'):
        return True, ""
    return False, _NOT_INSTALLED


# ---- 各后端可用性 ----

def _ort_cuda_capable() -> bool:
    """内置的 onnxruntime 是否含 CUDA provider（按文件判断）。"""
    roots = []
    if getattr(sys, 'frozen', False):
        roots.append(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)))
    roots.append(os.path.abspath(
        os.path.join(os.path.dirname(sys.executable), '..', 'Lib', 'site-packages')))
    rel = os.path.join('onnxruntime', 'capi', 'onnxruntime_providers_cuda.dll')
    return any(os.path.exists(os.path.join(r, rel)) for r in roots)


def _cuda_installed() -> bool:
    """CUDA provider 与 cuDNN 文件是否已安装（不代表 provider 一定能加载）。"""
    return (_ort_cuda_capable()
            and any(os.path.exists(os.path.join(d, 'cudnn64_9.dll'))
                    for d in _candidate_dll_dirs()))


def _directml_installed() -> bool:
    """DirectML 加速包是否已安装（不提前导入 onnxruntime）。"""
    if platform.system() != 'Windows':
        return False
    try:
        build = int(platform.version().split('.')[-1])
        if build < 18362:  # DirectML 最低要求：Windows 10 1903
            return False
    except (TypeError, ValueError):
        return False
    return os.path.isdir(os.path.join(dml_modules_dir(), 'onnxruntime'))


def _loaded_providers() -> list[str]:
    """返回当前进程真正加载成功的 ONNX Runtime providers。"""
    try:
        import onnxruntime as ort
        return ort.get_available_providers()
    except Exception:
        return []


def cuda_available() -> bool:
    """CUDA 是否可用；ORT 已加载时以真实 provider 为准。"""
    if 'onnxruntime' in sys.modules:
        return 'CUDAExecutionProvider' in _loaded_providers()
    return _cuda_installed()


def directml_available() -> bool:
    """DirectML 是否可用；ORT 已加载时以真实 provider 为准。"""
    if 'onnxruntime' in sys.modules:
        return 'DmlExecutionProvider' in _loaded_providers()
    return _directml_installed()


def coreml_available() -> bool:
    """CoreML 加速是否可用（macOS 官方 onnxruntime 自带 CoreML EP）。"""
    if platform.system() != 'Darwin':
        return False
    _use_modules_dir(modules_dir())
    try:
        import onnxruntime as ort  # macOS 无互斥 flavor，直接 import 是安全的
        return 'CoreMLExecutionProvider' in ort.get_available_providers()
    except Exception:
        return False


def _backend_from_loaded_ort() -> str:
    """onnxruntime 已被加载时，基于已加载的 flavor 选最优后端。"""
    provs = _loaded_providers()
    if 'DmlExecutionProvider' in provs:
        return 'directml'
    if 'CUDAExecutionProvider' in provs:
        return 'cuda'
    if 'CoreMLExecutionProvider' in provs:
        return 'coreml'
    return 'cpu'


def best_backend() -> str:
    """开始任务时按当前状况选最优后端：cuda / directml / coreml / cpu。

    插电时优先 CUDA（独显性能最高）；离电且装有 DirectML 时改走 DirectML——
    DirectML 默认使用当前显示输出 GPU，独显直连用独显、混合输出用核显，更省电。
    """
    if _engine is not None:
        return _backend_from_loaded_ort()  # onnxruntime flavor 已锁定
    if 'onnxruntime' in sys.modules:
        # 其他模块可能先导入 ORT；CUDA provider 创建会话前仍需注册运行库目录。
        if _cuda_installed():
            _setup_cuda_dlls()
        return _backend_from_loaded_ort()
    cuda, dml = _cuda_installed(), _directml_installed()
    if cuda and dml:
        preferred = 'cuda' if power_state() != 'battery' else 'directml'
    elif cuda:
        preferred = 'cuda'
    elif dml:
        preferred = 'directml'
    elif platform.system() == 'Darwin':
        preferred = 'coreml'
    else:
        preferred = 'cpu'

    # 文件存在不等于 provider 能加载。这里在界面展示后端前完成一次真实加载，
    # 避免 CPU 版覆盖 GPU 版或驱动/DLL 缺失时仍误报为 CUDA/DirectML。
    if preferred == 'directml':
        _use_modules_dir(dml_modules_dir())
    if preferred == 'cuda':
        _setup_cuda_dlls()
    _loaded_providers()
    return _backend_from_loaded_ort()


_BACKEND_NAMES = {
    'cuda': 'GPU (CUDA)',
    'directml': 'GPU (DirectML)',
    'coreml': 'GPU (CoreML)',
    'cpu': 'CPU',
}


def backend_name() -> str:
    """OCR 推理后端描述，用于界面展示。"""
    return _BACKEND_NAMES[_active_backend or best_backend()]


# ---- 一键安装 ----

_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')


def _patch_distlib_for_frozen() -> None:
    """打包后 pip 内的 distlib 无法定位 frozen 包的资源查找器，
    注册一个从 _internal/pip/_vendor/distlib/ 读文件的查找器（装 wheel 时要内嵌 w64.exe 等启动器）。"""
    if not getattr(sys, 'frozen', False):
        return
    try:
        from pip._vendor.distlib import resources as distlib_resources
    except ImportError:
        return
    base = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)),
                        'pip', '_vendor', 'distlib')
    if not os.path.isdir(base):
        return

    class _Resource:
        def __init__(self, name):
            self.name = name

        @property
        def bytes(self):
            with open(os.path.join(base, self.name), 'rb') as f:
                return f.read()

    class _Finder:
        def iterator(self, _name):
            return [_Resource(f) for f in os.listdir(base) if f.endswith('.exe')]

    distlib_resources._finder_cache['pip._vendor.distlib'] = _Finder()


def _run_pip(args: list[str], log_cb=None) -> int:
    """在进程内调用 pip（打包后无独立 python 可用）。log_cb 逐行收到日志。"""
    _patch_distlib_for_frozen()
    from pip._internal.cli.main import main as pip_main

    class _Writer:
        def __init__(self):
            self._buf = ''

        def write(self, s):
            self._buf += s
            while True:
                cuts = [i for i in (self._buf.find('\n'), self._buf.find('\r')) if i >= 0]
                if not cuts:
                    break
                i = min(cuts)
                line = _ANSI_RE.sub('', self._buf[:i]).strip()
                self._buf = self._buf[i + 1:]
                if line and log_cb:
                    log_cb(line)

        def flush(self):
            pass

    writer = _Writer()
    with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
        return pip_main(args)


def accel_offers() -> list[tuple[str, str]]:
    """当前机器可安装的加速方案列表 [(方案 key, 按钮说明)]，可多个（CUDA 与 DirectML 互存）。

    key: 'cuda'（NVIDIA）/ 'directml'（AMD·Intel·高通等 Windows 显卡）。
    macOS 的 CoreML 无需安装；海思无可装方案，均不出现在这里。
    """
    offers: list[tuple[str, str]] = []
    if platform.system() != 'Windows':
        return offers
    if gpu_kind() == 'hisilicon':
        return offers
    if has_nvidia_gpu() and not _cuda_installed():
        offers.append(('cuda', '安装 NVIDIA CUDA 加速（约 1.1GB）'))
    if gpu_names() and not _directml_installed():
        # 任何 DX12 显卡（含 NVIDIA 双显本）都可装 DirectML：离电/混合输出时使用
        offers.append(('directml', '安装 DirectML 加速（AMD/Intel/高通 · 约 250MB）'))
    return offers


def install_gpu(kind: str, log_cb=None) -> str:
    """一键安装指定加速包。kind: 'cuda' / 'directml'。

    log_cb 接收 pip 日志行；失败抛 RuntimeError。返回完成提示语。
    """
    if kind == 'cuda':
        packages, target = CUDA_PACKAGES, modules_dir()
    elif kind == 'directml':
        packages, target = DML_PACKAGES, dml_modules_dir()
    else:
        raise RuntimeError(f"未知加速方案：{kind}")
    os.makedirs(target, exist_ok=True)
    base_args = ['install', '--disable-pip-version-check', '--no-warn-script-location',
                 '--upgrade', '--target', target]
    for index in PIP_INDEXES:
        if log_cb:
            log_cb(f"使用源 {index} 下载安装…")
        loaded_before_install = 'onnxruntime' in sys.modules
        if _run_pip(base_args + ['-i', index] + packages, log_cb) == 0:
            importlib.invalidate_caches()
            # onnxruntime 已在本进程加载时无法更换 flavor，新后端需重启验证。
            if loaded_before_install:
                return "加速安装完成（重启应用后生效）"
            if best_backend() == kind:
                return "加速安装完成"
            if kind == 'cuda':
                return "安装完成，但未检测到可用的 CUDA（需要较新驱动），将继续使用现有后端"
            return "安装完成，但未检测到可用的 DirectML，将继续使用现有后端"
    raise RuntimeError("下载安装失败，请检查网络连接后重试")


# ---- OCR 引擎与页面处理 ----

def get_engine():
    """RapidOCR 引擎单例。首次调用（开始任务时）按当时状况选择后端并加载模型。"""
    global _engine, _active_backend
    with _engine_lock:
        if _engine is None:
            ok, reason = ocr_available()
            if not ok:
                raise RuntimeError(reason)
            backend = best_backend()
            from rapidocr import RapidOCR
            provider_key = {
                'cuda': 'EngineConfig.onnxruntime.use_cuda',
                'directml': 'EngineConfig.onnxruntime.use_dml',
                'coreml': 'EngineConfig.onnxruntime.use_coreml',
            }.get(backend)
            params = {provider_key: True} if provider_key else None
            _engine = RapidOCR(params=params)
            # get_available_providers() 仅表示编译进包，依赖 DLL 缺失时创建会话仍会
            # 回退 CPU；以实际会话采用的首选 provider 作为最终后端。
            try:
                session = _engine.text_det.session.session
                first_provider = session.get_providers()[0]
            except (AttributeError, IndexError):
                first_provider = 'CPUExecutionProvider'
            _active_backend = {
                'CUDAExecutionProvider': 'cuda',
                'DmlExecutionProvider': 'directml',
                'CoreMLExecutionProvider': 'coreml',
            }.get(first_provider, 'cpu')
    return _engine


def page_image_array(doc: fitz.Document, page: fitz.Page, include_annots: bool = False):
    """取页面图像：优先直接用整页内嵌扫描图（无损且快），否则按 200 DPI 渲染。

    include_annots=False 时渲染不含批注/留言（手写墨迹不参与识别）；
    True 时把注释一并渲染进图像（内嵌扫描图路径不含注释，有注释时强制渲染合成）。

    返回 (numpy 数组, 宽, 高)。
    """
    import numpy as np
    pix = None
    imgs = page.get_images()
    if len(imgs) == 1 and not (include_annots and page.first_annot):
        pix = fitz.Pixmap(doc, imgs[0][0])
        if pix.width < 800 or pix.height < 800:
            pix = None  # 内嵌图太小，不像整页扫描，改用渲染
    if pix is None:
        pix = page.get_pixmap(dpi=200, alpha=False, annots=include_annots)
    if pix.colorspace and pix.colorspace.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return arr, pix.width, pix.height


def ocr_page(doc: fitz.Document, page: fitz.Page, include_annots: bool = False) -> list[dict]:
    """OCR 单页，返回 [{'text', 'rect', 'size'}]，坐标为 PDF 页面坐标。

    include_annots=False（默认）：不识别用户加的批注/留言墨迹；
    True：批注墨迹一并渲染识别。
    """
    engine = get_engine()
    arr, iw, ih = page_image_array(doc, page, include_annots)
    result = engine(arr)
    lines: list[dict] = []
    if result.boxes is None or result.txts is None or result.scores is None:
        return lines
    sx = page.rect.width / iw
    sy = page.rect.height / ih
    for box, text, _score in zip(result.boxes, result.txts, result.scores):
        text = text.strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        rect = fitz.Rect(min(xs) * sx, min(ys) * sy, max(xs) * sx, max(ys) * sy)
        lines.append({"text": text, "rect": rect, "size": max(rect.height * 0.9, 4)})
    return lines


def write_text_layer(page: fitz.Page, lines: list[dict]) -> None:
    """把 OCR 行写入页面为不可见文字（render_mode=3），页面外观不变。"""
    for line in lines:
        rect = line["rect"]
        # china-s 为 PyMuPDF 内置简中字体；文本框放不下时退化为按基线插入
        rc = page.insert_textbox(rect, line["text"], fontname="china-s",
                                 fontsize=line["size"], render_mode=3)
        if rc < 0:
            page.insert_text((rect.x0, rect.y1 * 0.98), line["text"],
                             fontname="china-s", fontsize=line["size"],
                             render_mode=3)


def note_annot_lines(page: fitz.Page) -> list[dict]:
    """把页面上的留言（Text 注释）内容转为隐形文字行，写入文字层后可搜索。"""
    lines: list[dict] = []
    for annot in page.annots(types=(fitz.PDF_ANNOT_TEXT,)) or []:
        content = (annot.info.get("content") or "").strip()
        if not content:
            continue
        r = annot.rect
        # 便签图标很小，文字框向右下延展以容纳内容
        rect = fitz.Rect(r.x0, r.y0, min(r.x0 + 200, page.rect.x1),
                         min(r.y1 + 14 * (content.count("\n") + 1), page.rect.y1))
        lines.append({"text": content, "rect": rect, "size": 9})
    return lines


def ocr_pdf(pdf_path: str, out_path: str, include_annots: bool = False,
            progress_cb=None, cancel_check=None) -> str | None:
    """为整个 PDF 添加 OCR 文字层并另存。已有文字的页自动跳过。

    include_annots=False（默认）：不识别用户加的批注/留言（手写墨迹不参与识别）；
    True：批注墨迹一并渲染识别，留言文字写入隐形文字层（可搜索、可复制）。

    返回输出路径；被取消时返回 None（不生成半成品文件）。
    """
    doc = fitz.open(pdf_path)
    total = doc.page_count
    cancelled = False
    try:
        for i in range(total):
            if cancel_check and cancel_check():
                cancelled = True
                break
            page = doc.load_page(i)
            if not page.get_text().strip():
                lines = ocr_page(doc, page, include_annots=include_annots)
                if include_annots:
                    lines += note_annot_lines(page)
                write_text_layer(page, lines)
            if progress_cb:
                progress_cb(i + 1, total)
        if cancelled:
            return None
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        doc.save(out_path, garbage=3, deflate=True)
    finally:
        doc.close()
    return out_path
