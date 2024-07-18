<div align="center">
  <a href="https://nonebot.dev/store"><img src="https://raw.githubusercontent.com/A-kirami/nonebot-plugin-template/resources/nbp_logo.png" width="180" height="180" alt="NoneBotPluginLogo"></a>
  <br>
  <p><img src="https://raw.githubusercontent.com/A-kirami/nonebot-plugin-template/resources/NoneBotPlugin.svg" width="240" alt="NoneBotPluginText"></p>
</div>

<div align="center">

# nonebot-plugin-weiweibot

_✨ 维维豆奶欢乐开怀😋 ✨_


<a href="./LICENSE">
    <img src="https://img.shields.io/github/license/SwedishDoveCooker/nonebot-plugin-weiweibot.svg" alt="license">
</a>
<a href="https://pypi.python.org/pypi/nonebot-plugin-weiweibot">
    <img src="https://img.shields.io/pypi/v/nonebot-plugin-weiweibot.svg" alt="pypi">
</a>
<img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="python">

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

|         配置项         | 必填 |  默认值   |        说明        |
| :--------------------: | :--: | :-------: | :----------------: |
| SESSION_EXPIRE_TIMEOUT |  否  |   PT30S   |    控制会话时长    |
|     COMMAND_START      |  否  | ["/", ""] | 判断消息是否是命令 |
|      COMMAND_SEP       |  否  |   ["."]   |   命令的分隔标记   |

## 🎉 使用

### 指令表

|        指令 ( 所有 / 均可省略 )       |      权限      | 需要@ |                        说明                        |
| :----------------: | :------------: | :---: | :------------------------------------------------: |
|       /help        | 黑名单外所有人 |  否   |                      帮助说明                      |
|        /vv         | 黑名单外所有人 |  否   |         输入任意关键字, 返回匹配的随机图片         |
|         /d         | 黑名单外所有人 |  否   | 精确搜索, 输入关键字, 返回匹配的图片列表或唯一图片 |
|         /r         | 黑名单外所有人 |  否   |               无需参数, 返回随机图片               |
|         /f         | 黑名单外所有人 |  否   |     模糊搜索, 输入关键字, 返回最可能匹配的图片     |
|      /upload       | 黑名单外所有人 |  否   |                      上传图片                      |
| /image_recognition |     管理员     |  否   |            对群友上传的图片进行文字识别            |
|        /add        |     管理员     |  否   |                  将群友加入黑名单                  |
|      /remove       |     管理员     |  否   |                  将群友移出黑名单                  |

### 效果图

仅展示群内互动功能
<div align="left">
<img src="https://cdn.jsdelivr.net/gh/SwedishDoveCooker/ImgBed@main/202407180035381.png" width="600"/>
<img src="https://cdn.jsdelivr.net/gh/SwedishDoveCooker/ImgBed@main/202407180035618.jpg" width="600"/>
<img src="https://cdn.jsdelivr.net/gh/SwedishDoveCooker/ImgBed@main/202407180035690.png" width="600"/>
</div>
