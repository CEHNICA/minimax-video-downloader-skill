from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parent.parent / "scripts" / "download_video.py"
spec = spec_from_file_location("download_video", SCRIPT)
router = module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(router)


class RoutingTests(unittest.TestCase):
    def test_xiaohongshu_share_text(self):
        self.assertEqual(router.choose_platform("看看这个 https://xhslink.cn/o/Example123 好看"), "xiaohongshu")

    def test_full_xiaohongshu_link(self):
        self.assertEqual(router.choose_platform("https://www.xiaohongshu.com/discovery/item/abc123?xsec_token=abc"), "xiaohongshu")

    def test_wechat_channels(self):
        self.assertEqual(router.choose_platform("https://weixin.qq.com/sph/Example123"), "wechat-channels")

    def test_reject_lookalike_hosts(self):
        for url in ("https://weixin.qq.com.evil.com/sph/Example123", "https://xhslink.cn.evil.com/o/abc",
                    "https://v.douyin.com.evil.com/Example123/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                router.choose_platform(url)

    def test_reject_multiple_videos(self):
        with self.assertRaisesRegex(ValueError, "多条"):
            router.choose_platform("https://xhslink.cn/o/Example123 https://weixin.qq.com/sph/Example123")

    def test_douyin_short_link_in_share_text(self):
        share = "示例视频 [https://v.douyin.com/Example123/](https://v.douyin.com/Example123/)"
        self.assertEqual(router.choose_platform(share), "douyin")

    def test_douyin_long_link(self):
        self.assertEqual(router.choose_platform("https://www.douyin.com/video/1234567890123456789"), "douyin")

    def test_pass_only_selected_video_link(self):
        platform, url = router.choose_share(
            "说明 https://example.com/info 视频 https://www.douyin.com/video/1234567890123456789/"
        )
        self.assertEqual((platform, url), ("douyin", "https://www.douyin.com/video/1234567890123456789/"))

    def test_reject_unsupported_site(self):
        with self.assertRaises(ValueError):
            router.choose_platform("https://www.youtube.com/watch?v=abc123")

    def test_bilibili_long_link(self):
        self.assertEqual(router.choose_platform("https://www.bilibili.com/video/BV1b9ad6xEnD/"), "bilibili")

    def test_bilibili_share_link_with_tracking_query(self):
        share = ("看看这个 https://www.bilibili.com/video/BV1b9ad6xEnD/?spm_id_from=333.999&vd_source=abc 推荐")
        self.assertEqual(router.choose_platform(share), "bilibili")

    def test_bilibili_short_link(self):
        self.assertEqual(router.choose_platform("https://b23.tv/AbCd12"), "bilibili")

    def test_reject_bilibili_lookalike(self):
        for url in ("https://www.bilibili.com.evil.com/video/BV1b9ad6xEnD/", "https://b23.tv.evil.com/AbCd12"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                router.choose_platform(url)


if __name__ == "__main__":
    unittest.main()
