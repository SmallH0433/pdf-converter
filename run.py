import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator, setTheme, Theme

from app.main_window import MainWindow


def resource_path(*parts: str) -> Path:
    """返回开发环境或 PyInstaller 打包后的资源路径。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF 转换工具")
    app.setWindowIcon(
        QIcon(str(resource_path("assets", "branding", "pdf-converter.ico")))
    )
    app.installTranslator(FluentTranslator())
    setTheme(Theme.AUTO)

    window = MainWindow()
    window.setWindowIcon(app.windowIcon())
    window.show()

    # 从「打开方式」启动时，直接在阅读器中打开传入的 PDF
    pdfs = [a for a in sys.argv[1:]
            if a.lower().endswith(".pdf") and os.path.exists(a)]
    if pdfs:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: window.open_pdf_in_reader(pdfs[0]))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
