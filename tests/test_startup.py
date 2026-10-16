"""Check startup isolation in a fresh interpreter and first-use navigation."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class StartupIsolationTests(unittest.TestCase):
    def test_home_does_not_load_document_or_ai_services(self):
        # Match the Windows bundle's exclusion of the unused optional blur
        # module. Block heavy services so an accidental startup import fails.
        script = '''
import importlib.abc
import sys

class BlockHeavyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "qfluentwidgets.common.image_utils":
            raise ModuleNotFoundError(fullname)
        if fullname.split(".")[0] in {
            "fitz", "pymupdf", "numpy", "cv2", "onnxruntime", "rapidocr"
        } or fullname in {"app.core.workers", "app.core.llm_bookmarks"}:
            raise AssertionError("Startup loaded " + fullname)

sys.meta_path.insert(0, BlockHeavyImports())
from PySide6.QtWidgets import QApplication
from app.main_window import FluentMainWindow

app = QApplication([])
window = FluentMainWindow()
window.show()
app.processEvents()
assert window.stackedWidget.count() == 7
assert window.stackedWidget.currentWidget() is window.home_page
assert all(shell.layout() is None for shell in window._page_shells.values())
window.close()
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ.copy(), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_importing_entry_point_does_not_load_gui(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import run, sys; assert 'PySide6' not in sys.modules; "
             "assert 'qfluentwidgets' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class LazyNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.main_window import FluentMainWindow
        self.window = FluentMainWindow()
        self.window.stackedWidget.setAnimationEnabled(False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_all_routes_create_pages_once_and_keep_navigation_shell(self):
        from app.main_window import PAGE_SPECS
        from unittest.mock import patch

        with patch("app.core.ocr_service.gpu_names", return_value=[]), \
             patch("app.core.llm_bookmarks.list_local_models", return_value=[]):
            for route, attribute, _spec, _icon, _title, eager in PAGE_SPECS:
                with self.subTest(route=route):
                    self.window._navigate(route)
                    page = getattr(self.window, attribute)
                    if eager:
                        self.assertIs(self.window.stackedWidget.currentWidget(), page)
                        continue
                    shell = self.window._page_shells[attribute]
                    self.assertIs(self.window.stackedWidget.currentWidget(), shell)
                    self.assertIs(shell.layout().itemAt(0).widget(), page)
                    self.window._navigate("homePage")
                    # Exercise the sidebar path, which emits currentChanged.
                    self.window.switchTo(shell)
                    self.assertIs(getattr(self.window, attribute), page)
                    self.assertEqual(shell.layout().count(), 1)

    def test_external_pdf_opens_reader_from_a_fresh_window(self):
        import tempfile
        import fitz

        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sample.pdf")
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), "Startup test")
                doc.save(path)
            self.window.open_pdf_in_reader(path)
            self.assertEqual(self.window.reader_page._pdf_path, path)
            self.assertIs(self.window.stackedWidget.currentWidget(),
                          self.window._page_shells["reader_page"])
            self.window.close()
            self.window.reader_page._doc.close()
            self.window.reader_page._doc = None


if __name__ == "__main__":
    unittest.main()
