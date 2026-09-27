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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
