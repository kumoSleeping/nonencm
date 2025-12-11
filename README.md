


# Nonencm


[![PyPI](https://img.shields.io/pypi/v/nonencm?style=flat-square)](https://pypi.org/project/nonencm/)
[![License](https://img.shields.io/github/license/taurusxin/ncmdump?style=flat-square)](LICENSE)

## 📖 简介

**[pyncm](https://github.com/greats3an/pyncm)** 是一个功能强大的 `ncm` 处理工具。

本项目基于 **pyncm** 与 **noneprompt** 构建的现代化 CLI 界面，提供更便捷的使用体验。

本项目仅用于学习研究封装与工具开发经验, 不提供任何服务.  

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

## 使用前必做

1. 请先登录，并保证账号拥有一定的权限, 确保你能完整收听歌曲
2. Settings 设置你的下载文件夹
3. Settings 设置你的音频 Quality

## 功能一览


### Settings
> 全局设置
- Output Directory
  - 选择下载文件的保存位置
- Audio Quality: standard
  - Standard (standard) 默认
  - Higher (exhigh)
  - Lossless (lossless)
  - Hi-Res (hires)
- Preferred Format: auto
  - auto：由接口返回的最佳可用格式决定(在较低的 Audio Quality 情况下通常是 mp3)
  - mp3：即便有高码率/无损也会强制转为 mp3 级别的下载。
  - flac：会优先无损格式，不足时再退回其他格式。
- Filename Template: {title} - {artist}
  - {title}：歌曲名
  - {artist}/{artists}：歌手（多个时逗号分隔）
  - {album}：专辑名
  - {track}：同 {title}（保留的兼容键）
  - {id}：歌曲 ID
- Download Lyrics: No
  - 下载同时附带歌词
- Use Download API: No / Yes
  - 网易云黑胶用户拥有每个月300-500次的下载机会
  - 否则使用播放Api进行下载，可能会有部分音质受限的情况
- Overwrite Files: No / Yes
  - 如果已经存在是否覆盖

### Search & Download
>批量下载歌曲歌单

- 支持直接传入歌单链接下载
- 支持直接搜索歌曲下载
- 支持批量搜索歌曲下载
  - 使用换行分隔
  - 每次将请您手动确认搜索结果, 确认后将静默下载, 您可以立即确认下一首歌的选择
- 会根据下载策略进行残破文件(需vip/登陆)的检测和二次下载确认

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

### 基本支持
- 登陆
- 下载自动补全封面信息

## 配置文件
- 本项目会在启动的文件夹生成 nonencm_config.yaml 文件, 用于保存全局配置
- 登录后, pyncm 会在启动的文件夹生成 session.pyncm 文件, 用于保存登录状态

## 📄 许可证
额别急我研究一下。
