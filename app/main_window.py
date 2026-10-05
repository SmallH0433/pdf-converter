"""平台主窗口。

Windows/Linux 保留 FluentWindow；macOS 使用原生 QMainWindow 标题栏、菜单栏和
带文字侧边栏，使红黄绿窗口控件、键盘快捷键、字体与系统外观遵循平台习惯。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    CardWidget,
    FluentIcon as FIF,
    FluentWindow,
    NavigationItemPosition,
    StrongBodyLabel,
    Theme,
    isDarkTheme,
    qconfig,
    setTheme,
)

import importlib

from .macos_ui import IS_MACOS, configure_liquid_glass_window

# 页面类延迟导入：启动时只实例化首页，其余页面首次进入时才创建，
# 避免阅读器/OCR/书签等重依赖（PyMuPDF、numpy 等）拖慢启动。
PAGE_SPECS = (
    ("homePage", "home_page", "app.pages.home_page:HomePage", FIF.HOME, "首页", True),
    ("readerPage", "reader_page", "app.pages.reader_page:ReaderPage", FIF.DOCUMENT, "阅读器", False),
    ("convertPage", "convert_page", "app.pages.convert_page:ConvertPage", FIF.PHOTO, "PDF 转图片", False),
    ("extractPage", "extract_page", "app.pages.extract_page:ExtractPage", FIF.CUT, "页码节选", False),
    ("bookmarkPage", "bookmark_page", "app.pages.bookmark_page:BookmarkPage", FIF.TAG, "目录/书签自动生成", False),
    ("img2pdfPage", "img2pdf_page", "app.pages.img2pdf_page:Img2PdfPage", FIF.ALBUM, "图片转 PDF", False),
    ("ocrPage", "ocr_page", "app.pages.ocr_page:OcrPage", FIF.SEARCH, "PDF OCR", False),
)


def _lazy_page(window, stack, row_or_widget):  # noqa: C901
    """占位页首次显示时，把真实页面创建为它的子控件（占位壳不动，导航映射不失效）。"""
    if isinstance(row_or_widget, int):
        index = row_or_widget
    else:
        index = stack.indexOf(row_or_widget)
    if index < 0 or index >= len(PAGE_SPECS):
        return
    _route, attribute, spec, _icon, _title, eager = PAGE_SPECS[index]
    if eager:
        return
    shell = stack.widget(index)
    if shell is None or shell.layout() is not None:
        return
    module_name, class_name = spec.split(":")
    page_type = getattr(importlib.import_module(module_name), class_name)
    page = page_type(window)
    setattr(window, attribute, page)
    layout = QVBoxLayout(shell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(page)
    if hasattr(window, "_polish_page"):
        window._polish_page(page)


def _create_pages(window, stack=None):
    """首页立即创建；其余页面用占位 widget 顶替，首次进入时才真正实例化。"""
    window._page_shells = {}
    for _route, attribute, _spec, _icon, _title, eager in PAGE_SPECS:
        if eager:
            module_name, class_name = _spec.split(":")
            page_type = getattr(importlib.import_module(module_name), class_name)
            setattr(window, attribute, page_type(window))
        else:
            # 占位壳沿用页面的 objectName，导航 routeKey 保持有效
            placeholder = QWidget()
            placeholder.setObjectName(_route)
            setattr(window, attribute, placeholder)
            window._page_shells[attribute] = placeholder


def _handle_close(window, event):
    reader = window.reader_page
    if hasattr(reader, "confirm_discard"):
        if reader.confirm_discard():
            reader.stop_workers()
            event.accept()
        else:
            event.ignore()
    else:
        event.accept()


class FluentMainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 转换工具")
        self.resize(1080, 760)

        _create_pages(self)
        for _route, attribute, _spec, icon, title, _eager in PAGE_SPECS:
            self.addSubInterface(getattr(self, attribute), icon, title)
        self.stackedWidget.currentChanged.connect(
            lambda index: _lazy_page(self, self.stackedWidget, index))

        self.navigationInterface.addItem(
            routeKey="themeToggle",
            icon=FIF.CONSTRACT,
            text="切换主题",
            onClick=self._toggle_theme,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )

        self.home_page.navigate.connect(self._navigate)
        self.stackedWidget.setCurrentWidget(self.home_page)

    def _navigate(self, route_key: str):
        for row, (route, attribute, _s, _i, _t, _e) in enumerate(PAGE_SPECS):
            if route == route_key:
                _lazy_page(self, self.stackedWidget, row)
                # 导航永远切换到占位壳（首次切换时壳内已填充真实页面）
                self.switchTo(self._page_shells.get(attribute, getattr(self, attribute)))
                return

    @staticmethod
    def _toggle_theme():
        setTheme(Theme.LIGHT if isDarkTheme() else Theme.DARK)

    def closeEvent(self, e):
        _handle_close(self, e)

    def open_pdf_in_reader(self, path: str):
        """从「打开方式」等外部入口打开 PDF：切到阅读器并加载。"""
        row = next(i for i, s in enumerate(PAGE_SPECS) if s[0] == "readerPage")
        _lazy_page(self, self.stackedWidget, row)
        self.switchTo(self._page_shells["reader_page"])
        self.reader_page.load_pdf(path)


class MacMainWindow(QMainWindow):
    """macOS window shell using native chrome and Apple-style navigation."""

    def __init__(self):
        super().__init__()
        self.setObjectName("macMainWindow")
        self.setWindowTitle("PDF 转换工具")
        self.resize(1180, 800)
        self.setMinimumSize(940, 660)
        self.setUnifiedTitleAndToolBarOnMac(True)

        _create_pages(self)

        central = QWidget(self)
        central.setObjectName("macCentralWidget")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame(central)
        self.sidebar.setObjectName("macSidebar")
        self.sidebar.setProperty("macMaterial", "sidebar")
        # Keep the Qt sidebar opaque.  The native AppKit titlebar is configured
        # separately; a translucent Qt backing store can become invisible in
        # frozen macOS builds when combined with full-size content view.
        self.sidebar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.sidebar.setAutoFillBackground(True)
        self.sidebar.setFixedWidth(236)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 14)
        sidebar_layout.setSpacing(10)

        sidebar_title = QLabel("PDF 工具", self.sidebar)
        sidebar_title.setObjectName("macSidebarTitle")
        sidebar_layout.addWidget(sidebar_title)

        section_label = QLabel("功能", self.sidebar)
        section_label.setObjectName("macSidebarSection")
        sidebar_layout.addWidget(section_label)

        self.sidebar_list = QListWidget(self.sidebar)
        self.sidebar_list.setObjectName("macSidebarList")
        self.sidebar_list.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_list.setIconSize(QSize(20, 20))
        self.sidebar_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for route, _attribute, _page_type, icon, title, _eager in PAGE_SPECS:
            item = QListWidgetItem(icon.icon(), title)
            item.setData(Qt.ItemDataRole.UserRole, route)
            item.setSizeHint(QSize(204, 42))
            self.sidebar_list.addItem(item)
        sidebar_layout.addWidget(self.sidebar_list, 1)

        system_label = QLabel("跟随系统外观", self.sidebar)
        system_label.setObjectName("macSidebarFooter")
        sidebar_layout.addWidget(system_label)

        self.content_stack = QStackedWidget(central)
        self.content_stack.setObjectName("macContentStack")
        self.content_stack.setProperty("macMaterial", "content")
        for _route, attribute, _spec, _icon, _title, _eager in PAGE_SPECS:
            self.content_stack.addWidget(getattr(self, attribute))

        root.addWidget(self.sidebar)
        root.addWidget(self.content_stack, 1)
        self.setCentralWidget(central)

        self.sidebar_list.currentRowChanged.connect(self._show_page)
        self.home_page.navigate.connect(self._navigate)
        self.sidebar_list.setCurrentRow(0)

        self._create_native_menus()
        self._polish_pages()
        self._apply_appearance()
        qconfig.themeChanged.connect(self._apply_appearance)
        # Native NSViews exist only after Qt has completed window creation.
        QTimer.singleShot(
            0, lambda: configure_liquid_glass_window(self, self.sidebar))

    def _create_native_menus(self):
        file_menu = self.menuBar().addMenu("文件")
        open_action = QAction("打开 PDF…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_pdf_dialog)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        close_action = QAction("关闭窗口", self)
        close_action.setShortcut(QKeySequence.StandardKey.Close)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

        view_menu = self.menuBar().addMenu("显示")
        self.sidebar_action = QAction("显示侧边栏", self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.setShortcut(QKeySequence("Ctrl+Meta+S"))
        self.sidebar_action.toggled.connect(self.sidebar.setVisible)
        view_menu.addAction(self.sidebar_action)

    def _polish_pages(self):
        self._polish_page(self.home_page)

    def _polish_page(self, page):
        """对单个真实页面套用 macOS 外观（占位页跳过；懒加载页面在创建时调用）。"""
        layout = page.layout()
        if layout is not None and page is not self.home_page:
            layout.setContentsMargins(34, 28, 34, 32)
            layout.setSpacing(14)
        for card in page.findChildren(CardWidget):
            card.setBorderRadius(18)
        if page is not self.home_page:
            labels = page.findChildren(StrongBodyLabel)
            if labels:
                labels[0].setObjectName("macPageTitle")
                font = QFont(labels[0].font())
                font.setPointSize(22)
                font.setWeight(QFont.Weight.DemiBold)
                labels[0].setFont(font)

    def _apply_appearance(self, *_args):
        dark = isDarkTheme()
        sidebar = "#2C2C2E" if dark else "#ECECEE"
        content = "#18181A" if dark else "#F5F5F7"
        card = "rgba(255, 255, 255, 16)" if dark else "rgba(255, 255, 255, 210)"
        card_hover = "rgba(255, 255, 255, 24)" if dark else "rgba(255, 255, 255, 242)"
        border = "rgba(255, 255, 255, 24)" if dark else "rgba(0, 0, 0, 20)"
        text = "#F5F5F7" if dark else "#1D1D1F"
        secondary = "#A1A1A6" if dark else "#6E6E73"
        hover = "rgba(255, 255, 255, 18)" if dark else "rgba(255, 255, 255, 125)"
        selected = "rgba(255, 255, 255, 36)" if dark else "rgba(255, 255, 255, 205)"
        self.setStyleSheet(f"""
            QMainWindow#macMainWindow, QWidget#macCentralWidget {{
                background: transparent;
            }}
            QStackedWidget#macContentStack {{
                background: {content};
            }}
            QFrame#macSidebar {{
                background: {sidebar};
                border: none;
                border-right: 1px solid {border};
            }}
            QLabel#macSidebarTitle {{
                color: {text};
                font-size: 17px;
                font-weight: 600;
                padding: 4px 10px 8px 10px;
            }}
            QLabel#macSidebarSection {{
                color: {secondary};
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px 0 10px;
            }}
            QLabel#macSidebarFooter {{
                color: {secondary};
                font-size: 11px;
                padding: 8px 10px;
            }}
            QListWidget#macSidebarList {{
                background: transparent;
                border: none;
                outline: none;
                color: {text};
                font-size: 14px;
            }}
            QListWidget#macSidebarList::item {{
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 0 12px;
                margin: 2px 0;
            }}
            QListWidget#macSidebarList::item:hover {{ background: {hover}; }}
            QListWidget#macSidebarList::item:selected {{
                background: {selected};
                border: 1px solid {border};
                color: {text};
            }}
            CardWidget {{
                background: {card};
                border: 1px solid {border};
                border-radius: 18px;
            }}
            CardWidget:hover {{ background: {card_hover}; }}
            StrongBodyLabel#macPageTitle {{
                color: {text};
                padding-bottom: 4px;
            }}
        """)

    def _show_page(self, row: int):
        if 0 <= row < self.content_stack.count():
            _lazy_page(self, self.content_stack, row)
            self.content_stack.setCurrentIndex(row)

    def _navigate(self, route_key: str):
        for row in range(self.sidebar_list.count()):
            if self.sidebar_list.item(row).data(Qt.ItemDataRole.UserRole) == route_key:
                self.sidebar_list.setCurrentRow(row)
                return

    def _open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF 文件 (*.pdf)")
        if path:
            self.open_pdf_in_reader(path)

    def closeEvent(self, event):
        _handle_close(self, event)

    def open_pdf_in_reader(self, path: str):
        row = next(i for i, s in enumerate(PAGE_SPECS) if s[0] == "readerPage")
        _lazy_page(self, self.content_stack, row)
        self._navigate("readerPage")
        self.reader_page.load_pdf(path)


MainWindow = MacMainWindow if IS_MACOS else FluentMainWindow
