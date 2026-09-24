"""Resolve Xiaohongshu shares and download via the installed yt-dlp package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT_DOMAINS = ("xiaohongshu.com", "xhslink.com", "xhslink.cn")
NOTE_PATH = re.compile(r"^/(?:explore|discovery/item)/([0-9a-f]+)(?:/)?$")
URL_PATTERN = re.compile(r"https?://[^\s<>\"'\[\]（），。；！？]+", re.I)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def redact_share_parameters(message: str) -> str:
    def clean(match: re.Match[str]) -> str:
        try:
            parts = urllib.parse.urlsplit(match.group(0))
            return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except ValueError:
            return "[链接已省略]"

    without_url_queries = URL_PATTERN.sub(clean, message)
    return re.sub(r"xsec_token=[^&\s]+", "xsec_token=[已省略]", without_url_queries)


class SafeYtdlpLogger:
    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        print(redact_share_parameters(message), file=sys.stderr)

    def error(self, message: str) -> None:
        print(redact_share_parameters(message), file=sys.stderr)


def platform_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme in ("http", "https") and not parsed.username
            and not parsed.password and parsed.port in (None, 80, 443)
            and any(host == d or host.endswith("." + d) for d in ROOT_DOMAINS))


def extract_url(text: str) -> str:
    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(").,;!?:")
        if platform_url(url):
            return url
    raise ValueError("未找到小红书链接；请保留原始分享链接及其参数。")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_note(url: str, timeout: int = 20) -> str:
    """Stop at the first real note URL, before the website redirects to login."""
    opener = urllib.request.build_opener(NoRedirect())
    for _ in range(8):
        if not platform_url(url):
            raise ValueError("分享链接跳到了非小红书域名，已停止。")
        parsed = urllib.parse.urlsplit(url)
        if parsed.hostname in ("www.xiaohongshu.com", "xiaohongshu.com"):
            if NOTE_PATH.fullmatch(parsed.path):
                # Preserve the entire query, notably xsec_token and xsec_source.
                return urllib.parse.urlunsplit(("https", "www.xiaohongshu.com", parsed.path, parsed.query, ""))
            if parsed.path == "/login":
                target = urllib.parse.parse_qs(parsed.query).get("redirectPath", [None])[0]
                if target:
                    url = urllib.parse.urljoin(url, target)
                    continue
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout) as response:
                # Do not execute embedded page JavaScript or invent API signatures.
                raise ValueError(f"分享链接未返回笔记跳转（HTTP {response.status}）；请重新复制完整分享链接。")
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                exc.close()
                continue
            code = exc.code
            exc.close()
            raise ValueError(f"解析短链失败（HTTP {code}）；链接可能失效或需要登录。") from None
    raise ValueError("分享链接跳转次数过多，已停止。")


def inspect_media(path: Path) -> dict:
    probe = shutil.which("ffprobe")
    if not probe:
        return {"media_validation": "unavailable: ffprobe not installed"}
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
         "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", timeout=45)
    if result.returncode:
        raise ValueError("文件已保存，但 ffprobe 验证失败，不能报告下载成功。")
    data = json.loads(result.stdout)
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not videos:
        raise ValueError("文件中没有可识别的视频轨道。")
    return {"media_validation": "passed", "duration_seconds": float(data.get("format", {}).get("duration", 0)),
            "width": videos[0].get("width"), "height": videos[0].get("height"),
            "video_codec": videos[0].get("codec_name"),
            "audio_codecs": [s.get("codec_name") for s in data.get("streams", []) if s.get("codec_type") == "audio"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="下载小红书视频；支持短链、完整链接和整段分享文案。")
    parser.add_argument("share", help="原始 URL 或分享文案")
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "Downloads" / "xiaohongshu")
    parser.add_argument("--probe-only", action="store_true", help="只解析标题、时长、画质，不下载视频")
    parser.add_argument("--cookies", type=Path, help="仅使用用户明确提供的小红书 Netscape Cookie 文件")
    args = parser.parse_args()
    try:
        import yt_dlp
        from yt_dlp.version import __version__
    except ImportError:
        print("缺少 yt-dlp。运行：python -m pip install -U yt-dlp", file=sys.stderr)
        return 2
    original = extract_url(args.share)
    resolved = resolve_note(original)
    print("已解析到小红书笔记，保留分享参数。", file=sys.stderr)
    if args.cookies and not args.cookies.is_file():
        raise ValueError("指定的 Cookie 文件不存在。")
    opts = {
        "noplaylist": True, "format": "best[ext=mp4]/best",
        "outtmpl": str(args.output_dir.resolve() / "%(title).80s [%(id)s].%(ext)s"),
        "windowsfilenames": True, "overwrites": False, "continuedl": True,
        "socket_timeout": 20, "retries": 1, "fragment_retries": 1,
        "noprogress": True, "quiet": True, "logger": SafeYtdlpLogger(),
        "http_headers": {"User-Agent": USER_AGENT, "Referer": "https://www.xiaohongshu.com/"},
    }
    if args.cookies:
        opts["cookiefile"] = str(args.cookies.resolve())
    if not args.probe_only:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(resolved, download=not args.probe_only)
        if not info:
            raise ValueError("未取得视频信息。")
        # The share query can carry xsec_token; it is needed for extraction,
        # but should not persist in the downloaded metadata or terminal output.
        source = urllib.parse.urlsplit(original)
        public_source_url = urllib.parse.urlunsplit((source.scheme, source.netloc, source.path, "", ""))
        summary = {"id": info.get("id"), "title": info.get("title"), "source_url": public_source_url,
                   "note_url": resolved.split("?")[0], "yt_dlp_version": __version__,
                   "duration_seconds": info.get("duration"), "width": info.get("width"), "height": info.get("height")}
        if args.probe_only:
            summary["formats"] = [{k: f.get(k) for k in ("format_id", "width", "height", "vcodec", "acodec", "filesize")}
                                  for f in info.get("formats", [])]
        else:
            path = Path(ydl.prepare_filename(info)).resolve()
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("下载没有产生有效文件。")
            summary.update({"path": str(path), "size_bytes": path.stat().st_size})
            summary.update(inspect_media(path))
            with path.open("rb") as handle:
                summary["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
            path.with_suffix(".download.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as error:
        safe_error = redact_share_parameters(str(error))
        print(f"未完成下载：{safe_error}\n若提示登录、验证码或没有视频流，请停止重试；重新取得有效分享链接，或在用户授权后提供 Cookie。", file=sys.stderr)
        raise SystemExit(1)
