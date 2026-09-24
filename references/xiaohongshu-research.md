# 研究与验证记录

研究日期：2026-09-22。资料通过 Codex 自带网页搜索和官方源码查找；没有使用 OpenCLI 搜索，也没有把用户 Cookie 发给在线解析站。

## 官方依据

- [yt-dlp 官方项目及安装说明](https://github.com/yt-dlp/yt-dlp#installation)
- [官方小红书提取器源码](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/xiaohongshu.py)
- [Cookie 使用说明](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
- [短链/提取故障报告](https://github.com/yt-dlp/yt-dlp/issues/15467)

源码核实结果：提取器直接支持 `www.xiaohongshu.com/explore/<ID>` 和 `/discovery/item/<ID>`。短链应先解析为完整笔记 URL。页面中 `window.__INITIAL_STATE__` 的 `note.noteDetailMap[ID].note` 包含视频信息。`video.media.stream` 的 `masterUrl` 和 `backupUrls` 是候选视频地址；`video.consumer.originVideoKey` 可对应 `https://sns-video-bd.xhscdn.com/{originVideoKey}`。官方提取器用 GET 检查原始地址，特意不用 HEAD，以免假阴性。这些是维护诊断线索，不表示每条笔记均有原始地址。

## 验证方法

1. 检查短链跳转链；如果最终落在登录页，从 `redirectPath` 提取完整笔记地址，保留查询参数。
2. 将完整 HTTPS 笔记地址交给已安装的 `yt-dlp`，确认能读取标题和视频格式。
3. 下载后用 `ffprobe` 检查实际文件的容器、时长、视频和音频轨道。不要把封面或网页当成视频。

参考过其他开源下载技能的搜索结果，但本地脚本为本次编写，没有安装或运行第三方技能中的未知代码。脚本依赖机器上已有的 yt-dlp，不对其源码作修改。
