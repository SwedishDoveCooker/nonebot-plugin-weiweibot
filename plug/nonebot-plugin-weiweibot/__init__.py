from hashlib import md5
from pathlib import Path
from typing import Annotated, List, Optional

import filetype
import httpx
from gnupg import GPG
from nonebot import logger, on_command

# from nonebot import get_bot
# from nonebot.plugin import on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.log import default_format
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import is_type

from .config import config
from .search import agent, search_mode
from .store import read, write
from .utils import (
    decry,
    export_pub,
    filter_zh_en,
    get_own_fingp,
    gpg_init,
    import_pubkey,
    index,
)

__dir: Path = Path(__file__).parent
__assets_dir: Path = __dir.parent.parent / "assets"
__tmp_dir: Path = __dir.parent.parent / "tmp"
# __keys_dir: Path = __dir.parent.parent / "keys"
__keys_dir: Path = Path.home() / ".gnupg"

gpg: GPG = gpg_init(__keys_dir)
fing: str = get_own_fingp(gpg, config.gpg_email)
pubkey: str = export_pub(gpg, fing)

imglist: List[str] = index(__assets_dir)

# BLACKLIST=[]
logger.add(
    "info.log",
    level="DEBUG",
    format=default_format,
    rotation="10 days",
    compression="zip",
)
__plugin_meta__ = PluginMetadata(
    name="vv_helper",
    description="",
    usage="",
    type="application",
    homepage="https://github.com/SwedishDoveCooker/nonebot-plugin-weiweibot",
    supported_adapters={"~onebot.v11"},
)

headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 1145141919810",
}

