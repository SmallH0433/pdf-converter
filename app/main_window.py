"""主窗口：FluentWindow + 导航 + 主题切换。"""
from __future__ import annotations

from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    NavigationItemPosition,
    Theme,
    isDarkTheme,
    setTheme,
)

from .pages.bookmark_page import BookmarkPage
from .pages.convert_page import ConvertPage
from .pages.extract_page import ExtractPage
from .pages.home_page import HomePage
from .pages.img2pdf_page import Img2PdfPage
from .pages.ocr_page import OcrPage


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 转换工具")
        self.resize(1080, 760)

        self.home_page = HomePage(self)
        self.convert_page = ConvertPage(self)
        self.extract_page = ExtractPage(self)
        self.bookmark_page = BookmarkPage(self)
        self.img2pdf_page = Img2PdfPage(self)
        self.ocr_page = OcrPage(self)

        self.addSubInterface(self.home_page, FIF.HOME, "首页")
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
        widget = {
            "convertPage": self.convert_page,
            "extractPage": self.extract_page,
            "bookmarkPage": self.bookmark_page,
            "img2pdfPage": self.img2pdf_page,
            "ocrPage": self.ocr_page,
        }.get(route_key)
        if widget:
            self.switchTo(widget)

    @staticmethod
    def _toggle_theme():
        setTheme(Theme.LIGHT if isDarkTheme() else Theme.DARK)
