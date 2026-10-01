"""Offline tests for the Bilibili downloader: identifier parsing and format selection.

These tests never touch the network. The AV1 regression they guard is that
`bv*` prefers Bilibili's AV1 streams, whose CDN returns 503 without login.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parent.parent / "scripts" / "download_bilibili.py"
spec = spec_from_file_location("download_bilibili", SCRIPT)
bili = module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(bili)


class ResolveVideoIdTests(unittest.TestCase):
    def test_bare_bv_id(self):
        self.assertEqual(bili.resolve_video_id("BV1b9ad6xEnD"), "BV1b9ad6xEnD")

    def test_bare_av_id(self):
        self.assertEqual(bili.resolve_video_id("av170001"), "av170001")

    def test_video_url(self):
        self.assertEqual(bili.resolve_video_id("https://www.bilibili.com/video/BV1b9ad6xEnD/"), "BV1b9ad6xEnD")

    def test_video_url_with_share_query(self):
        url = ("https://www.bilibili.com/video/BV1b9ad6xEnD/?buvid=XUCC&spm_id_from=333.999"
               "&vd_source=31c53e79eacbc81065d69fdb48e2fab3")
        self.assertEqual(bili.resolve_video_id(url), "BV1b9ad6xEnD")

    def test_url_inside_share_text(self):
        share = "【震惊瘫坐】https://www.bilibili.com/video/BV1b9ad6xEnD/?vd_source=abc 记得三连"
        self.assertEqual(bili.resolve_video_id(share), "BV1b9ad6xEnD")

    def test_canonical_url(self):
        self.assertEqual(bili.canonical_url("BV1b9ad6xEnD"), "https://www.bilibili.com/video/BV1b9ad6xEnD/")

    def test_reject_foreign_host(self):
        for url in ("https://www.bilibili.com.evil.com/video/BV1b9ad6xEnD/",
                    "https://evil.com/video/BV1b9ad6xEnD/",
                    "https://b23.tv.evil.com/AbCd12"):
            with self.subTest(url=url), self.assertRaises(bili.DownloadError):
                bili.resolve_video_id(url)

    def test_reject_unsafe_url_shape(self):
        for url in ("http://www.bilibili.com/video/BV1b9ad6xEnD/",
                    "https://user:pw@www.bilibili.com/video/BV1b9ad6xEnD/",
                    "https://www.bilibili.com:8443/video/BV1b9ad6xEnD/",
                    "https://www.bilibili.com/video/BV1b9ad6xEnD/#frag"):
            with self.subTest(url=url), self.assertRaises(bili.DownloadError):
                bili.resolve_video_id(url)

    def test_reject_bilibili_page_without_video(self):
        with self.assertRaises(bili.DownloadError):
            bili.resolve_video_id("https://space.bilibili.com/295428344")

    def test_reject_text_without_link(self):
        with self.assertRaises(bili.DownloadError):
            bili.resolve_video_id("今天天气不错")

    def test_reject_malformed_bv_id(self):
        for url in ("https://www.bilibili.com/video/BV123/", "https://www.bilibili.com/video/BV1b9ad6xEnDx/"):
            with self.subTest(url=url), self.assertRaises(bili.DownloadError):
                bili.resolve_video_id(url)

    def test_reject_bad_bv_id_to_canonical(self):
        with self.assertRaises(bili.DownloadError):
            bili.canonical_url("not-a-bv-id")


class TitleSanitisationTests(unittest.TestCase):
    def test_reserved_characters_replaced(self):
        self.assertEqual(bili.windows_safe_title('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_length_capped_and_trimmed(self):
        self.assertEqual(len(bili.windows_safe_title("名" * 200)), 80)
        self.assertEqual(bili.windows_safe_title("标题.  "), "标题")

    def test_keeps_chinese_and_fullwidth_punctuation(self):
        self.assertEqual(bili.windows_safe_title("震惊瘫坐！短片《太阳》"), "震惊瘫坐！短片《太阳》")

    def test_never_returns_empty(self):
        self.assertEqual(bili.windows_safe_title("///"), "___")
        self.assertEqual(bili.windows_safe_title(""), "video")


class FormatSelectionTests(unittest.TestCase):
    def test_best_prefers_avc1_first(self):
        selector = bili.build_format("best")
        self.assertTrue(selector.startswith("bv*[vcodec^=avc1]+ba/"))

    def test_av1_never_preferred(self):
        for quality in bili.QUALITY_CHOICES:
            with self.subTest(quality=quality):
                selector = bili.build_format(quality)
                self.assertNotIn("av01", selector)
                # avc1 is tried before hvc1, and the catch-all segment is last.
                self.assertLess(selector.index("avc1"), selector.index("hvc1"))
                catch_all = selector.split("/")[-1]
                self.assertTrue(catch_all.startswith("bv*") and catch_all.endswith("+ba"))
                self.assertNotIn("vcodec", catch_all)

    def test_quality_caps_height(self):
        self.assertIn("[height<=720]", bili.build_format("720"))
        self.assertIn("[height<=1080]", bili.build_format("1080"))

    def test_best_has_no_height_cap(self):
        self.assertNotIn("height<=", bili.build_format("best"))

    def test_falls_back_to_h265_then_any(self):
        selector = bili.build_format("best")
        self.assertIn("bv*[vcodec^=hvc1]+ba/b", selector)
        self.assertTrue(selector.endswith("bv*+ba"))

    def test_every_advertised_quality_is_buildable(self):
        for quality in ("1080", "720", "480", "360", "best"):
            with self.subTest(quality=quality):
                self.assertTrue(bili.build_format(quality))


if __name__ == "__main__":
    unittest.main()