helper = on_command(
    "help",
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@helper.handle()
async def handle_message_helper(event: Event) -> None:
    uid: str = event.get_user_id()
    info_str = """! 使用说明如下 : 
命令1 /vv : 
    输入任意关键字, 返回匹配的随机图片

命令2 /r : 
    无需参数, 返回随机图片

命令3 /acc 别名 : /d 
    输入关键字, 返回匹配的图片列表或唯一图片
    可以再通过输入数字查找唯一图片
    所有关键字不区分大小写

命令4 /al 别名 : /algolia
    使用 algolia 搜索, 返回最可能匹配的图片
    请注意: 目前 algolia 可能无法准确返回图片名中含 “-” 的图片
        
--WIP--
命令5 /cl 别名 : /clip
    使用 clip 搜索, 结果可能会有较大偏差

命令6 /gpg 别名 : /gnupg
    加载您的gpg密钥, 用于和bot通信

命令7 /deta 别名 : /details
    显示bot详细使用说明, 保证绝对比nonebot文档拟人(

命令8 /upload
    上传, 虽然但是直接上传群相册他不香吗(
"""
    await helper.finish("Hi, " + MessageSegment.at(uid) + info_str)


al = on_command(
    "al",
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@al.handle()
async def handle_message_al(event: Event, args: Annotated[Message, CommandArg()]):
    uid: str = event.get_user_id()
    query: Optional[str] = args.extract_plain_text().strip()
    if query.startswith("-gpg "):
        query: Optional[str] = decry(gpg, query[5:].strip())
        if not query:
            await vv.finish("😅喜欢玩gpg?")
    if query.isdigit():
        keyword: Optional[str] = read(uid)
        if not keyword:
            await al.finish("😅没有找到相关缓存喵, 请先尝试查询")
        else:
            result: Optional[List[str]] = agent(
                mode=search_mode.ALGOLIA,
                keyword=keyword,
                config=config,
            )
        if result:
            if len(result) < int(query) or int(query) < 1:
                await al.finish("😅傻逼")
            logger.info(f"/al: query: {keyword}, result: {result[int(query) - 1]}")
            await al.finish(
                MessageSegment.image(__assets_dir / (result[int(query) - 1] + ".jpg"))
            )
    else:
        keyword: Optional[str] = filter_zh_en(query).lower()
        if keyword:
            result: Optional[List[str]] = agent(
                mode=search_mode.ALGOLIA,
                keyword=keyword,
                config=config,
            )
            if result:
                if len(result) == 1:
                    # quick return
                    logger.info(f"/al: query: {keyword}, result: {result[0]}")
                    await al.finish(
                        MessageSegment.image(__assets_dir / (result[0] + ".jpg"))
                    )
                logger.info(f"/al: query: {keyword}, result: {result}")
                write(filename=uid, data=keyword)
                msg: str = "🥰匹配到多张图片喵, 请选择\n" + "\n".join(
                    [f"{i + 1} : {r}" for i, r in enumerate(result)]
                )
                await al.finish(msg)
            else:
                logger.info(f"/al: query: {keyword}, result: not found")
                await al.finish(
                    "🥺not found\n请注意, 输入的关键词中的非中英文部分会被清除喵"
                )
        else:
            await al.finish("😡请输入查询参数喵")


deta = on_command(
    "deta",
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@deta.handle()
async def handle_message_deta():
    info_str = """1. 搜索
    搜索不到时可以尝试将关键字用空格分开, 尤其是使用algonlia时, 而不是去增加关键字
    查找时只允许中英文和空格, 大小写不敏感
2. gpg
    bot不会验证消息的签名, 同时也没有做对任何重放攻击的防范
    由于我实在找不到任何优雅的实现子命令解析的方法, 使用gpg时请严格按照/xxx -gpg 密文的格式发送
3. CLIP
    估计需要比较长的时间才能做完
4. 上传
    强烈建议使用群相册, bot的上传功能很难做到比相册更加方便
    """
    await deta.finish(info_str)


cl = on_command(
    "cl",
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@cl.handle()
async def handle_message_cl():
    await cl.finish("WIP")


vv = on_command(
    "vv",
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@vv.handle()
async def handle_message_vv(event: Event, args: Annotated[Message, CommandArg()]):
    if keyword := args.extract_plain_text().strip():
        if keyword.startswith("-gpg "):
            keyword: Optional[str] = decry(gpg, keyword[5:].strip())
            if not keyword:
                await vv.finish("😅喜欢玩gpg?")
        # results = search(location, 1)
        result: Optional[str] = agent(
            mode=search_mode.SINGLE,
            imglist=imglist,
            keyword=filter_zh_en(keyword.lower()),
        )
        if result:
            logger.info(f"/vv: query: {keyword}, result: {result}")
            uid: str = event.get_user_id()
            write(filename=uid, data=filter_zh_en(keyword.lower()))
            await vv.finish(MessageSegment.image(__assets_dir / (result + ".jpg")))
            # await vv.finish(encry_img(gpg, __assets_dir / (result + ".jpg"), read(uid + ".gpg")))
        else:
            logger.info(f"/vv: query: {keyword}, result: not found")
            await vv.finish(
                "🥺not found\n请注意, 输入的关键词中的非中英文部分会被清除喵"
            )
    else:
        await vv.finish("🙌请输入查询参数喵")


r = on_command(
    "r",
    aliases={"rand"},
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@r.handle()
async def handle_message_r():
    # if args.extract_plain_text():
    #     await vv.finish()
    result: Optional[str] = agent(
        mode=search_mode.RANDOM,
        imglist=imglist,
    )
    logger.info(f"/r : result:{result}")
    await vv.finish(
        MessageSegment.image(__dir.parent.parent / "assets" / (result + ".jpg"))
    )


acc = on_command(
    "acc",
    aliases={"d"},
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@acc.handle()
async def handle_message_acc(event: Event, args: Annotated[Message, CommandArg()]):
    # read cache if the input is num
    uid: str = event.get_user_id()
    query: Optional[str] = args.extract_plain_text().lower().strip()
    if query.isdigit():
        keyword: Optional[str] = read(uid)
        if not keyword:
            await acc.finish("😅没有找到相关缓存喵, 请先尝试查询")
        else:
            result: Optional[List[str]] = agent(
                mode=search_mode.COMPLETE,
                imglist=imglist,
                keyword=keyword,
            )
        if result:
            if len(result) < int(query) or int(query) < 1:
                await acc.finish("😅")
            logger.info(f"/acc: query: {keyword}, result: {result[int(query) - 1]}")
            await acc.finish(
                MessageSegment.image(__assets_dir / (result[int(query) - 1] + ".jpg"))
            )
    else:
        keyword: Optional[str] = filter_zh_en(query)
    if keyword:
        # simply unserialize may cause security issues
        result: Optional[List[str]] = agent(
            mode=search_mode.COMPLETE,
            imglist=imglist,
            keyword=keyword,
        )
        if result:
            if len(result) == 1:
                logger.info(f"/acc: query: {keyword}, result: {result[0]}")
                await acc.finish(
                    MessageSegment.image(__assets_dir / (result[0] + ".jpg"))
                )
            logger.info(f"/acc: query: {keyword}, result: {result}")
            write(filename=uid, data=keyword)
            # msg = "匹配到多张图片, 请选择\n"
            #             for i in range(len(result)):
            #                 msg += str(i+1) + " : " + result[i][2] + "\n"
            #             msg+=str(len(result)+1)+" : 退出"
            #             await acc.pause(msg)
            msg: str = "🥰匹配到多张图片, 请选择\n" + "\n".join(
                [f"{i + 1} : {r}" for i, r in enumerate(result)]
            )
            await acc.finish(msg)
        else:
            logger.info(f"/acc: query: {keyword}, result: not found")
            await acc.finish(
                "🥺not found\n请注意, 输入的关键词中的非中英文部分会被清除喵"
            )
    else:
        await acc.finish("🙌请输入查询参数喵")


gpgload = on_command(
    "gpg",
    aliases={"gnupg"},
    block=True,
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
)


@gpgload.handle()
async def _(event: Event, args: Annotated[Message, CommandArg()]):
    uid: str = event.get_user_id()
    secret: Optional[str] = args.extract_plain_text().strip()
    if not secret:
        await gpgload.finish("🤠请查收bot的pubkey: " + pubkey)
    # try:
    fingerprints: List[str] = import_pubkey(gpg, secret)
    if not fingerprints:
        await gpgload.finish("🤣导入失败, 请检查公钥格式喵")
    else:
        write(filename=uid + ".gpg", data=fingerprints[0])
        logger.info(f"/gpg : uid:{uid}, fingerprints: {fingerprints[0]}")
        await gpgload.finish(
            f"🥹导入成功喵, 公钥指纹为: {fingerprints[0]}\n您可以使用您的密钥和bot通信了喵"
        )
    # except Exception as e:
    #     logger.error(f"/gpg : uid:{uid}, error:{e}")
    #     await gpgload.finish("🤣导入失败, 请检查公钥格式喵")


uploader = on_command(
    "upload",
    aliases={"上传"},
    rule=is_type(PrivateMessageEvent, GroupMessageEvent),
    block=True,
)


@uploader.handle()
async def handle_message_uploader(bot: Bot, event: Event):
    name: str = event.get_plaintext()
    flag: list = []
    for i in event.get_message():
        if i.__dict__["type"] == "image":
            flag.append(i.__dict__["data"]["url"])
    if flag:
        for URL in flag:
            async with httpx.AsyncClient() as client:
                response = await client.get(URL)
                if response.status_code == 200:
                    save_path: Path = (
                        __tmp_dir
                        / f"{md5(response.content).hexdigest()}.{filetype.guess(response.content).extension}"
                        if filetype.guess(response.content)
                        else __tmp_dir / f"{md5(response.content).hexdigest()}.wtf"
                    )
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(response.content)
                    logger.info(f"Image saved: {save_path} from URL: {URL}")
                else:
                    logger.error(
                        f"failed to save img from URL: {URL} due to {response.status_code}"
                    )
    else:
        logger.info(
            f"/upload : uid:{event.get_user_id()}, name:{name}, error: no image found"
        )
        await uploader.finish("🤨没有找到图片喵, 请发送图片后再试喵")


# result = []
# @acc.handle()
# async def handle_message_d(args: Message = CommandArg()):
#     global result; result = []
#     if location := args.extract_plain_text().lower().strip():
#         result=simple_search(location,3426)
#         if len(result) == 1:
#             logger.info(f"/acc : query:{location}, result:{', '.join(map(str, result))}")
#             await acc.finish(MessageSegment.image(Path(__file__).parent / "assets" / result[0][1]))
#         if len(result) > 1:
#             logger.info(f"/acc : query:{location}, result:{', '.join(map(str, result))}")
#             msg = "匹配到多张图片, 请选择\n"
#             for i in range(len(result)):
#                 msg += str(i+1) + " : " + result[i][2] + "\n"
#             msg+=str(len(result)+1)+" : 退出"
#             await acc.pause(msg)
#         else:
#             logger.info(f"/acc : query:{location}, result:not found")
#             await acc.finish("not found\n你可以使用/upload命令上传缺失的照片, 具体请参照/help\n也可以使用/f进行模糊搜索")

# @acc.handle()
# async def handle_message_dl(args: Message = CommandArg()):
#     global result;location = args.extract_plain_text()
#     if location.isdigit():
#         if int(location)<=len(result):
#             logger.info(f"/acc : query:{location}, result:{result[int(location)-1][1]}")
#             await acc.reject(MessageSegment.image(Path(__file__).parent / "assets" / result[int(location)-1][1]))
#         elif int(location)==len(result)+1:
#             await acc.finish("已退出")
#         else:
#             await acc.finish("out of range")
#     await acc.reject("仍在300秒会话期内, 请按照规范输入或者选择相应数字退出")


# seer = on_message()
# 我会一直视奸你的
# '''
# @seer.handle()
# async def handle_message_seer(bot: Bot, event: Event):
#     name: str = event.get_plaintext()
#     flag: list = []
#     imgname:str = str(uuid.uuid4())
#     for i in event.get_message():
#         # logger.info(i.__dict__)
#         if i.__dict__['type'] == 'image':
#             # logger.info("fetched "+i.__dict__['data']['url'])
#             flag.append(i.__dict__['data']['url'])
#     # logger.info(event.get_message())
#     # logger.info(event.get_message()[0].__dict__)
#     # logger.info(event.get_message()[0].__dict__['data']['url'])
#     # logger.info(event.get_message()[1].__dict__)
#     # logger.info(event.get_message()[1].__dict__['data']['url'])
#     if flag:
#         for URL in flag:
#             async with httpx.AsyncClient() as client:
#                 response = await client.get(URL)
#                 if response.status_code == 200:
#                     md5_hash = hashlib.md5(response.content).hexdigest()
#                     kind = filetype.guess(response.content)
#                     filename = f"{md5_hash}.{kind.extension}"
#                     save_path = __dir.joinpath("temp", filename)
#                     save_path.parent.mkdir(parents=True, exist_ok=True)
#                     with open(save_path, "wb") as f:
#                         f.write(response.content)
#                     logger.info(f"Image saved: {filename} from URL: {URL}")
#                 else:
#                     logger.error(f"failed to save img from URL: {URL}")
#         input_dir = __dir.joinpath("temp")
#         # Define target directories
#         nailong_dir = __dir.joinpath("outputs", "nailong")
#         notnailong_dir = __dir.joinpath("outputs", "notnailong")

#         # Ensure target directories exist
#         nailong_dir.mkdir(parents=True, exist_ok=True)
#         notnailong_dir.mkdir(parents=True, exist_ok=True)

#         if run_predictions(input_dir, model, test_transform, device):
#             # target_path = nailong_dir / image_path.name
#             # image_path.rename(target_path)

#             await bot.call_api('delete_msg', message_id=event.message_id)
#             await bot.set_group_ban(group_id=event.group_id, user_id=event.user_id, duration=60)
#             await seer.finish(MessageSegment.image(Path(__file__).parent / f"{randint(1, 5)}.jpg"))
#         else:
#             # target_path = notnailong_dir / image_path.name
#             # image_path.rename(target_path)
#             logger.info(f"没有发现奶龙: {image_path.name}")
# '''
# @seer.handle()
# async def handle_message_seer(bot: Bot, event: Event):
#     return 0
#     name: str = event.get_plaintext()
#     flag: list = []
#     unique_folder_name:str = str(uuid.uuid4())
#     for i in event.get_message():
#         # logger.info(i.__dict__)
#         if i.__dict__['type'] == 'image':
#             # logger.info("fetched "+i.__dict__['data']['url'])
#             flag.append(i.__dict__['data']['url'])
#     # logger.info(event.get_message())
#     # logger.info(event.get_message()[0].__dict__)
#     # logger.info(event.get_message()[0].__dict__['data']['url'])
#     # logger.info(event.get_message()[1].__dict__)
#     # logger.info(event.get_message()[1].__dict__['data']['url'])
#     if flag:
#         for URL in flag:
#             async with httpx.AsyncClient() as client:
#                 response = await client.get(URL)
#                 if response.status_code == 200:
#                     md5_hash = hashlib.md5(response.content).hexdigest()
#                     kind = filetype.guess(response.content)
#                     filename = f"{md5_hash}.{kind.extension}"
#                     save_path = __dir.joinpath("input", unique_folder_name, filename)
#                     save_path.parent.mkdir(parents=True, exist_ok=True)
#                     with open(save_path, "wb") as f:
#                         f.write(response.content)
#                     # logger.info(f"Image saved: {filename} from URL: {URL}")
#                 else:
#                     logger.error(f"failed to save img from URL: {URL}")
#         input_dir = __dir.joinpath("input", unique_folder_name)
#         if run_predictions(input_dir, model, test_transform, device):
#             target_dir = __dir.joinpath("input", "奶龙们", unique_folder_name)
#             target_dir.parent.mkdir(parents=True, exist_ok=True)
#             input_dir.rename(target_dir)
#             await bot.call_api('delete_msg', message_id=event.message_id)
#             await bot.set_group_ban(group_id = event.group_id, user_id = event.user_id, duration = 60)
#             await seer.finish(MessageSegment.image(Path(__file__).parent / (str(randint(1,6)) + ".jpg")))
#             # await seer.finish("发现奶龙")
#         else:
#             target_dir = __dir.joinpath("input", "非奶龙", unique_folder_name)
#             target_dir.parent.mkdir(parents=True, exist_ok=True)
#             input_dir.rename(target_dir)
#             logger.info("没有发现奶龙")

# fuzzy_search = on_command(
#     "f",
#     aliases={"模糊搜索", "模糊"},
#     block=True,
#     rule = is_type(PrivateMessageEvent, GroupMessageEvent),
#     permission=limit_permission
# )

# very_ex_name=very_ex_name_handler()
# name=name_handler()
# idf = compute_idf(very_ex_name)
# @fuzzy_search.handle()
# async def handle_message_fuzzy_search(bot: Bot, event: Event) -> None:
#     message: str = event.get_plaintext().lower();global very_ex_name,idf
#     ranked_results = rank_documents(message, very_ex_name, idf)
#     if ranked_results:
#         top_index, top_score = ranked_results[0]
#     logger.info(f"/f : query:{message}, result:{name[top_index]}")
#     await fuzzy_search.send(f"最高权重: {top_score}")
#     await fuzzy_search.finish(MessageSegment.image(Path(__file__).parent / "assets" / name[top_index]))


# add = on_command(
#     "add",
#     block=True,
#     rule = is_type(PrivateMessageEvent, GroupMessageEvent),
#     permission=SUPERUSER
# )

# @add.handle()
# async def handle_message_add(args: Message = CommandArg()):
#     uid = args.extract_plain_text().strip()
#     global BLACKLIST
#     if uid in BLACKLIST:
#         await add.finish("User already in blacklist")
#     else:
#         BLACKLIST.append(uid)
#         logger.info(f"User {uid} added to blacklist")
#         await add.finish("User added to blacklist")


# remove = on_command(
#     "remove",
#     block=True,
#     rule = is_type(PrivateMessageEvent, GroupMessageEvent),
#     permission=SUPERUSER
# )

# @remove.handle()
# async def handle_message_remove(args: Message = CommandArg()):
#     uid = args.extract_plain_text().strip()
#     global BLACKLIST
#     if uid not in BLACKLIST:
#         await remove.finish("User not in blacklist")
#     else:
#         BLACKLIST.remove(uid)
#         logger.info(f"User {uid} removed from blacklist")
#         await remove.finish("User removed from blacklist")
