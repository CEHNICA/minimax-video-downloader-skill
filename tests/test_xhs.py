"""Offline tests for the Xiaohongshu downloader helpers.

`download_xhs.py` originally left files named `*.unknown_video`: the
Xiaohongshu extractor sometimes reports no usable extension, yt-dlp writes the
`%(ext)s)` fallback literally, and Windows then refuses to open a file that
ffprobe happily validates. These tests pin the container-to-extension mapping
and the rename behaviour.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parent.parent / "scripts" / "download_xhs.py"
spec = spec_from_file_location("download_xhs", SCRIPT)
xhs = module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(xhs)


class ContainerMappingTests(unittest.TestCase):
    def test_mp4_family(self):
        for format_name in ("mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov", "m4a"):
            with self.subTest(format_name=format_name):
                self.assertEqual(xhs.extension_for_container(format_name), ".mp4")

    def test_matroska_and_webm(self):
        self.assertEqual(xhs.extension_for_container("matroska,webm"), ".webm")
        self.assertEqual(xhs.extension_for_container("webm"), ".webm")

    def test_stream_containers(self):
        self.assertEqual(xhs.extension_for_container("mpegts"), ".ts")
        self.assertEqual(xhs.extension_for_container("flv"), ".flv")

    def test_unknown_container_returns_none(self):
        for format_name in ("", "something_else", "avi"):
            with self.subTest(format_name=format_name):
                self.assertIsNone(xhs.extension_for_container(format_name))


class NormaliseExtensionTests(unittest.TestCase):
    def test_unknown_video_becomes_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "笔记 [abc123].unknown_video"
            source.write_bytes(b"payload")
            result, renamed = xhs.normalise_extension(source, "mov,mp4,m4a,3gp,3g2,mj2")
            self.assertTrue(renamed)
            self.assertEqual(result.name, "笔记 [abc123].mp4")
            self.assertTrue(result.is_file())
            self.assertEqual(result.read_bytes(), b"payload")

    def test_dots_in_title_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "用opus5.5 创造的 MV [abc].unknown_video"
            source.write_bytes(b"payload")
            result, renamed = xhs.normalise_extension(source, "mov,mp4,m4a,3gp,3g2,mj2")
            self.assertTrue(renamed)
            self.assertEqual(result.name, "用opus5.5 创造的 MV [abc].mp4")

    def test_already_playable_extension_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"payload")
            result, renamed = xhs.normalise_extension(source, "mov,mp4,m4a,3gp,3g2,mj2")
            self.assertFalse(renamed)
            self.assertEqual(result, source)

    def test_mkv_is_left_alone_even_for_mp4_content(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mkv"
            source.write_bytes(b"payload")
            result, renamed = xhs.normalise_extension(source, "mov,mp4,m4a,3gp,3g2,mj2")
            self.assertFalse(renamed)
            self.assertEqual(result.name, "clip.mkv")

    def test_unknown_container_leaves_file_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.unknown_video"
            source.write_bytes(b"payload")
            result, renamed = xhs.normalise_extension(source, "mystery")
            self.assertFalse(renamed)
            self.assertTrue(source.is_file())

    def test_rename_replaces_only_the_final_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "a.b.c.unknown_video"
            source.write_bytes(b"payload")
            result, _ = xhs.normalise_extension(source, "mp4")
            self.assertEqual(result.name, "a.b.c.mp4")


class RedactionTests(unittest.TestCase):
    def test_xsec_token_is_removed(self):
        message = "ERROR https://www.xiaohongshu.com/discovery/item/abc?xsec_token=SECRET&xsec_source=pc_feed"
        cleaned = xhs.redact_share_parameters(message)
        self.assertNotIn("SECRET", cleaned)
        self.assertIn("discovery/item/abc", cleaned)

    def test_query_is_stripped_from_urls(self):
        cleaned = xhs.redact_share_parameters("see https://example.com/a/b?token=1#frag")
        self.assertIn("https://example.com/a/b", cleaned)
        self.assertNotIn("token=1", cleaned)


if __name__ == "__main__":
    unittest.main()
