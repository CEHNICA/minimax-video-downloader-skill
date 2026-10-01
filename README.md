# MiniMax 单条视频下载技能

这是一个供 MiniMax 使用的 `video-downloader` Skill，也可以直接运行 Python 脚本。它从分享链接或整段分享文案中识别平台，下载**单条公开**的小红书、微信视频号、抖音或哔哩哔哩视频，并检查保存的文件。项目不包含视频文件、账号资料或浏览器 Cookie。

| 平台 | 接受的分享链接 | 处理方式 |
| --- | --- | --- |
| 小红书 | `xhslink.cn`、`xhslink.com`、`xiaohongshu.com` | 解析短链，保留笔记所需参数，再使用 `yt-dlp`。 |
| 微信视频号 | `https://weixin.qq.com/sph/...` | 将完整分享 URL 交给第三方解析服务，再从微信视频域名下载。见[数据流说明](#数据流与浏览器配置)。 |
| 抖音 | `v.douyin.com`、`douyin.com`、`iesdouyin.com` | 用独立的 Chrome 配置读取公开视频播放信息，再使用 `yt-dlp` 下载。 |
| 哔哩哔哩 | `bilibili.com/video/...`、`b23.tv`、纯 BV 或 av 号 | 先解析 BV 号，再用 `yt-dlp` 下载；见[画质选择](#哔哩哔哩画质选择)。 |

一次只处理一条链接；如果文案里有多条受支持的视频链接，脚本会要求重新选择。只讨论视频内容、批量采集或制作报告的任务不属于这个 Skill。

## 安装

以下步骤面向 Windows PowerShell。需要 **Python 3.11 或更新版本**、Google Chrome，以及加入 `PATH` 的 `ffprobe`（随 FFmpeg 提供）。抖音下载还需要能从命令行运行 `yt-dlp`。Python 包列在 [`requirements.txt`](requirements.txt) 中。

```powershell
git clone https://github.com/CEHNICA/minimax-video-downloader-skill.git
Set-Location .\minimax-video-downloader-skill
python -m pip install -r .\requirements.txt

$skillDir = Join-Path $env:USERPROFILE '.minimax\skills\video-downloader'
New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $skillDir 'scripts') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $skillDir 'references') | Out-Null
Copy-Item .\SKILL.md $skillDir -Force
Copy-Item .\scripts\*.py (Join-Path $skillDir 'scripts') -Force
Copy-Item .\references\*.md (Join-Path $skillDir 'references') -Force
```

安装后可检查依赖是否可用：

```powershell
python --version
python -c "import yt_dlp; import playwright"
yt-dlp --version
ffprobe -version
```

Google Chrome 需要已安装在系统中。`playwright` 会为抖音脚本启动一个单独的可见 Chrome 窗口；不要求使用日常浏览器配置。只有抖音脚本需要 Chrome，其余平台不需要浏览器。若 MiniMax 没有立即识别新 Skill，可重启 MiniMax 后再试。

## 使用

在 MiniMax 中发送一条受支持的视频分享链接，并说“下载这个视频”。也可以直接运行统一入口：

```powershell
$script = Join-Path $env:USERPROFILE '.minimax\skills\video-downloader\scripts\download_video.py'
$share = Read-Host '粘贴小红书、视频号、抖音或哔哩哔哩分享链接/文案'
python -X utf8 $script $share
```

默认保存到用户的 `Downloads\xiaohongshu`、`Downloads\wechat-channels`、`Downloads\douyin` 或 `Downloads\bilibili`。需要先检查链接时使用 `--probe-only`；需要自行指定目录时使用 `--output-dir`：

```powershell
python -X utf8 $script $share --probe-only
python -X utf8 $script $share --output-dir (Join-Path $env:USERPROFILE 'Downloads\saved-videos')
```

小红书只有在你自己决定使用、并提供 Netscape 格式 Cookie 文件时才传 `--cookies '文件路径'`。抖音可用 `--ratio 1080p` **请求**画质，实际画质以平台返回的视频为准；`--profile-dir '专用目录'` 可改变其独立浏览器配置的位置。这两个选项只适用于抖音。哔哩哔哩用 `--quality 720` 设定画质上限，该选项只适用于哔哩哔哩。`--probe-only` 不下载媒体文件，但抖音仍会启动该独立浏览器，视频号仍会请求第三方解析服务。

脚本会输出实际保存路径和可取得的媒体信息。小红书另写入同名 `.download.json`；其中来源链接不保留查询参数。视频号、抖音和哔哩哔哩遇到同名现有文件时会停止，小红书则使用 `yt-dlp` 的非覆盖设置。

## 哔哩哔哩画质选择

B 站同一分辨率通常同时提供 H.264、H.265 和 AV1 三种编码。**不要直接用 `yt-dlp` 的默认选择器**：`bv*+ba` 可能挑中 AV1 档，而 B 站 CDN 对未登录的 AV1 视频流持续返回 `503 Service Unavailable`，结果是音频正常下完、视频流停在 0 字节，重试多次仍然失败。

`download_bilibili.py` 因此固定按 **H.264 → H.265 → 任意编码** 的顺序选择，AV1 只作最后兜底。`--quality` 只在此顺序上叠加高度上限：

| 参数 | 实际含义 |
| --- | --- |
| `--quality best`（默认） | 最高可用画质，仍优先 H.264。 |
| `--quality 1080` | 限制到 1080 及以下，例如电影宽度的 1920x804。 |
| `--quality 720` | 限制到 720 及以下。 |

1080P 高码率和 4K 属于大会员内容，未登录时不会出现在格式列表中，这是正常现象；本项目不为此读取浏览器 Cookie。想确认当前可用格式时先跑 `--probe-only`。

仓库自带不访问网站的路由和短链跳转测试，可在仓库根目录运行：

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
```

## 数据流与浏览器配置

- **小红书：**笔记地址及解析所需的参数会交给 `yt-dlp` 请求小红书。脚本默认不读取本机浏览器 Cookie；只有显式传入 `--cookies` 时才读取你指定的文件。小红书提取器有时返回不了可用的文件扩展名，`yt-dlp` 会把 `%(ext)s)` 原样落成 `*.unknown_video`——文件内容是有效的，但 Windows 播放器不认。脚本在 ffprobe 验证通过后会按实际容器重命名（`.mp4` / `.webm` / `.ts` / `.flv`），在 stderr 打印重命名结果，报告中的 `path` 和同名 `.download.json` 都指向重命名后的文件。
- **微信视频号：**脚本会把你提供的**完整公开分享 URL（包含查询参数）**以 HTTPS 请求发送给第三方解析服务 `https://v.mtotech.com/api/resolve`。第三方如何处理收到的 URL 不由本项目控制。解析成功后，脚本只接受 `finder.video.qq.com` 的媒体地址，不跟随跨域跳转，也不在输出中打印临时签名媒体 URL。介意将链接交给第三方时，请不要用本技能处理视频号链接。
- **哔哩哔哩：**脚本只把 BV 号或 av 号组成的规范化地址（`https://www.bilibili.com/video/<BV号>/`）交给 `yt-dlp`，分享链接里的 `vd_source`、`spm_id_from` 等追踪参数不会带进下载请求或结果输出；`b23.tv` 短链只在解析阶段跟随跳转。脚本不读取本机浏览器 Cookie，因此 1080P 高码率和 4K 等大会员内容无法获取。
- **抖音：**脚本通过 Playwright 启动单独的可见 Chrome 窗口，使用独立、**持久**的浏览器配置，不读取日常 Chrome 配置或现有浏览器 Cookie，也不会关闭你原有的 Chrome 窗口。Windows 默认配置位置是 `%LOCALAPPDATA%\MiniMax\video-downloader\douyin-chrome-profile`。该专用配置可能保留这项技能运行时产生的浏览器数据；如果不再需要，先关闭技能启动的 Chrome 窗口，再在文件资源管理器地址栏打开 `%LOCALAPPDATA%\MiniMax\video-downloader\`，删除其中的 `douyin-chrome-profile` 文件夹。使用 `--profile-dir` 后，请删除你自行指定的专用目录。

## 验证范围与限制

本项目曾在 Windows 上用有限的公开分享链接进行单条下载验证；抖音的一条样本还通过了全片解码检查，哔哩哔哩的一条样本在 `--quality 720` 下取得 1280x536 H.264 + AAC MP4，小红书的一条样本验证了未知扩展名会被重命名为 `.mp4`。平台页面、访问限制、链接有效期和第三方解析服务都可能变化，因此一次成功不能保证其他链接也能下载。`--probe-only` 只检查解析，不等于下载成功。需要登录、验证码、失效或私密的视频可能无法处理。

请只保存你有权保存的视频，并遵守平台规则。项目代码采用 [MIT License](LICENSE)；视频内容的权利仍属于各自权利人。
