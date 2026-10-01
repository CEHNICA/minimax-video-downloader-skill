"""Download one public Bilibili video with yt-dlp.

Bilibili's CDN answers 503 for unauthenticated AV1 streams, so yt-dlp's
default `bv*` selector can pick a format that never finishes downloading
while the audio stream succeeds. This script prefers H.264, then H.265, and
only falls back to any codec as a last resort. It never reads cookies from
the user's browser.

Dependencies: Python yt-dlp, ffprobe.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


ALLOWED_HOSTS = ("bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv", "www.b23.tv")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
URL_PATTERN = re.compile(r"https?://[^\s<>\"'\[\]（），。；！？]+", re.I)
VIDEO_PATH = re.compile(r"^/video/((?:BV[0-9A-Za-z]{10})|(?:av\d+))/?$", re.I)
SHORT_PATH = re.compile(r"^/([0-9A-Za-z]{4,32})/?$")
BV_ID = re.compile(r"^BV[0-9A-Za-z]{10}$", re.I)
AV_ID = re.compile(r"^av\d+$", re.I)
QUALITY_HEIGHTS = {"1080": 1080, "720": 720, "480": 480, "360": 360}
CODEC_PREFERENCE = ("avc1", "hvc1")
QUALITY_CHOICES = (*QUALITY_HEIGHTS, "best")
MAX_SHORTLINK_REDIRECTS = 8


class DownloadError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SafeYtdlpLogger:
    """Keep yt-dlp chatter out of the report and out of share links."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        print(message, file=sys.stderr)

    def error(self, message: str) -> None:
        print(message, file=sys.stderr)


def default_output_dir() -> Path:
    return Path.home() / "Downloads" / "bilibili"


def _validate(url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
        allowed = (parsed.scheme == "https"
                   and (parsed.hostname or "").lower() in ALLOWED_HOSTS
                   and parsed.username is None and parsed.password is None
                   and parsed.port is None and not parsed.fragment)
    except ValueError:
        allowed = False
    if not allowed or "\\" in url or any(ord(char) < 32 for char in url):
        raise DownloadError("只接受 HTTPS 的 bilibili.com 或 b23.tv 视频链接")


def _video_id_from_url(url: str) -> str | None:
    _validate(url)
    path = urllib.parse.urlsplit(url).path
    match = VIDEO_PATH.fullmatch(path)
    if match:
        return match.group(1)
    return None


def _follow_shortlink(url: str) -> str:
    opener = urllib.request.build_opener(NoRedirect())
    current = url
    for _ in range(MAX_SHORTLINK_REDIRECTS + 1):
        _validate(current)
        if _video_id_from_url(current):
            break
        if (urllib.parse.urlsplit(current).hostname or "").lower().endswith("b23.tv"):
            if not SHORT_PATH.fullmatch(urllib.parse.urlsplit(current).path):
                raise DownloadError("b23.tv 短链格式无法识别")
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=20) as response:
                current = response.geturl()
        except urllib.error.HTTPError as error:
            code = error.code
            location = error.headers.get("Location")
            error.close()
            if code not in (301, 302, 303, 307, 308) or not location:
                raise DownloadError(f"短链解析失败（HTTP {code}）") from None
            if any(ord(char) < 32 for char in location):
                raise DownloadError("短链返回无效跳转地址")
            current = urllib.parse.urljoin(current, location)
    else:
        raise DownloadError("短链跳转次数过多")
    video_id = _video_id_from_url(current)
    if not video_id:
        raise DownloadError("短链跳转后没有找到 BV 号")
    return video_id


def resolve_video_id(value: str) -> str:
    value = value.strip()
    if BV_ID.fullmatch(value) or AV_ID.fullmatch(value):
        return value
    match = URL_PATTERN.search(value)
    if not match:
        raise DownloadError("没有找到 B 站链接或 BV 号")
    url = match.group(0).rstrip("'\"),.;!?/）】")
    _validate(url)
    video_id = _video_id_from_url(url)
    if video_id:
        return video_id
    if (urllib.parse.urlsplit(url).hostname or "").lower().endswith("b23.tv"):
        return _follow_shortlink(url)
    raise DownloadError("链接里没有 BV 号或 av 号")


def canonical_url(video_id: str) -> str:
    if not (BV_ID.fullmatch(video_id) or AV_ID.fullmatch(video_id)):
        raise DownloadError("视频编号格式不正确")
    return f"https://www.bilibili.com/video/{video_id}/"


def build_format(quality: str) -> str:
    """Prefer H.264, then H.265, and only then anything else.

    AV1 is listed last on purpose: Bilibili's CDN returns 503 for it when the
    request is not authenticated, and a failed video stream is not recoverable
    by retrying.
    """
    limit = QUALITY_HEIGHTS.get(quality)
    height = f"[height<={limit}]" if limit else ""
    selectors = [f"bv*[vcodec^={codec}]{height}+ba/b" for codec in CODEC_PREFERENCE]
    selectors.append(f"bv*{height}+ba")
    return "/".join(selectors)


