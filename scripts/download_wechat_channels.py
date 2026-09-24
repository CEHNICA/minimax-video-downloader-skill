"""Download a public WeChat Channels sph share, without exposing signed media URLs."""

from __future__ import annotations

import argparse
import hashlib
import http.client
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


RESOLVER_URL = "https://v.mtotech.com/api/resolve"
MEDIA_HOST = "finder.video.qq.com"
SHARE_HOST = "weixin.qq.com"
SHARE_PATH = re.compile(r"^/sph/([A-Za-z0-9_-]{6,64})/?$")
URL_IN_TEXT = re.compile(r"https://[^\s<>\"'\[\]（），。；！？]+", re.I)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
CHUNK_SIZE = 1024 * 1024


class DownloadError(Exception):
    """A user-facing error that contains no signed media URL."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _parts(url: str) -> urllib.parse.SplitResult:
    try:
        return urllib.parse.urlsplit(url)
    except ValueError as error:
        raise DownloadError("链接格式无效。") from error


def extract_share_url(text: str) -> tuple[str, str]:
    """Return only a validated public sph URL and its sharing code."""
    for match in URL_IN_TEXT.finditer(text):
        candidate = match.group(0).rstrip(").,;!?:）。，；！？")
        if len(candidate) > 2048:
            continue
        parts = _parts(candidate)
        try:
            safe_origin = (parts.scheme.lower() == "https" and (parts.hostname or "").lower() == SHARE_HOST
                           and parts.username is None and parts.password is None
                           and parts.port is None and not parts.fragment)
        except ValueError:
            continue
        if not safe_origin:
            continue
        path_match = SHARE_PATH.fullmatch(parts.path)
        if path_match:
            clean = urllib.parse.urlunsplit(("https", SHARE_HOST, parts.path, parts.query, ""))
            return clean, path_match.group(1)
    raise DownloadError("未找到有效的微信视频号 sph 公共分享链接。")


def validate_media_url(url: object) -> str:
    """Reject arbitrary resolver-selected destinations, including lookalike hosts."""
    if not isinstance(url, str) or len(url) > 8192:
        raise DownloadError("解析服务没有返回可用的视频地址。")
    parts = _parts(url)
    try:
        safe_origin = (parts.scheme.lower() == "https" and (parts.hostname or "").lower() == MEDIA_HOST
                       and parts.username is None and parts.password is None
                       and parts.port is None and not parts.fragment)
    except ValueError:
        safe_origin = False
    if not safe_origin or any(ord(char) < 32 for char in url):
        raise DownloadError("解析服务返回了非微信视频域名，已停止下载。")
    return url


def _open_no_redirect(request: urllib.request.Request, timeout: int):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


def resolve_video(share_url: str) -> str:
    payload = json.dumps({"url": share_url}).encode("utf-8")
    request = urllib.request.Request(
        RESOLVER_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with _open_no_redirect(request, 30) as response:
            if response.status != 200:
                raise DownloadError(f"解析服务返回 HTTP {response.status}。")
            length_header = response.headers.get("Content-Length", "")
            if length_header.isdigit() and int(length_header) > 2_000_000:
                raise DownloadError("解析服务响应过大，已停止。")
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise DownloadError(f"解析服务返回 HTTP {code}。") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        raise DownloadError("无法连接解析服务，请稍后再试。") from None
    if len(raw) > 2_000_000:
        raise DownloadError("解析服务响应过大，已停止。")
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise DownloadError("解析服务没有返回有效 JSON。") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise DownloadError("解析服务未能解析此视频（ok 不是 true）。链接可能失效、私密或已删除。")
    data = body.get("data")
    if not isinstance(data, dict):
        raise DownloadError("解析服务响应缺少视频资料。")
    return validate_media_url(data.get("h264_url"))


def inspect_media(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise DownloadError("未找到 ffprobe，无法验证视频；请安装 ffmpeg 并将 ffprobe 加入 PATH。")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration,format_name:stream=codec_type,codec_name,width,height",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DownloadError("ffprobe 无法读取下载文件。") from None
    if result.returncode:
        raise DownloadError("ffprobe 无法识别下载文件，可能不是完整视频。")
    try:
        info = json.loads(result.stdout)
        duration = float(info.get("format", {}).get("duration", 0))
        formats = info.get("format", {}).get("format_name", "").split(",")
        streams = info.get("streams", [])
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        raise DownloadError("ffprobe 没有返回有效的媒体信息。") from None
    if not isinstance(streams, list) or any(not isinstance(stream, dict) for stream in streams):
        raise DownloadError("ffprobe 没有返回有效的媒体轨道信息。")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not videos or not (0 < duration < float("inf")):
        raise DownloadError("下载文件没有有效的视频轨道或时长。")
    if "mp4" not in formats:
        raise DownloadError("下载文件不是可识别的 MP4 视频。")
    return {
        "duration_seconds": round(duration, 3),
        "width": videos[0].get("width"),
        "height": videos[0].get("height"),
        "video_codec": videos[0].get("codec_name"),
        "audio_codecs": [stream.get("codec_name") for stream in streams if stream.get("codec_type") == "audio"],
    }


def download_video(media_url: str, destination: Path) -> dict:
    """Stream into a disposable local file; publish it only after media validation."""
    if not shutil.which("ffprobe"):
        raise DownloadError("未找到 ffprobe，无法验证视频；请安装 ffmpeg 并将 ffprobe 加入 PATH。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise DownloadError(f"目标文件已存在：{destination}。请指定其他目录，避免覆盖。")
    handle, temp_name = tempfile.mkstemp(prefix=f".{destination.stem}.", suffix=".part", dir=destination.parent)
    os.close(handle)
    temp_path = Path(temp_name)
    digest = hashlib.sha256()
    total = 0
    try:
        request = urllib.request.Request(
            validate_media_url(media_url),
            headers={"User-Agent": USER_AGENT, "Referer": "https://weixin.qq.com/"},
        )
        try:
            with _open_no_redirect(request, 60) as response:
                if response.status != 200:
                    raise DownloadError(f"视频服务器返回 HTTP {response.status}。")
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if media_type in ("text/html", "application/json", "text/plain"):
                    raise DownloadError("视频服务器返回的是网页或错误信息，不是视频。")
                length_header = response.headers.get("Content-Length")
                expected = int(length_header) if length_header and length_header.isdigit() else None
                with temp_path.open("wb") as target:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
                        digest.update(chunk)
                        total += len(chunk)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise DownloadError(f"视频服务器返回 HTTP {code}。") from None
        except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError, ConnectionError):
            raise DownloadError("视频服务器连接失败或下载中断。") from None
        if total == 0 or (expected is not None and total != expected):
            raise DownloadError("视频下载不完整，已丢弃临时文件。")
        media = inspect_media(temp_path)
        temp_path.rename(destination)
        return {"path": str(destination.resolve()), "size_bytes": total, "sha256": digest.hexdigest(), **media}
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载微信视频号 sph 公开视频；分享链接会发送给第三方解析服务。")
    parser.add_argument("share", help="用户提供的 sph 分享链接或含链接的分享文案")
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "Downloads" / "wechat-channels")
    parser.add_argument("--probe-only", action="store_true", help="只查询是否可解析，不下载视频")
    args = parser.parse_args()
    share_url, share_code = extract_share_url(args.share)
    media_url = resolve_video(share_url)
    if args.probe_only:
        summary = {"status": "resolved", "share_code": share_code, "media_host": MEDIA_HOST, "downloaded": False}
    else:
        summary = {"status": "downloaded", "share_code": share_code,
                   **download_video(media_url, args.output_dir / f"{share_code}.mp4")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except DownloadError as error:
        print(f"未完成下载：{error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("下载已取消，临时文件已清理。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        # In particular, never print urllib's raw exception text: it can contain the signed URL.
        print(f"未完成下载：出现未预期的 {type(error).__name__}。", file=sys.stderr)
        raise SystemExit(1)
