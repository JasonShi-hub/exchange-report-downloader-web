import unittest

from app.downloaders.cninfo_downloader import (
    build_output_filename,
    build_short_doc_key,
    classify_announcement,
    expand_category_codes,
    is_relation_code,
)


class CninfoHelperTests(unittest.TestCase):
    def test_expand_category_codes_keeps_order(self):
        result = expand_category_codes(["a;b", "b", " c ", "", "d;;"])
        self.assertEqual(result, ["a", "b", "c", "d"])

    def test_relation_code_detection(self):
        self.assertTrue(is_relation_code("category_dyhd_szdy"))
        self.assertFalse(is_relation_code("category_ndbg_szsh"))

    def test_classify_research_title(self):
        self.assertEqual(classify_announcement("投资者关系活动记录表"), "调研报告")

    def test_build_short_doc_key_prefers_announcement_id(self):
        self.assertEqual(build_short_doc_key("1234567890123", "a.pdf"), "A4567890123")

    def test_output_filename_keeps_unique_suffix(self):
        filename = build_output_filename("2025-01-01", "2025年年度报告", "1234567890123", "a.pdf")
        self.assertTrue(filename.endswith("_A4567890123.pdf"))


if __name__ == "__main__":
    unittest.main()