def inspect_media(path: Path) -> dict:
    probe = shutil.which("ffprobe")
    if not probe:
        raise DownloadError("缺少 ffprobe，无法验证下载文件")
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=format_name,duration,size",
         "-show_entries", "stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode:
        raise DownloadError("下载文件无法通过 ffprobe 验证")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise DownloadError("下载文件中没有视频轨道")
    if "mp4" not in data.get("format", {}).get("format_name", "").split(","):
        raise DownloadError("下载文件不是 MP4 容器")
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    if not 0 < duration < float("inf"):
        raise DownloadError("下载文件没有有效时长")
    return {
        "duration_seconds": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codecs": [s.get("codec_name") for s in streams if s.get("codec_type") == "audio"],
    }


def windows_safe_title(title: str) -> str:
    """Match the reserved characters yt-dlp strips, so the name we predict here
    is the name yt-dlp actually produces."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)[:80].rstrip(" .")
    return cleaned or "video"


def stage_download(ydl, info: dict, target: Path) -> tuple[Path, dict]:
    """Download into a sibling temp file, verify it, then link it into place.

    `outtmpl` is normalised to a dict by YoutubeDL, so the staging template has
    to be written in the same shape. A file that fails verification is dropped
    with the temp directory and never reaches the output directory. The final
    name comes from the file yt-dlp really wrote, not from a guess.
    """
    with tempfile.TemporaryDirectory(prefix="bilibili-", dir=target.parent) as stage_dir:
        stage_root = Path(stage_dir) / "media"
        ydl.params["outtmpl"] = {"default": str(stage_root / "%(title).80s [%(id)s].%(ext)s")}
        ydl.process_ie_result(info, download=True)
        produced = next((p for p in sorted(stage_root.rglob("*")) if p.is_file()), None)
        if produced is None:
            raise DownloadError("下载没有产生文件")
        if produced.stat().st_size < 1024:
            raise DownloadError("下载文件过小，不是有效视频")
        metadata = inspect_media(produced)
        final = target.parent / produced.name
        if final.exists():
            raise DownloadError(f"目标文件已存在，未覆盖：{final}")
        try:
            os.link(produced, final)
        except FileExistsError:
            raise DownloadError(f"目标文件已存在，未覆盖：{final}") from None
    return final, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="下载单条公开 B 站视频（不使用浏览器 Cookie）")
    parser.add_argument("input", help="B 站链接、b23.tv 短链、含链接的分享文案或纯 BV/av 号")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir(), help="输出目录；默认 Downloads/bilibili")
    parser.add_argument("--quality", choices=QUALITY_CHOICES, default="best",
                        help="最高画质上限；默认 best（仍优先 H.264）")
    parser.add_argument("--probe-only", action="store_true", help="只解析视频信息，不下载媒体")
    args = parser.parse_args()

    try:
        import yt_dlp
        from yt_dlp.version import __version__
    except ImportError:
        print("缺少 yt-dlp。运行：python -m pip install -U yt-dlp", file=sys.stderr)
        return 2

    stage = "解析 B 站链接"
    try:
        video_id = resolve_video_id(args.input)
        url = canonical_url(video_id)
        if not shutil.which("ffprobe"):
            raise DownloadError("缺少 ffprobe，无法验证下载文件")
        stage = "读取视频信息"
        options = {
            "noplaylist": True,
            "format": build_format(args.quality),
            "merge_output_format": "mp4",
            "windowsfilenames": True,
            "continuedl": True,
            "socket_timeout": 20,
            "retries": 3,
            "fragment_retries": 3,
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "logger": SafeYtdlpLogger(),
            "http_headers": {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"},
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise DownloadError("未取得视频信息")
            report = {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration_seconds": info.get("duration"),
                "quality": args.quality,
                "yt_dlp_version": __version__,
            }
            if args.probe_only:
                report["formats"] = [
                    {k: f.get(k) for k in ("format_id", "width", "height", "vcodec", "acodec", "filesize")}
                    for f in info.get("formats", [])
                ]
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0
            if not info.get("title"):
                raise DownloadError("视频没有可用标题，拒绝用不确定的文件名保存")
            output_dir = args.output_dir.resolve()
            target = output_dir / f"{windows_safe_title(info['title'])} [{video_id}].mp4"
            if target.exists():
                raise DownloadError(f"目标文件已存在，未覆盖：{target}")
            output_dir.mkdir(parents=True, exist_ok=True)
            stage = "下载和验证媒体"
            path, metadata = stage_download(ydl, info, target)
    except DownloadError as exc:
        print(f"下载失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - report the failing stage instead of a traceback
        print(f"下载失败：{stage}阶段发生 {type(exc).__name__}。", file=sys.stderr)
        return 1

    report.update({
        "path": str(path),
        "size_bytes": path.stat().st_size,
        **metadata,
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
