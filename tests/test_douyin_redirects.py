"""Focused tests for the Douyin shortlink redirect boundary."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


SCRIPT = Path(__file__).parent.parent / "scripts" / "download_douyin.py"
spec = importlib.util.spec_from_file_location("download_douyin_under_test", SCRIPT)
downloader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloader)


class FakeOpener:
    def __init__(self, locations, first_status=None):
        self.locations = list(locations)
        self.first_status = first_status
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method()))
        if self.first_status and len(self.calls) == 1:
            raise HTTPError(request.full_url, self.first_status, "test", {}, None)
        location = self.locations.pop(0)
        raise HTTPError(request.full_url, 302, "test", {"Location": location}, None)


class RedirectBoundaryTests(unittest.TestCase):
    def test_safe_redirect_returns_video_id_without_following_target(self):
        opener = FakeOpener(["https://www.douyin.com/video/1234567890123456789"])
        with patch.object(downloader, "build_opener", return_value=opener):
            self.assertEqual(downloader.resolve_aweme_id("https://v.douyin.com/abc/"), "1234567890123456789")
        self.assertEqual(opener.calls, [("https://v.douyin.com/abc", "HEAD")])

    def test_offsite_and_non_https_redirects_are_never_requested(self):
        for target in ("https://example.com/video/1234567890123456789",
                       "http://www.douyin.com/video/1234567890123456789",
                       "https://www.douyin.com.evil.test/video/1234567890123456789",
                       "https://user@www.douyin.com/video/1234567890123456789",
                       "https://www.douyin.com:444/video/1234567890123456789"):
            with self.subTest(target=target):
                opener = FakeOpener([target])
                with patch.object(downloader, "build_opener", return_value=opener):
                    with self.assertRaises(downloader.DownloadError):
                        downloader.resolve_aweme_id("https://v.douyin.com/abc/")
                self.assertEqual(len(opener.calls), 1)

    def test_redirect_limit_stops_before_tenth_request(self):
        locations = [f"https://v.douyin.com/step{i}" for i in range(1, 11)]
        opener = FakeOpener(locations)
        with patch.object(downloader, "build_opener", return_value=opener):
            with self.assertRaisesRegex(downloader.DownloadError, "次数过多"):
                downloader.resolve_aweme_id("https://v.douyin.com/start")
        self.assertEqual(len(opener.calls), downloader.MAX_SHORTLINK_REDIRECTS + 1)

    def test_head_failure_can_fall_back_to_get(self):
        opener = FakeOpener(["https://www.douyin.com/video/1234567890123456789"], first_status=405)
        with patch.object(downloader, "build_opener", return_value=opener):
            self.assertEqual(downloader.resolve_aweme_id("https://v.douyin.com/abc/"), "1234567890123456789")
        self.assertEqual([method for _, method in opener.calls], ["HEAD", "GET"])


if __name__ == "__main__":
    unittest.main()
