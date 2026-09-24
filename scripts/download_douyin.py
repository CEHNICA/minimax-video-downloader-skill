#!/usr/bin/env python3
"""Download one public Douyin video without touching the user's Chrome profile.

Dependencies: Python playwright, Google Chrome, yt-dlp, ffprobe.
The script starts and closes only its own Playwright Chrome window/profile.
It never imports cookies from the user's browsers.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


ALLOWED_HOSTS = {"douyin.com", "www.douyin.com", "m.douyin.com", "v.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}
SHARE_URL = "https://www.iesdouyin.com/share/video/{}/"
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
URL_RE = re.compile(r"https?://[^\s，。；、<>\[\]()]+", re.I)
AWEME_ID_RE = re.compile(r"^\d{15,25}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,256}$")
MAX_SHORTLINK_REDIRECTS = 8


def default_profile_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "MiniMax" / "video-downloader" / "douyin-chrome-profile"


class DownloadError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _validate_douyin_url(url: str) -> None:
    try:
        parsed = urlparse(url)
        allowed = (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
                   and parsed.username is None and parsed.password is None
                   and parsed.port is None and not parsed.fragment)
    except ValueError:
        allowed = False
    if not allowed or any(ord(char) < 32 for char in url) or "\\" in url:
        raise DownloadError("只接受 HTTPS 的 douyin.com 或 iesdouyin.com 视频链接")


def _aweme_id_from_url(url: str) -> str | None:
    _validate_douyin_url(url)
    parsed = urlparse(url)
    path_match = re.search(r"/(?:video|share/video)/(\d{15,25})(?:/|$)", parsed.path)
    if path_match:
        return path_match.group(1)
    modal = parse_qs(parsed.query).get("modal_id", [None])[0]
    if modal and AWEME_ID_RE.fullmatch(modal):
        return modal
    return None


def _follow_shortlink(url: str, method: str) -> str | None:
    """Follow only inspected Douyin HTTPS redirects; never request a new origin first."""
    opener = build_opener(NoRedirect())
    current = url
    for _ in range(MAX_SHORTLINK_REDIRECTS + 1):
        _validate_douyin_url(current)
        aweme_id = _aweme_id_from_url(current)
        if aweme_id:
            return aweme_id
        request = Request(current, method=method, headers={"User-Agent": ANDROID_UA})
        try:
            with opener.open(request, timeout=20) as response:
                final_url = response.geturl()
                return _aweme_id_from_url(final_url)
        except HTTPError as error:
            code = error.code
            location = error.headers.get("Location")
            error.close()
            if code not in (301, 302, 303, 307, 308):
                raise
            if not location or any(ord(char) < 32 for char in location):
                raise DownloadError("抖音短链返回无效跳转地址")
            target = urljoin(current, location)
            _validate_douyin_url(target)
            current = target
    raise DownloadError("抖音短链跳转次数过多")


def resolve_aweme_id(value: str) -> str:
    value = value.strip()
    if AWEME_ID_RE.fullmatch(value):
        return value
    match = URL_RE.search(value)
    if not match:
        raise DownloadError("没有找到抖音链接或视频 ID")
    url = match.group(0).rstrip("'\"),.;!?/）】")
    aweme_id = _aweme_id_from_url(url)
    if aweme_id:
        return aweme_id
    if urlparse(url).hostname != "v.douyin.com":
        raise DownloadError("链接里没有可识别的视频 ID")
    try:
        aweme_id = _follow_shortlink(url, "HEAD")
        if aweme_id:
            return aweme_id
    except (HTTPError, URLError, TimeoutError, OSError):
        pass
    try:
        aweme_id = _follow_shortlink(url, "GET")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DownloadError(f"抖音短链解析失败：{type(exc).__name__}") from exc
    if not aweme_id:
        raise DownloadError("短链跳转后没有找到视频 ID")
    return aweme_id


def extract_video_id(aweme_id: str, profile_dir: Path, attempts: int = 4) -> tuple[str, str]:
    """Open a mobile share page in a dedicated, persistent Chrome profile."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DownloadError("缺少 Python playwright 依赖") from exc

    profile_dir.mkdir(parents=True, exist_ok=True)
    share_url = SHARE_URL.format(aweme_id)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 375, "height": 812},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=3,
            user_agent=ANDROID_UA,
        )
        try:
            page = context.new_page()
            page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(8000)
            src = ""
            for attempt in range(1, attempts + 1):
                page.goto(share_url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_function(
                        "() => { const v = document.querySelector('video'); "
                        "return !!(v && (v.currentSrc || v.src).includes('video_id=')); }",
                        timeout=12000,
                    )
                    src = page.evaluate("document.querySelector('video').currentSrc || document.querySelector('video').src")
                    break
                except Exception:
                    if attempt < attempts:
                        page.wait_for_timeout(3000)
            if not src:
                raise DownloadError(f"浏览器尝试 {attempts} 次仍未找到该视频的播放地址")
            description = page.evaluate("document.querySelector('meta[name=description]')?.content || ''")
        finally:
            context.close()

    video_id = parse_qs(urlparse(src).query).get("video_id", [None])[0]
    if not video_id or not VIDEO_ID_RE.fullmatch(video_id):
        raise DownloadError("播放器地址中没有有效的 video_id")
    return video_id, description


def build_play_url(video_id: str, ratio: str) -> str:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise DownloadError("video_id 格式不正确")
    return f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio={ratio}&line=0"


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise DownloadError("下载文件无法通过 ffprobe 验证")
    data = json.loads(result.stdout)
    file_format = data.get("format", {})
    if "mp4" not in file_format.get("format_name", "").split(","):
        raise DownloadError("下载文件不是 MP4 容器")
    try:
        duration = float(file_format.get("duration", 0))
    except (TypeError, ValueError) as exc:
        raise DownloadError("下载文件没有有效时长") from exc
    if not 0 < duration < float("inf"):
        raise DownloadError("下载文件没有正时长")
    if not any(stream.get("codec_type") == "video" for stream in data.get("streams", [])):
        raise DownloadError("下载文件没有视频轨道")
    return data


def download_media(play_url: str, output: Path) -> dict:
    parsed = urlparse(play_url)
    if parsed.scheme != "https" or parsed.hostname != "aweme.snssdk.com" or parsed.path != "/aweme/v1/play/":
        raise DownloadError("媒体地址必须是预期的抖音播放地址")
    if output.exists():
        raise DownloadError(f"目标文件已存在，未覆盖：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="douyin-", dir=output.parent) as stage_dir:
        stage_file = Path(stage_dir) / "video.mp4"
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "--no-warnings", "--add-header", "Referer:https://www.douyin.com/",
             "--add-header", f"User-Agent:{ANDROID_UA}", "-o", str(stage_file), play_url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=240, creationflags=NO_WINDOW,
        )
        if result.returncode:
            detail = re.sub(r"https?://\S+", "[URL redacted]", (result.stderr or result.stdout)[-500:])
            raise DownloadError("媒体下载失败：" + detail)
        if not stage_file.exists() or stage_file.stat().st_size < 1024:
            raise DownloadError("媒体下载未生成有效文件")
        metadata = probe(stage_file)
        try:
            os.link(stage_file, output)
        except FileExistsError as exc:
            raise DownloadError(f"目标文件已存在，未覆盖：{output}") from exc
        return metadata


def main() -> int:
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="下载单条公开抖音视频（独立浏览器配置）")
    parser.add_argument("input", help="抖音链接、含链接的分享文案或纯视频 ID")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", "-o", type=Path, help="目标 MP4 文件的完整路径")
    destination.add_argument("--output-dir", type=Path, help="输出目录；默认 Downloads/douyin")
    parser.add_argument("--profile-dir", type=Path,
                        default=default_profile_dir(),
                        help="本脚本专用 Chrome 配置目录，不使用用户现有配置")
    parser.add_argument("--ratio", choices=("1080p", "720p", "540p", "480p", "360p"), default="720p")
    parser.add_argument("--probe-only", action="store_true", help="仅解析视频信息，不下载媒体")
    args = parser.parse_args()

    stage = "解析抖音分享链接"
    try:
        aweme_id = resolve_aweme_id(args.input)
        if not args.probe_only:
            output = args.output or (args.output_dir or Path.home() / "Downloads" / "douyin") / f"{aweme_id}.mp4"
            if output.exists():
                raise DownloadError(f"目标文件已存在，未覆盖：{output}")
        stage = "独立浏览器读取播放信息"
        video_id, description = extract_video_id(aweme_id, args.profile_dir)
        if args.probe_only:
            print(json.dumps({"aweme_id": aweme_id, "video_id": video_id, "description": description}, ensure_ascii=True))
            return 0
        stage = "下载和验证媒体"
        play_url = build_play_url(video_id, args.ratio)
        metadata = download_media(play_url, output)
    except DownloadError as exc:
        print(f"下载失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"下载失败：{stage}阶段发生 {type(exc).__name__}。", file=sys.stderr)
        return 1

    streams = metadata.get("streams", [])
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    print(json.dumps({
        "path": str(output.resolve()),
        "aweme_id": aweme_id,
        "size_bytes": output.stat().st_size,
        "duration_seconds": float(metadata.get("format", {}).get("duration", 0)),
        "resolution": f"{video.get('width')}x{video.get('height')}",
        "video_codec": video.get("codec_name"),
        "audio_codecs": [stream.get("codec_name") for stream in streams if stream.get("codec_type") == "audio"],
        "description": description,
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
