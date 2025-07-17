<!-- markdownlint-disable MD033 MD036 MD041 MD045 -->
<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="./NoneBotPlugin.svg" width="300" alt="logo">
  </a>

</div>

<div align="center">

# nonebot-plugin-weiweibot

_✨ 维维豆奶欢乐开怀 😋 ✨_

<a href="./LICENSE">
    <img src="https://img.shields.io/github/license/SwedishDoveCooker/nonebot-plugin-weiweibot.svg" alt="license">
</a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-weiweibot">
    <img src="https://img.shields.io/pypi/v/nonebot-plugin-weiweibot.svg" alt="pypi">
</a>
<img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python">
<img src="https://img.shields.io/pypi/dm/nonebot-plugin-weiweibot?logo=nonebot-plugin-weiweibot&label=Downloads" alt="downloads">

</div>

## 📖 介绍

一个快速查找维维老师语录的机器人

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-weiweibot

</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details>
<summary>pip</summary>

    pip install nonebot-plugin-weiweibot

</details>
<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-weiweibot

</details>
<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-weiweibot

</details>
<details>
<summary>conda</summary>

    conda install nonebot-plugin-weiweibot

</details>

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_weiweibot"]

</details>

## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的必填配置

|         配置项         | 必填 |     默认值      |              说明               |
| :--------------------: | :--: | :-------------: | :-----------------------------: |
|     COMMAND_START      |  否  |      ["/"]      |          决定命令开头           |
|      COMMAND_SEP       |  否  |      ["."]      |         决定命令分割符          |
|       GPG_EMAIL        |  是  | xxx@example.com |       决定 bot 使用的密钥       |
| ALGOLIA_APPLICATION_ID |  是  |     114514      | 请先将 nin 的图片库上传 algolia |
|    ALGOLIA_API_KEY     |  是  |     114514      | 请先将 nin 的图片库上传 algolia |

## 🎉 使用

### 指令表

|  指令   |  权限  | 需要@ |                        说明                        |
| :-----: | :----: | :---: | :------------------------------------------------: |
|  /help  | 所有人 |  否   |                      帮助说明                      |
|  /deta  | 所有人 |  否   |               进一步的帮助说明(bushi               |
|   /vv   | 所有人 |  否   |         输入任意关键字, 返回匹配的随机图片         |
|   /r    | 所有人 |  否   |               无需参数, 返回随机图片               |
|   /al   | 所有人 |  否   | algolia 搜索, 输入任意关键字, 返回匹配列表或指定图 |
|  /acc   | 所有人 |  否   | 精确搜索, 输入关键字, 返回匹配的图片列表或唯一图片 |
|  /gpg   | 所有人 |  否   |          加载 nin 的 gpg 密钥用于加密通信          |
| /upload | 所有人 |  否   |                      上传图片                      |

<p> 🥹 目前仅 /vv 和 /al 指令支持 gpg, clip 正在绝赞施工中 </p>

<p> ⚠️ 目前部分指令未进行全面的测试 </p>

🥰 nin 可以在本仓库的 assets 里下载样例图片
