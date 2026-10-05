import os
import platform
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.main_window import MacMainWindow, MainWindow


@unittest.skipUnless(platform.system() == "Darwin", "macOS-only window shell")
class MacMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        if hasattr(self.window.reader_page, "stop_workers"):
            self.window.reader_page.stop_workers()
        self.window.deleteLater()

    def test_uses_native_mac_window_with_all_pages(self):
        self.assertIsInstance(self.window, MacMainWindow)
        self.assertEqual(self.window.sidebar_list.count(), 7)
        self.assertEqual(self.window.content_stack.count(), 7)
        self.assertTrue(self.window.sidebar_action.isChecked())
        self.assertEqual(self.window.sidebar.property("macMaterial"), "sidebar")
        self.assertEqual(self.window.content_stack.property("macMaterial"), "content")
        self.assertFalse(
            self.window.sidebar.testAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(self.window.sidebar_list.item(0).sizeHint().height(), 42)

    def test_route_navigation_changes_sidebar_and_content_together(self):
        self.window._navigate("ocrPage")
        shell = self.window._page_shells["ocr_page"]
        self.assertIs(self.window.content_stack.currentWidget(), shell)
        self.assertIs(shell.layout().itemAt(0).widget(), self.window.ocr_page)
        self.assertEqual(
            self.window.sidebar_list.currentItem().data(Qt.ItemDataRole.UserRole),
            "ocrPage",
        )


if __name__ == "__main__":
    unittest.main()
