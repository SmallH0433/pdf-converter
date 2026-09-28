import os
import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator, setTheme, Theme

from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF 转换工具")
    app.installTranslator(FluentTranslator())
    setTheme(Theme.AUTO)

    window = MainWindow()
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
