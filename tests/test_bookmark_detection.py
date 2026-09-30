import tempfile
import unittest
from pathlib import Path

import fitz

from app.core.pdf_service import detect_headings


BODY = (
    "This is ordinary body text used to establish the normal font size for the page. "
    "It should never be interpreted as a bookmark heading."
)


class BookmarkDetectionTests(unittest.TestCase):
    def _make_pdf(self, draw_pages) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        doc = fitz.open()
        for draw in draw_pages:
            page = doc.new_page(width=480, height=680)
            draw(page)
        doc.save(tmp.name)
        doc.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        return tmp.name

    @staticmethod
    def _body(page, y=130):
        page.insert_text((40, y), BODY, fontsize=10)
        page.insert_text((40, y + 18), BODY, fontsize=10)

    def test_section_keyword_accepts_compact_dotted_number(self):
        def first(page):
            page.insert_text((40, 80), "Section1.1 Foundations", fontsize=14)
            self._body(page)

        def second(page):
            page.insert_text((40, 80), "Section 1.2 Applications", fontsize=14)
            self._body(page)

        toc = detect_headings(self._make_pdf([first, second]), mode="numbering")

        self.assertEqual(
            [(item["level"], item["title"]) for item in toc],
            [(1, "Section1.1 Foundations"), (2, "Section 1.2 Applications")],
        )

    def test_split_numbered_heading_is_reassembled_from_visual_row(self):
        def page_with_heading(number, final_word):
            def draw(page):
                x = 40
                for text in (number, "Smart", "Bookmark", final_word):
                    page.insert_text((x, 80), text, fontsize=8)
                    x += fitz.get_text_length(text, fontsize=8) + 12
                self._body(page)
            return draw

        toc = detect_headings(
            self._make_pdf([
                page_with_heading("1.1", "Detection"),
                page_with_heading("1.2", "Filtering"),
            ]),
            mode="numbering",
        )

        self.assertEqual(
            [item["title"] for item in toc],
            ["1.1 Smart Bookmark Detection", "1.2 Smart Bookmark Filtering"],
        )

    def test_large_equations_are_not_font_based_headings(self):
        def draw(page):
            page.insert_text((40, 70), "Useful Introduction", fontsize=16)
            page.insert_text((40, 115), "VTH = VDD - 2V", fontsize=20)
            page.insert_text((40, 160), "y = mx + b", fontsize=18)
            page.insert_text((40, 205), "CLK2 + CLK3", fontsize=18)
            page.insert_text((40, 245), "1.1 V = IR", fontsize=14)
            page.insert_text((40, 280), "1.2 P = UI", fontsize=14)
            self._body(page, y=330)

        toc = detect_headings(self._make_pdf([draw]), mode="both")
        titles = [item["title"] for item in toc]

        self.assertIn("Useful Introduction", titles)
        self.assertNotIn("VTH = VDD - 2V", titles)
        self.assertNotIn("y = mx + b", titles)
        self.assertNotIn("CLK2 + CLK3", titles)
        self.assertNotIn("1.1 V = IR", titles)
        self.assertNotIn("1.2 P = UI", titles)


if __name__ == "__main__":
    unittest.main()
