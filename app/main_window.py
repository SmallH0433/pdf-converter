"""平台主窗口。

Windows/Linux 保留 FluentWindow；macOS 使用原生 QMainWindow 标题栏、菜单栏和
带文字侧边栏，使红黄绿窗口控件、键盘快捷键、字体与系统外观遵循平台习惯。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
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

from .macos_ui import IS_MACOS
from .pages.bookmark_page import BookmarkPage
from .pages.convert_page import ConvertPage
from .pages.extract_page import ExtractPage
from .pages.home_page import HomePage
from .pages.img2pdf_page import Img2PdfPage
from .pages.ocr_page import OcrPage
from .pages.reader_page import ReaderPage


PAGE_SPECS = (
    ("homePage", "home_page", HomePage, FIF.HOME, "首页"),
    ("readerPage", "reader_page", ReaderPage, FIF.DOCUMENT, "阅读器"),
    ("convertPage", "convert_page", ConvertPage, FIF.PHOTO, "PDF 转图片"),
    ("extractPage", "extract_page", ExtractPage, FIF.CUT, "页码节选"),
    ("bookmarkPage", "bookmark_page", BookmarkPage, FIF.TAG, "书签生成"),
    ("img2pdfPage", "img2pdf_page", Img2PdfPage, FIF.ALBUM, "图片转 PDF"),
    ("ocrPage", "ocr_page", OcrPage, FIF.SEARCH, "PDF OCR"),
)


def _create_pages(window):
    for _route, attribute, page_type, _icon, _title in PAGE_SPECS:
        setattr(window, attribute, page_type(window))


def _route_widget(window, route_key: str):
    for route, attribute, _page_type, _icon, _title in PAGE_SPECS:
        if route == route_key:
            return getattr(window, attribute)
    return None


def _handle_close(window, event):
    if window.reader_page.confirm_discard():
        window.reader_page.stop_workers()
        event.accept()
    else:
        event.ignore()


class FluentMainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 转换工具")
        self.resize(1080, 760)

        _create_pages(self)

        self.addSubInterface(self.home_page, FIF.HOME, "首页")
        self.addSubInterface(self.reader_page, FIF.DOCUMENT, "阅读器")
        self.addSubInterface(self.convert_page, FIF.PHOTO, "PDF 转图片")
        self.addSubInterface(self.extract_page, FIF.CUT, "页码节选")
        self.addSubInterface(self.bookmark_page, FIF.TAG, "书签生成")
        self.addSubInterface(self.img2pdf_page, FIF.ALBUM, "图片转 PDF")
        self.addSubInterface(self.ocr_page, FIF.SEARCH, "PDF OCR")

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
        widget = _route_widget(self, route_key)
        if widget:
            self.switchTo(widget)

    @staticmethod
    def _toggle_theme():
        setTheme(Theme.LIGHT if isDarkTheme() else Theme.DARK)

    def closeEvent(self, e):
        _handle_close(self, e)

    def open_pdf_in_reader(self, path: str):
        """从「打开方式」等外部入口打开 PDF：切到阅读器并加载。"""
        self.switchTo(self.reader_page)
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
        self._pages = [getattr(self, spec[1]) for spec in PAGE_SPECS]

        central = QWidget(self)
        central.setObjectName("macCentralWidget")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame(central)
        self.sidebar.setObjectName("macSidebar")
        self.sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 14)
        sidebar_layout.setSpacing(8)

        sidebar_title = QLabel("PDF 工具", self.sidebar)
        sidebar_title.setObjectName("macSidebarTitle")
        sidebar_layout.addWidget(sidebar_title)

        section_label = QLabel("功能", self.sidebar)
        section_label.setObjectName("macSidebarSection")
        sidebar_layout.addWidget(section_label)

        self.sidebar_list = QListWidget(self.sidebar)
        self.sidebar_list.setObjectName("macSidebarList")
        self.sidebar_list.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_list.setIconSize(QSize(19, 19))
        self.sidebar_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for route, _attribute, _page_type, icon, title in PAGE_SPECS:
            item = QListWidgetItem(icon.icon(), title)
            item.setData(Qt.ItemDataRole.UserRole, route)
            item.setSizeHint(QSize(190, 38))
            self.sidebar_list.addItem(item)
        sidebar_layout.addWidget(self.sidebar_list, 1)

        system_label = QLabel("跟随系统外观", self.sidebar)
        system_label.setObjectName("macSidebarFooter")
        sidebar_layout.addWidget(system_label)

        self.content_stack = QStackedWidget(central)
        self.content_stack.setObjectName("macContentStack")
        for page in self._pages:
            self.content_stack.addWidget(page)

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
        for page in self._pages:
            layout = page.layout()
            if layout is not None and page is not self.home_page:
                layout.setContentsMargins(30, 24, 30, 28)
                layout.setSpacing(12)
            for card in page.findChildren(CardWidget):
                card.setBorderRadius(12)

        for page in (self.convert_page, self.extract_page, self.bookmark_page,
                     self.img2pdf_page, self.ocr_page):
            labels = page.findChildren(StrongBodyLabel)
            if labels:
                labels[0].setObjectName("macPageTitle")
                font = QFont(labels[0].font())
                font.setPointSize(20)
                font.setWeight(QFont.Weight.DemiBold)
                labels[0].setFont(font)

    def _apply_appearance(self, *_args):
        dark = isDarkTheme()
        sidebar = "#242426" if dark else "#ECECEE"
        content = "#1C1C1E" if dark else "#F5F5F7"
        border = "#3A3A3C" if dark else "#D1D1D6"
        text = "#F5F5F7" if dark else "#1D1D1F"
        secondary = "#A1A1A6" if dark else "#6E6E73"
        hover = "#353537" if dark else "#E1E1E4"
        selected = "#3A3A3C" if dark else "#D8D8DC"
        self.setStyleSheet(f"""
            QMainWindow#macMainWindow {{ background: {content}; }}
            QWidget#macCentralWidget, QStackedWidget#macContentStack {{
                background: {content};
            }}
            QFrame#macSidebar {{
                background: {sidebar};
                border: none;
                border-right: 1px solid {border};
            }}
            QLabel#macSidebarTitle {{
                color: {text};
                font-size: 15px;
                font-weight: 600;
                padding: 2px 8px 8px 8px;
            }}
            QLabel#macSidebarSection {{
                color: {secondary};
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px 0 8px;
            }}
            QLabel#macSidebarFooter {{
                color: {secondary};
                font-size: 11px;
                padding: 6px 8px;
            }}
            QListWidget#macSidebarList {{
                background: transparent;
                border: none;
                outline: none;
                color: {text};
                font-size: 13px;
            }}
            QListWidget#macSidebarList::item {{
                border: none;
                border-radius: 7px;
                padding: 0 10px;
                margin: 1px 0;
            }}
            QListWidget#macSidebarList::item:hover {{ background: {hover}; }}
            QListWidget#macSidebarList::item:selected {{
                background: {selected};
                color: {text};
            }}
        """)

    def _show_page(self, row: int):
        if 0 <= row < self.content_stack.count():
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
        self._navigate("readerPage")
        self.reader_page.load_pdf(path)


MainWindow = MacMainWindow if IS_MACOS else FluentMainWindow
