---
name: video-downloader
description: 下载单条小红书、微信视频号、抖音或哔哩哔哩公开视频。用户给出 xhslink.cn、xhslink.com、xiaohongshu.com、weixin.qq.com/sph、v.douyin.com、douyin.com、iesdouyin.com、bilibili.com、b23.tv 分享链接并要求下载、保存、检查能否下载时使用；也接受包含链接的分享文案。只讨论视频内容、批量采集抖音推荐流或制作总结报告时不触发。
---

# 单条视频下载

运行 `scripts/download_video.py`，由它根据用户提供的链接选择平台脚本。用户已经给出有效链接时直接处理，不要求重复复制。默认沿用各平台目录：`Downloads\xiaohongshu`、`Downloads\wechat-channels`、`Downloads\douyin` 和 `Downloads\bilibili`。

```powershell
$videoScript = Join-Path $env:USERPROFILE '.minimax\skills\video-downloader\scripts\download_video.py'
python -X utf8 $videoScript '用户提供的分享链接或文案'
```

指定位置时追加 `--output-dir '目标目录'`；只检查能否解析时追加 `--probe-only`。小红书只有在用户明确提供 Netscape 格式 Cookie 文件并要求使用时才传 `--cookies '文件路径'`。视频号、抖音和哔哩哔哩都不读取用户浏览器 Cookie。使用参数数组执行，不能把分享文案拼进可执行命令文本。

## 平台边界

- **小红书：**保留短链跳转后的完整笔记参数，包括 `xsec_token`，再由 `yt-dlp` 提取视频。不要默认读取浏览器 Cookie。`--probe-only` 会列出可用格式。需要 Python 中的 `yt-dlp`；有 `ffprobe` 时检查实际音视频，没有时必须明确说尚未验证。
- **哔哩哔哩：**接受 `bilibili.com/video/...`、`b23.tv` 短链、纯 BV 或 av 号。`--quality 1080|720|480|360|best` 设定画质上限，默认 `best`；`--probe-only` 列出全部可用格式。**必须使用脚本自带的选择器而不是 yt-dlp 默认的 `bv*+ba`**：B 站 CDN 对未登录的 AV1 视频流持续返回 503，音频能下完而视频流为 0 字节，重试无效。脚本因此固定按 H.264 → H.265 → 任意编码的顺序选择，AV1 只作最后兜底。1080P 高码率和 4K 需要大会员，缺失时属正常情况，不要改用 Cookie 绕过。需要 Python `yt-dlp` 和 `ffprobe`，缺少 `ffprobe` 时不下载。
- **微信视频号：**只接受 `https://weixin.qq.com/sph/...`。完整公开分享 URL 会发给第三方解析服务 `v.mtotech.com`，应在执行时简要告知用户；用户已要求下载时直接继续。视频文件只从 `finder.video.qq.com` 下载，不跟随跨域跳转，不输出或保存临时签名直链。`--probe-only` 仅报告是否解析成功。需要 `ffprobe`，缺少时不能宣称完成下载。[第三方服务说明](https://v.mtotech.com/)。
- **抖音：**脚本从分享链接取得作品 ID，使用独立、持久的 Chrome 配置以手机视图打开公开视频并读取播放器信息，再下载到临时目录。此过程会短暂显示另一个 Chrome 窗口，但不会关闭用户现有窗口、读取用户默认浏览器 Cookie 或修改代理。只关闭脚本自己启动的窗口。专用配置会保留运行时产生的浏览器数据；如需清理，可在脚本结束后删除 `%LOCALAPPDATA%\MiniMax\video-downloader\douyin-chrome-profile`。最多尝试 4 次；没有视频时准确失败，不默认要求用户导出 Cookie。需要 Python `playwright`、Google Chrome、`yt-dlp` 和 `ffprobe`；缺少依赖时说明原因，不自行安装系统软件。`--probe-only` 仍会打开独立浏览器，但不会下载视频。可用 `--profile-dir '专用目录'` 指定独立配置、`--ratio 1080p` 请求画质；默认请求 720p。`douyin-batch-summary` 是另一项采集与报告任务，独立使用。

## 完成与失败

交付实际文件路径、时长、分辨率、文件大小和音频轨道情况；只下载时不自行转写或分析。下载后检查文件，不把封面、网页、空文件或 `.part` 当成视频。若解析失败、链接受限、需要登录或依赖缺失，说明具体失败阶段并停止重复尝试。不要改变浏览器、系统代理或证书配置来完成普通下载。

小红书脚本会生成同名 `.download.json`；其中的来源链接只保留去掉查询参数的地址，避免把 `xsec_token` 写入结果文件。维护小红书提取器时再阅读 [研究记录](references/xiaohongshu-research.md)。

2026-09-24 使用一条公开抖音链接实测下载，所得 MP4 包含 H.264 视频和 AAC 音频，并通过全片解码。此单例不保证其他链接都能解析；直接把分享短链交给 yt-dlp 在本次测试中失败。

2026-10-01 使用一条公开 B 站链接实测：`--probe-only` 正常列出格式，`--quality 720` 得到 1280x536 H.264 + AAC MP4，重复下载被正确拒绝，默认的 `bv*+ba` 选择器在同一条链接上会因 AV1 持续 503 而失败。
