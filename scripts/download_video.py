"""Choose the installed single-video downloader from a supplied share link."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


URLS = re.compile(r"https?://[^\s<>\"'\[\]（），。；！？]+", re.IGNORECASE)
SPH_PATH = re.compile(r"^/sph/[A-Za-z0-9_-]{6,64}/?$")


def platform_for_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            return None
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if host in ("xhslink.cn", "xhslink.com", "xiaohongshu.com") or host.endswith(".xiaohongshu.com"):
        return "xiaohongshu"
    if (parsed.scheme == "https" and host == "weixin.qq.com" and parsed.port is None
            and not parsed.fragment and SPH_PATH.fullmatch(parsed.path)):
        return "wechat-channels"
    if host in ("douyin.com", "www.douyin.com", "m.douyin.com", "v.douyin.com",
                "iesdouyin.com", "www.iesdouyin.com"):
        return "douyin"
    if host in ("bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv", "www.b23.tv"):
        return "bilibili"
    return None


def choose_share(share: str) -> tuple[str, str]:
    choices: dict[str, str] = {}
    for match in URLS.finditer(share):
        url = match.group(0).rstrip(").,;!?:）。，；！？")
        platform = platform_for_url(url)
        if platform:
            choices[url] = platform
    if not choices:
        raise ValueError("未找到支持的视频链接。当前支持小红书、微信视频号、抖音和哔哩哔哩分享链接。")
    if len(choices) != 1:
        raise ValueError("发现多条视频链接，请一次只提供一条。")
    url, platform = next(iter(choices.items()))
    return platform, url


def choose_platform(share: str) -> str:
    return choose_share(share)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="按分享链接平台下载一条视频。")
    parser.add_argument("share", help="视频分享链接或包含该链接的文案")
    parser.add_argument("--output-dir", type=Path, help="指定保存目录；省略时沿用各平台原有默认目录")
    parser.add_argument("--probe-only", action="store_true", help="只检查是否可解析，不下载")
    parser.add_argument("--cookies", type=Path, help="仅供小红书使用，且须由用户明确提供")
    parser.add_argument("--profile-dir", type=Path, help="仅供抖音使用的独立 Chrome 配置目录")
    parser.add_argument("--ratio", choices=("1080p", "720p", "540p", "480p", "360p"), help="仅供抖音使用的视频画质")
    parser.add_argument("--quality", choices=("best", "1080", "720", "480", "360"), help="仅供哔哩哔哩使用的画质上限")
    args = parser.parse_args()
    platform, selected_url = choose_share(args.share)
    if args.cookies and platform != "xiaohongshu":
        raise ValueError("--cookies 只用于小红书；其他平台不读取 Cookie。")
    if (args.profile_dir or args.ratio) and platform != "douyin":
        raise ValueError("--profile-dir 和 --ratio 只用于抖音。")
    if args.quality and platform != "bilibili":
        raise ValueError("--quality 只用于哔哩哔哩。")
    script = Path(__file__).resolve().parent / {
        "xiaohongshu": "download_xhs.py",
        "wechat-channels": "download_wechat_channels.py",
        "douyin": "download_douyin.py",
        "bilibili": "download_bilibili.py",
    }[platform]
    command = [sys.executable, str(script), selected_url]
    if args.output_dir:
        command.extend(["--output-dir", str(args.output_dir)])
    if args.probe_only:
        command.append("--probe-only")
    if args.cookies:
        command.extend(["--cookies", str(args.cookies)])
    if args.profile_dir:
        command.extend(["--profile-dir", str(args.profile_dir)])
    if args.ratio:
        command.extend(["--ratio", args.ratio])
    if args.quality:
        command.extend(["--quality", args.quality])
    print(f"已识别平台：{platform}。", file=sys.stderr)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"未完成下载：{error}", file=sys.stderr)
        raise SystemExit(2)
