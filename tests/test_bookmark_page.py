import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.pages.bookmark_page import BookmarkPage


class BookmarkPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("app.pages.bookmark_page.ocr_service.ocr_available", return_value=(True, "")), \
             patch("app.pages.bookmark_page.llm_bookmarks.list_local_models", return_value=[]):
            self.page = BookmarkPage()
        self.page._total_pages = 12

    def tearDown(self):
        self.page.deleteLater()

    def test_ocr_and_llm_show_independent_progress_bars(self):
        self.page._show_detect_progress(use_ocr=True, use_llm=True)

        self.assertFalse(self.page.ocr_progress.isHidden())
        self.assertFalse(self.page.llm_progress.isHidden())
        self.assertTrue(self.page.progress.isHidden())

        self.page._update_ocr_progress(3, 12)
        self.page._update_llm_progress(2, 6)
        self.assertEqual(self.page.ocr_progress.value(), 3)
        self.assertEqual(self.page.llm_progress.value(), 2)

    def test_detected_results_are_checkable_and_editable(self):
        self.page._on_detected([
            {"level": 1, "title": "第一章", "page": 0},
            {"level": 1, "title": "第二章", "page": 4},
        ])
        first = self.page.tree.topLevelItem(0)

        self.assertEqual(first.checkState(0), Qt.CheckState.Unchecked)
        first.setText(0, "第一章（修订）")
        first.setText(1, "3")
        self.page.tree.topLevelItem(1).setText(2, "2")

        self.assertEqual(self.page._toc[0]["title"], "第一章（修订）")
        self.assertEqual(self.page._toc[0]["page"], 2)
        self.assertEqual(self.page._toc[1]["level"], 2)

    def test_checked_results_can_be_deleted_in_one_action(self):
        self.page._on_detected([
            {"level": 1, "title": "第一章", "page": 0},
            {"level": 1, "title": "第二章", "page": 4},
            {"level": 1, "title": "第三章", "page": 8},
        ])
        self.page.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
        self.page.tree.topLevelItem(2).setCheckState(0, Qt.CheckState.Checked)

        self.page._delete_selected()

        self.assertEqual([item["title"] for item in self.page._toc], ["第二章"])


if __name__ == "__main__":
    unittest.main()
