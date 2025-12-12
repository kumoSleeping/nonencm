


# Nonencm


[![PyPI](https://img.shields.io/pypi/v/nonencm?style=flat-square)](https://pypi.org/project/nonencm/)
[![License](https://img.shields.io/github/license/taurusxin/ncmdump?style=flat-square)](LICENSE)

## 📖 简介

**[pyncm](https://github.com/greats3an/pyncm)** 是一个功能强大的 `ncm` 处理工具。
**[QQMusicApi](https://github.com/L-1124/QQMusicApi)** 是一个功能强大的 异步 API 库。
**[noneprompt](https://github.com/nonebot/noneprompt)** 是 NoneBot 设计的控制台交互的提示工具包。

> ~~本项目实际上就是把这三个东西 vibe 在一起.~~

另外, 本项目仅用于学习研究封装与工具开发经验, 不提供任何支持.  

## 🚀 安装与使用

### 方式一：通过 PyPI 安装 (推荐)

如果您熟悉 Python 环境，可以直接通过 pip 安装：

```bash
pip install nonencm
nonencm
```

如果你希望使用目标文件夹的图片报表功能, 需要安装 pil-utils 依赖:

```bash
pip install "nonencm[pil-utils]"
nonencm
```

### 方式二：下载可执行文件

对于没有 Python 环境的用户，可以在 [Releases](../../releases) 页面下载对应系统的可执行文件。Windows 用户下载后直接双击即可。

在终端中运行方法:
- Windows: `win` + `r`，输入 `cmd`，回撤出现黑窗口，拖入 `.exe` 文件，回车运行
- macOS: `open nonencm-macos-vX.X.X`，打开访达找到所在文件夹，右键底部文件夹，选择 `在终端中打开` 输入
    ```bash
    chmod + x nonencm-macos-vX.X.X
    ./nonencm-macos-vX.X.X
    ```

## 使用前须知

1. 请先登录
   1. N 推荐使用二维码登录
   2. Q 推荐使用二维码登录
   3. ~~因为我别的都没测~~
2. 输出目录共用，Detection / Export 会对目录内所有歌曲生效（无论来源于 N 还是 Q）。

**返回上一级/取消等操作, 请使用 `ctrl + c` 或 `cmd + c`(Mac)**

## 功能一览


### Settings
> 通用设置
- Output Directory
  - 选择下载文件的保存位置
- Filename Template: {title} - {artist}
  - {title}：歌曲名
  - {artist}/{artists}：歌手（多个时逗号分隔）
  - {album}：专辑名
  - {track}：同 {title}（保留的兼容键）
  - {id}：歌曲 ID
- Overwrite Files: No / Yes
  - 如果已经存在是否覆盖

> N Settings（二级菜单）
- Audio Quality: standard
  - Standard (standard) 默认
  - Higher (exhigh)
  - Lossless (lossless)
  - Hi-Res (hires)
- Preferred Format: auto
  - auto：由接口返回的最佳可用格式决定(在较低的 Audio Quality 情况下通常是 mp3)
  - mp3：即便有高码率/无损也会强制转为 mp3 级别的下载。
  - flac：会优先无损格式，不足时再退回其他格式。
- Download Lyrics: No
  - 下载同时附带歌词
- Use Download API: No / Yes
  - 网易云黑胶用户拥有每个月300-500次的下载机会
  - 否则使用播放Api进行下载，可能会有部分音质受限的情况

> Q Settings（二级菜单）
- Preferred File Type
  - mp3_320：高码率 mp3
  - mp3_128：标准 mp3
  - flac：无损 flac（可用时）

### Login
> 平台独立登录
- N Account：二维码 / 手机号 / 匿名登录，支持注销，登录后生成 `session.pyncm`
- Q Account：二维码（Q / W）或短信验证码登录，支持注销，登录后生成 `session.qqmusic.json`
- 未登录的平台不会显示对应的搜索入口

### Search & Download

- 支持直接传入歌单链接下载（N / Q）
- 支持单行或多行关键字搜索并下载（换行分隔；逐首确认后静默下载，可继续下一首）
- 下载后复用通用的检测/导出能力（含残破文件检测，需登录/VIP 时触发）

### Export
> 导出目标文件夹的歌单报表

- Image Report (JPG)
- CSV
- TXT
- Markdown

### Detection
> 对目标文件夹进行检测与处理

- Check Failed Downloads
  - 会根据下载策略进行残破文件(需vip/登陆)的检测和二次下载确认
- Check Possible Duplicates
  - 对目标文件夹进行匹配、检测可能的重复文件并让用户选择


## 配置文件
- 本项目会在启动的文件夹生成 nonencm_config.yaml 文件, 用于保存全局配置
- 登录后, N 会生成 session.pyncm，Q 会生成 session.qqmusic.json，用于保存登录状态

## 📄 许可证
额别急我研究一下。
