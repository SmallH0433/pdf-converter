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
        self.window.reader_page.stop_workers()
        self.window.deleteLater()

    def test_uses_native_mac_window_with_all_pages(self):
        self.assertIsInstance(self.window, MacMainWindow)
        self.assertEqual(self.window.sidebar_list.count(), 7)
        self.assertEqual(self.window.content_stack.count(), 7)
        self.assertTrue(self.window.sidebar_action.isChecked())

    def test_route_navigation_changes_sidebar_and_content_together(self):
        self.window._navigate("ocrPage")
        self.assertIs(self.window.content_stack.currentWidget(), self.window.ocr_page)
        self.assertEqual(
            self.window.sidebar_list.currentItem().data(Qt.ItemDataRole.UserRole),
            "ocrPage",
        )


if __name__ == "__main__":
    unittest.main()
