"""Send real Qt wheel events through the preview's event filters."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.pages.reader_page import ReaderPage


class ReaderWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = ReaderPage()
        self.page.resize(1600, 900)
        self.doc = fitz.open()
        for height in (1200, 1700, 300):
            self.doc.new_page(width=600, height=height)
        self.page._doc = self.doc
        self.page._fit_width = False
        self.page.canvas.zoom = 1.0
        for index in range(3):
            self.page.thumb_list.addItem(f"第 {index + 1} 页")
        self.page.show()
        self.app.processEvents()
        self.page._goto_page(0)
        self.app.processEvents()
        self.bar = self.page.scroll.verticalScrollBar()

    def tearDown(self):
        self.page.stop_workers()
        self.page.canvas.set_document(None)
        self.page._doc = None
        self.doc.close()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()

    def wheel(self, y=-120, *, x=0, target=None, pixels=None,
              modifiers=Qt.KeyboardModifier.NoModifier,
              buttons=Qt.MouseButton.NoButton,
              phase=Qt.ScrollPhase.NoScrollPhase):
        target = target if target is not None else self.page.scroll.viewport()
        pos = target.rect().center()
        event = QWheelEvent(
            QPointF(pos), QPointF(target.mapToGlobal(pos)),
            pixels if pixels is not None else QPoint(), QPoint(x, y),
            buttons, modifiers, phase, False,
        )
        QApplication.sendEvent(target, event)

    def test_wheel_scrolls_inside_the_page_before_turning(self):
        self.assertGreater(self.bar.maximum(), 0)
        self.bar.setValue(self.bar.maximum() // 2)
        previous = self.bar.value()
        self.wheel(target=self.page.canvas)
        QTest.qWait(450)  # Allow the existing smooth scrolling to complete.
        self.assertEqual(self.page._page_index, 0)
        self.assertGreater(self.bar.value(), previous)

    def test_down_at_bottom_opens_next_page_at_top(self):
        self.bar.setValue(self.bar.maximum())
        self.wheel(target=self.page.canvas)
        self.assertEqual(self.page._page_index, 1)
        self.assertEqual(self.page.page_edit.text(), "2")
        self.assertEqual(self.page.thumb_list.currentRow(), 1)
        self.assertEqual(self.bar.value(), self.bar.minimum())

    def test_up_at_top_opens_previous_page_at_its_bottom(self):
        self.page._goto_page(1)
        self.wheel(120)
        self.assertEqual(self.page._page_index, 0)
        self.assertGreater(self.bar.maximum(), 0)
        self.assertEqual(self.bar.value(), self.bar.maximum())
        self.app.processEvents()
        self.assertEqual(self.bar.value(), self.bar.maximum())

    def test_a_page_that_fits_can_turn_and_document_limits_are_respected(self):
        self.wheel(120)
        self.assertEqual(self.page._page_index, 0)
        self.page._goto_page(2)
        self.assertEqual(self.bar.maximum(), 0)
        self.wheel()
        self.assertEqual(self.page._page_index, 2)
        self.wheel(120)
        self.assertEqual(self.page._page_index, 1)
        self.assertEqual(self.bar.value(), self.bar.maximum())

    def test_high_resolution_wheel_accumulates_and_resets_on_direction_change(self):
        self.page._goto_page(2)
        for _ in range(3):
            self.wheel(30, target=self.page.canvas)
            self.assertEqual(self.page._page_index, 2)
        self.wheel(-30)
        self.wheel(30)
        self.assertEqual(self.page._page_index, 2)
        for _ in range(3):
            self.wheel(30)
        self.assertEqual(self.page._page_index, 1)

    def test_touchpad_pixels_turn_pages_but_momentum_does_not(self):
        self.page._goto_page(2)
        self.wheel(0, pixels=QPoint(0, 30))
        self.assertEqual(self.page._page_index, 2)
        self.wheel(0, pixels=QPoint(0, 30))
        self.assertEqual(self.page._page_index, 1)
        self.bar.setValue(self.bar.minimum())
        self.wheel(120, phase=Qt.ScrollPhase.ScrollMomentum)
        self.assertEqual(self.page._page_index, 1)

    def test_pixel_only_touchpad_events_scroll_within_the_page(self):
        self.bar.setValue(100)
        self.wheel(0, pixels=QPoint(0, -25), target=self.page.canvas)
        self.assertEqual(self.bar.value(), 125)
        self.assertEqual(self.page._page_index, 0)

    def test_horizontal_and_modified_wheel_do_not_turn_pages(self):
        self.page._goto_page(1)
        self.wheel(0, x=120)
        self.wheel(120, x=240)
        self.wheel(120, modifiers=Qt.KeyboardModifier.ControlModifier)
        self.wheel(120, modifiers=Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.page._page_index, 1)

    def test_wheel_during_drawing_does_not_move_or_clear_the_stroke(self):
        self.page.canvas._stroking = True
        self.page.canvas._stroke = [(20, 30, .6)]
        self.bar.setValue(self.bar.maximum())
        self.wheel(buttons=Qt.MouseButton.LeftButton, target=self.page.canvas)
        self.assertEqual(self.page._page_index, 0)
        self.assertEqual(self.bar.value(), self.bar.maximum())
        self.assertEqual(self.page.canvas._stroke, [(20, 30, .6)])

    def test_turning_preserves_zoom_and_unsaved_annotations(self):
        annot = self.doc[0].add_ink_annot([[(20, 30), (40, 50)]])
        annot.update()
        xref = annot.xref
        self.page._dirty = True
        self.page._zoom_by(.9)
        zoom = self.page.canvas.zoom
        self.bar.setValue(self.bar.maximum())
        self.wheel()
        self.wheel(120)
        self.assertEqual(self.page._page_index, 0)
        self.assertEqual(self.page.canvas.zoom, zoom)
        self.assertTrue(self.page._dirty)
        self.assertIn(xref, [item.xref for item in self.doc[0].annots()])


if __name__ == "__main__":
    unittest.main()
