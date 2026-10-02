import tempfile
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from app.core import llm_bookmarks


def _patch_pipeline_steps():
    """跳过书名识别/无关页摘除/页眉摘除三个前置步骤，聚焦第 4 步批处理逻辑。"""
    return (patch.object(llm_bookmarks, "_detect_book_title", return_value="测试书名"),
            patch.object(llm_bookmarks, "_llm_drop_front_matter",
                         side_effect=lambda pdf, cands, key, title: cands),
            patch.object(llm_bookmarks, "_llm_drop_running_heads",
                         side_effect=lambda cands, key, title: cands))


class LlmBookmarkTests(unittest.TestCase):
    def test_configured_lmstudio_model_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings = home / ".lmstudio" / "settings.json"
            settings.parent.mkdir()
            configured = home / "other models"
            settings.write_text(json.dumps({"downloadsFolder": str(configured)}), encoding="utf-8")
            with patch.object(llm_bookmarks.Path, "home", return_value=home):
                self.assertEqual(llm_bookmarks.lmstudio_models_dir(), configured)

    def test_model_copy_is_on_demand_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.gguf"
            source.write_bytes(b"GGUF" + b"model content")
            with patch.object(llm_bookmarks, "model_store_dir", return_value=root / "llm_models"):
                copied = llm_bookmarks.copy_model_to_project(source)
                self.assertTrue(copied.is_file())
                self.assertEqual(copied.read_bytes(), source.read_bytes())
                self.assertEqual(llm_bookmarks.copy_model_to_project(source), copied)

    def test_partial_and_projection_models_are_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good.gguf").write_bytes(b"GGUF")
            (root / "downloading.gguf.part").write_bytes(b"GGUF")
            (root / "mmproj-bad.gguf").write_bytes(b"GGUF")
            with patch.object(llm_bookmarks, "model_store_dir", return_value=root), \
                 patch.object(llm_bookmarks, "lmstudio_models_dir", return_value=root):
                self.assertEqual([p.name for p in llm_bookmarks.list_local_models()], ["good.gguf"])

    def test_model_copies_and_hard_links_are_listed_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "store" / "abc123"
            store.mkdir(parents=True)
            model = store / "model.gguf"
            model.write_bytes(b"GGUF model")
            lmstudio = root / "lmstudio"
            linked = lmstudio / "pdf-converter" / "abc123"
            linked.mkdir(parents=True)
            os.link(model, linked / "model.gguf")          # 硬链接（同一文件）
            original = lmstudio / "publisher" / "repo"
            original.mkdir(parents=True)
            (original / "model.gguf").write_bytes(b"GGUF model")  # 同名同大小的独立副本
            with patch.object(llm_bookmarks, "model_store_dir", return_value=root / "store"), \
                 patch.object(llm_bookmarks, "lmstudio_models_dir", return_value=lmstudio):
                self.assertEqual([p.name for p in llm_bookmarks.list_local_models()], ["model.gguf"])

    def test_model_selects_only_source_candidates_not_hallucinated_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "Section 1.2 Applications", fontsize=14)
            page.insert_text((40, 120), "VTH = VDD - 2V", fontsize=20)
            page.insert_text((40, 170), "This is a paragraph of normal body text for font sizing.", fontsize=10)
            doc.save(path)
            doc.close()
            candidates = llm_bookmarks._extract_candidates(str(path), False)
            self.assertIn("Section 1.2 Applications", [r["text"] for r in candidates])
            self.assertIn("VTH = VDD - 2V", [r["text"] for r in candidates])
            title_id = next(r["id"] for r in candidates if r["text"] == "Section 1.2 Applications")
            reply = {"output": [{"type": "message", "content":
                                  f'{{"headings":[{{"id":{title_id},"level":2}},{{"id":999,"level":1}}]}}'}]}
            steps = _patch_pipeline_steps()
            with patch.object(llm_bookmarks, "copy_model_to_project", return_value=Path("sample.gguf")), \
                 patch.object(llm_bookmarks, "_import_copied_model", return_value="sample"), \
                 patch.object(llm_bookmarks, "_ensure_server"), \
                 steps[0], steps[1], steps[2], \
                 patch.object(llm_bookmarks, "_json_request", return_value=reply):
                toc = llm_bookmarks.detect_headings(str(path), "sample.gguf")
            self.assertEqual(toc, [{"title": "Section 1.2 Applications", "page": 0, "level": 1}])

    def test_invalid_model_output_is_rejected(self):
        with self.assertRaises(ValueError):
            llm_bookmarks._parse_headings("not JSON", {1}, 3)
        self.assertEqual(llm_bookmarks._parse_headings('{"headings":[{"id":2,"level":1}]}', {1}, 3), [])

    def test_fenced_array_model_output_is_accepted(self):
        # Some instruction models switch from the requested object to a bare array mid-document.
        answer = '```json\n[{"id":72,"level":2},{"id":73,"level":2},' \
                 '{"id":999,"level":1},{"id":72,"level":1}]\n```'
        self.assertEqual(llm_bookmarks._parse_headings(answer, {72, 73}, 3),
                         [(72, 2), (73, 2)])
        self.assertEqual(llm_bookmarks._parse_headings("```json\n[]\n```", {72}, 3), [])

    def test_llm_progress_reports_pipeline_and_batch_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "Section 1.2 Applications", fontsize=14)
            doc.save(path)
            doc.close()
            updates = []
            steps = _patch_pipeline_steps()
            reply = {"output": [{"type": "message", "content": '{"headings":[]}'}]}
            with patch.object(llm_bookmarks, "copy_model_to_project", return_value=Path("sample.gguf")), \
                 patch.object(llm_bookmarks, "_import_copied_model", return_value="sample"), \
                 patch.object(llm_bookmarks, "_ensure_server"), \
                 steps[0], steps[1], steps[2], \
                 patch.object(llm_bookmarks, "_json_request", return_value=reply):
                llm_bookmarks.detect_headings(
                    str(path), "sample.gguf", llm_progress_cb=lambda done, total: updates.append((done, total)))

            self.assertEqual(updates[0], (0, 5))
            self.assertEqual(updates[-1], (5, 5))

    def test_incomplete_array_model_output_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "JSON 无法解析"):
            llm_bookmarks._parse_headings('[{"id":72,"level":2},', {72}, 3)

    def test_truncated_model_output_retries_with_larger_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "Section 1.2 Applications", fontsize=14)
            doc.save(path)
            doc.close()
            candidates = llm_bookmarks._extract_candidates(str(path), False)
            title_id = next(r["id"] for r in candidates)
            truncated = {"output": [{"type": "message", "content": "```json\n"}]}
            valid = {"output": [{"type": "message", "content":
                                 f'{{"headings":[{{"id":{title_id},"level":2}}]}}'}]}
            requests = []
            def fake_request(url, body=None, timeout=30):
                requests.append(body)
                return truncated if len(requests) == 1 else valid
            steps = _patch_pipeline_steps()
            with patch.object(llm_bookmarks, "copy_model_to_project", return_value=Path("sample.gguf")), \
                 patch.object(llm_bookmarks, "_import_copied_model", return_value="sample"), \
                 patch.object(llm_bookmarks, "_ensure_server"), \
                 steps[0], steps[1], steps[2], \
                 patch.object(llm_bookmarks, "_json_request", side_effect=fake_request):
                toc = llm_bookmarks.detect_headings(str(path), "sample.gguf")
            self.assertEqual(toc, [{"title": "Section 1.2 Applications", "page": 0, "level": 1}])
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0]["max_output_tokens"], llm_bookmarks.MAX_OUTPUT_TOKENS)
            self.assertEqual(requests[1]["max_output_tokens"], llm_bookmarks.RETRY_OUTPUT_TOKENS)

    def test_toc_preface_index_pages_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.pdf"
            doc = fitz.open()
            toc = doc.new_page()
            toc.insert_text((40, 80), "CONTENTS", fontsize=16)
            for i, entry in enumerate(["1 Ordinary Differential Equations",
                                       "1.1 Functions and Equations",
                                       "1.2 Classification of Differential Equations"]):
                toc.insert_text((40, 120 + i * 24), entry, fontsize=12)
                toc.insert_text((320, 120 + i * 24), str(i + 1), fontsize=12)
            body = doc.new_page()
            body.insert_text((40, 80), "1.3 Solutions of Differential Equations", fontsize=14)
            body.insert_text((40, 120), "This is a paragraph of normal body text for font sizing.", fontsize=10)
            preface = doc.new_page()
            preface.insert_text((40, 80), "PREFACE", fontsize=16)
            preface.insert_text((40, 120), "This preface paragraph is normal body text for sizing.", fontsize=10)
            index = doc.new_page()
            index.insert_text((40, 80), "Index", fontsize=12)
            for i in range(12):
                index.insert_text((40, 120 + i * 24), f"Characteristic vectors, {100 + i}, {200 + i}", fontsize=10)
            doc.save(path)
            doc.close()
            texts = [r["text"] for r in llm_bookmarks._extract_candidates(str(path), False)]
            self.assertIn("1.3 Solutions of Differential Equations", texts)
            self.assertNotIn("1 Ordinary Differential Equations", texts)
            self.assertNotIn("PREFACE", texts)
            self.assertFalse(any(t.startswith("Characteristic vectors") for t in texts))

    def test_non_content_page_detection(self):
        toc_like = [f"1.{i} Section Title .......... {i}" for i in range(1, 14)]
        self.assertTrue(llm_bookmarks._is_non_content_page(toc_like))
        index_like = [f"entry{i}, {100 + i}, {200 + i}" for i in range(14)]
        self.assertTrue(llm_bookmarks._is_non_content_page(index_like))
        # 习题页的题号不是页码证据，不能误判
        exercises = []
        for i in range(13, 25):
            exercises += [str(i), f"Solve the differential equation number {i} for y"]
        self.assertFalse(llm_bookmarks._is_non_content_page(exercises))
        normal = ["13.2 The Algebra of Vectors", "This is a paragraph of body text for sizing."]
        self.assertFalse(llm_bookmarks._is_non_content_page(normal))
        # 行数少的目录续页按比例判定
        short_toc = ["第三部分 概率论与数理统计 ................... 419",
                     "第1讲 随机事件与概率 ......................... 421",
                     "第2讲 一维随机变量及其分布 .................... 442",
                     "第3讲 多维随机变量及其分布 .................... 466",
                     "第4讲 随机变量的数字特征 ...................... 494",
                     "第5讲 大数定律与中心极限定理 .................. 509", "2"]
        self.assertTrue(llm_bookmarks._is_non_content_page(short_toc))
        # 书眉带罗马数字页码、中文前言带版次的变体也要识别
        self.assertTrue(llm_bookmarks._is_non_content_page(["Ⅱ 目录", "1.1概述", "1"]))
        self.assertTrue(llm_bookmarks._is_non_content_page(["第六版前言", "本书是在原书基础上修订而成的长段落文本"]))
        self.assertTrue(llm_bookmarks._is_non_content_page(["Ⅱ第三版序", "序言正文段落"]))
        # 习题答案页同样剔除
        self.assertTrue(llm_bookmarks._is_non_content_page(["Answers to Odd-Numbered Exercises", "1. y = ce^x"]))
        self.assertTrue(llm_bookmarks._is_non_content_page(["习题答案", "1. （略）"]))

    def test_numbering_level_overrides_model_level(self):
        self.assertEqual(llm_bookmarks._numbering_level("1.1 Functions and Equations", 3), 2)
        self.assertEqual(llm_bookmarks._numbering_level("13.1.4 Some Subsection", 3), 3)
        self.assertEqual(llm_bookmarks._numbering_level("13 Vector Analysis", 3), 1)
        self.assertEqual(llm_bookmarks._numbering_level("第3章 时序逻辑电路", 3), 1)
        self.assertIsNone(llm_bookmarks._numbering_level("Vector Analysis", 3))
        self.assertIsNone(llm_bookmarks._numbering_level("1 do not necessarily define a", 3))
        self.assertEqual(llm_bookmarks._numbering_level("第5讲 大数定律与中心极限定理", 3), 1)

    def test_example_problems_are_not_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "3.1 事件的运算", fontsize=14, fontname="china-s")
            page.insert_text((40, 120), "1.1.4画出r=aθ（a>0）的图形。（这里e是常数）", fontsize=10, fontname="china-s")
            page.insert_text((40, 160), "3. 3.1设随机变量X和Y的联合分布函数为", fontsize=10, fontname="china-s")
            page.insert_text((40, 200), "定理2（有界性）", fontsize=10, fontname="china-s")
            page.insert_text((40, 240), "This is a paragraph of normal body text for font sizing.", fontsize=10)
            doc.save(path)
            doc.close()
            texts = [r["text"] for r in llm_bookmarks._extract_candidates(str(path), False)]
            self.assertIn("3.1 事件的运算", texts)
            self.assertFalse(any("1.1.4" in t for t in texts))
            self.assertFalse(any("3. 3.1" in t for t in texts))
            self.assertFalse(any(t.startswith("定理2") for t in texts))

    def test_number_fragments_are_not_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "1.2 Classification of Differential Equations", fontsize=14)
            page.insert_text((40, 120), "1 .2", fontsize=12)
            page.insert_text((40, 160), "13.1 5", fontsize=12)
            page.insert_text((40, 200), "This is a paragraph of normal body text for font sizing.", fontsize=10)
            doc.save(path)
            doc.close()
            texts = [r["text"] for r in llm_bookmarks._extract_candidates(str(path), False)]
            self.assertIn("1.2 Classification of Differential Equations", texts)
            self.assertNotIn("1 .2", texts)
            self.assertNotIn("13.1 5", texts)

    def test_model_level_is_corrected_for_numbered_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "13 Vector Analysis", fontsize=20)
            page.insert_text((40, 140), "13.1 Introduction", fontsize=14)
            page.insert_text((40, 180), "This is a paragraph of normal body text for font sizing.", fontsize=10)
            doc.save(path)
            doc.close()
            candidates = llm_bookmarks._extract_candidates(str(path), False)
            chapter_id = next(r["id"] for r in candidates if r["text"] == "13 Vector Analysis")
            section_id = next(r["id"] for r in candidates if r["text"] == "13.1 Introduction")
            # 模型把章判成 level 2、节判成 level 3，编号规则应纠正为 1 和 2
            reply = {"output": [{"type": "message", "content":
                                  f'{{"headings":[{{"id":{chapter_id},"level":2}},{{"id":{section_id},"level":3}}]}}'}]}
            steps = _patch_pipeline_steps()
            with patch.object(llm_bookmarks, "copy_model_to_project", return_value=Path("sample.gguf")), \
                 patch.object(llm_bookmarks, "_import_copied_model", return_value="sample"), \
                 patch.object(llm_bookmarks, "_ensure_server"), \
                 steps[0], steps[1], steps[2], \
                 patch.object(llm_bookmarks, "_json_request", return_value=reply):
                toc = llm_bookmarks.detect_headings(str(path), "sample.gguf")
            self.assertEqual(toc, [{"title": "13 Vector Analysis", "page": 0, "level": 1},
                                   {"title": "13.1 Introduction", "page": 0, "level": 2}])

    def test_prompt_enforces_numbered_levels_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "Section 1.2 Applications", fontsize=14)
            doc.save(path)
            doc.close()
            captured = []
            def fake_request(url, body=None, timeout=30):
                captured.append(body)
                return {"output": [{"type": "message", "content": '{"headings":[]}'}]}
            steps = _patch_pipeline_steps()
            with patch.object(llm_bookmarks, "copy_model_to_project", return_value=Path("sample.gguf")), \
                 patch.object(llm_bookmarks, "_import_copied_model", return_value="sample"), \
                 patch.object(llm_bookmarks, "_ensure_server"), \
                 steps[0], steps[1], steps[2], \
                 patch.object(llm_bookmarks, "_json_request", side_effect=fake_request):
                llm_bookmarks.detect_headings(str(path), "sample.gguf")
            prompt = captured[-1]["input"]
            for phrase in ("level 1", "level 2", "level 3", "THEOREM", "习题答案",
                           "不要模仿其层级", "孤立或带空格的纯数字"):
                self.assertIn(phrase, prompt)

    def test_book_title_detection_and_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "some file name.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "Advanced Engineering Mathematics", fontsize=24)
            doc.save(path)
            doc.close()
            with patch.object(llm_bookmarks, "_chat_once",
                              return_value="《Advanced Engineering Mathematics》"):
                self.assertEqual(llm_bookmarks._detect_book_title(str(path), "m"),
                                 "Advanced Engineering Mathematics")
            with patch.object(llm_bookmarks, "_chat_once", return_value="x" * 200):
                self.assertEqual(llm_bookmarks._detect_book_title(str(path), "m"), "some file name")

    def test_front_matter_pages_dropped_by_llm(self):
        candidates = [{"id": 0, "page": 0, "text": "Preface"},
                      {"id": 1, "page": 3, "text": "1.1 Functions"}]
        with patch.object(llm_bookmarks, "_page_previews", return_value=["页0: Preface"]), \
             patch.object(llm_bookmarks, "_chat_once", return_value='{"drop_pages":[0]}'):
            kept = llm_bookmarks._llm_drop_front_matter("x.pdf", candidates, "m", "书名")
        self.assertEqual([c["text"] for c in kept], ["1.1 Functions"])
        self.assertEqual(kept[0]["id"], 0)
        # 模型回答无效时保留原候选
        with patch.object(llm_bookmarks, "_page_previews", return_value=["页0: Preface"]), \
             patch.object(llm_bookmarks, "_chat_once", return_value="不是 JSON"):
            self.assertEqual(llm_bookmarks._llm_drop_front_matter("x.pdf", candidates, "m", "书名"),
                             candidates)

    def test_running_heads_dropped_but_repeated_sections_kept(self):
        candidates = [{"id": i, "page": p, "text": t} for i, (p, t) in enumerate([
            (1, "Advanced Engineering Mathematics"), (2, "Advanced Engineering Mathematics"),
            (3, "Advanced Engineering Mathematics"), (4, "1.1 Functions"),
            (5, "1. 概念"), (9, "1. 概念"), (12, "1. 概念")])]
        # 书名页眉不经模型直接摘除；"1. 概念" 是各章重复的真实小节，模型确认后保留
        with patch.object(llm_bookmarks, "_chat_once", return_value='{"drop":[]}') as chat:
            kept = llm_bookmarks._llm_drop_running_heads(candidates, "m",
                                                         "Advanced Engineering Mathematics")
        texts = [c["text"] for c in kept]
        self.assertNotIn("Advanced Engineering Mathematics", texts)
        self.assertEqual(texts.count("1. 概念"), 3)
        # 模型确认摘除的重复文本被移除
        with patch.object(llm_bookmarks, "_chat_once", return_value='{"drop":["1. 概念"]}'):
            kept = llm_bookmarks._llm_drop_running_heads(candidates, "m", "")
        self.assertEqual([c["text"] for c in kept],
                         ["Advanced Engineering Mathematics"] * 3 + ["1.1 Functions"])

    def test_http_500_is_retried(self):
        import urllib.error
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((40, 80), "Section 1.2 Applications", fontsize=14)
            doc.save(path)
            doc.close()
            candidates = llm_bookmarks._extract_candidates(str(path), False)
            title_id = next(r["id"] for r in candidates)
            fail500 = urllib.error.HTTPError("http://x", 500, "Internal Server Error", {}, None)
            valid = {"output": [{"type": "message", "content":
                                 f'{{"headings":[{{"id":{title_id},"level":2}}]}}'}]}
            calls = []
            def fake_request(url, body=None, timeout=30):
                calls.append(body)
                if len(calls) == 1:
                    raise fail500
                return valid
            steps = _patch_pipeline_steps()
            with patch.object(llm_bookmarks, "copy_model_to_project", return_value=Path("sample.gguf")), \
                 patch.object(llm_bookmarks, "_import_copied_model", return_value="sample"), \
                 patch.object(llm_bookmarks, "_ensure_server"), \
                 steps[0], steps[1], steps[2], \
                 patch.object(llm_bookmarks.time, "sleep"), \
                 patch.object(llm_bookmarks, "_json_request", side_effect=fake_request):
                toc = llm_bookmarks.detect_headings(str(path), "sample.gguf")
            self.assertEqual(toc, [{"title": "Section 1.2 Applications", "page": 0, "level": 1}])
            self.assertEqual(len(calls), 2)

    def test_import_uses_hard_link_for_same_drive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "llm_models" / "abc123" / "model.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"GGUF")
            listing = json.dumps([{"path": "pdf-converter/abc123/model.gguf", "modelKey": "local-model"}])
            with patch.object(llm_bookmarks, "lmstudio_models_dir", return_value=root / "lmstudio"), \
                 patch.object(llm_bookmarks, "_lms", side_effect=["", "[]", listing]) as cli, \
                 patch.object(llm_bookmarks.time, "sleep"):
                self.assertEqual(llm_bookmarks._import_copied_model(model), "local-model")
            self.assertIn("--hard-link", cli.call_args_list[0].args)

    def test_import_reuses_identical_registration_from_another_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "llm_models" / "abc123" / "model.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"GGUF" + b"same content")
            registry = root / "lmstudio" / "pdf-converter" / "abc123" / "model.gguf"
            registry.parent.mkdir(parents=True)
            registry.write_bytes(model.read_bytes())
            listing = json.dumps([{"path": "pdf-converter/abc123/model.gguf", "modelKey": "local-model"}])
            with patch.object(llm_bookmarks, "lmstudio_models_dir", return_value=root / "lmstudio"), \
                 patch.object(llm_bookmarks, "_lms", return_value=listing) as cli:
                self.assertEqual(llm_bookmarks._import_copied_model(model), "local-model")
            self.assertNotIn("import", cli.call_args_list[0].args)
            registry.write_bytes(b"GGUF" + b"different")
            with patch.object(llm_bookmarks, "lmstudio_models_dir", return_value=root / "lmstudio"), \
                 self.assertRaisesRegex(RuntimeError, "同名但不同内容"):
                llm_bookmarks._import_copied_model(model)


if __name__ == "__main__":
    unittest.main()
