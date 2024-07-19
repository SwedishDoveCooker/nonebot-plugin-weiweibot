import re
import mimetypes
import aiohttp
from urllib.parse import urlparse
from random import choice
from pathlib import Path
from typing import Optional
from nonebot.rule import is_type
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.permission import SUPERUSER
from nonebot import logger
from nonebot import on_command
from nonebot.adapters import Bot
from nonebot.adapters import Event
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.adapters.onebot.v11 import PrivateMessageEvent, GroupMessageEvent

from .tf_idf import compute_idf, rank_documents
from .simple_search import simple_search, very_ex_name_handler, name_handler
from .image_r3cognition import rename_images, process_images

BLACKLIST=[]
__dir = Path(__file__).parent

__plugin_meta__ = PluginMetadata(
    name="vv_helper",
    description="A helper plugin for weiwei lovers.",
    usage="This plugin provides various commands for image searching and uploading as well as managing.",

    type="application",

    homepage="https://github.com/SwedishDoveCooker/nonebot-plugin-weiweibot",
    

    supported_adapters={"~onebot.v11"},
)


async def limit_permission(event: Event):
    uid = event.get_user_id()
    if uid not in BLACKLIST:
        return True
    logger.info(f"Blocked User {uid}")
    return False


helper = on_command(
    "help",
    priority=11,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=limit_permission
)

@helper.handle()
async def handle_message_helper(bot: Bot, event: Event) -> None:
    uid: str = event.get_user_id()
    username: Optional[str] = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.usuuu.com/qq/{uid}") as response:
                if response.status == 200:
                    data = await response.json()
                    username = data['data']['name']
                else:
                    logger.error(f"Failed to fetch username for UID {uid}, status code: {response.status}")
    except Exception as e:
        logger.error(f"Error fetching username for UID {uid}: {e}")

    if not username:
        username = "Unknown User"

    message: str = event.get_plaintext().lower().strip()
    infor_str = f"""Hi, @{username}! 使用说明如下 : 
命令1 /vv : 
           输入任意关键字, 返回匹配的随机图片

命令2 /r : 
           无需参数, 返回随机图片

命令3 /d 别名 : /精确搜索 /精确 
           输入关键字, 返回匹配的图片列表或唯一图片
           可以再通过输入数字查找唯一图片, 查找有水印图片请在关键字后额外输入_1
           你有30秒的时间输入, 返回图片或输入错误将重置这个时间
           所有关键字不区分大小写

命令4 /f 别名 : /模糊搜索 /模糊 
           输入关键字, 返回最可能匹配的图片
           结果不保证绝对准确

命令5 /upload 别名 : /上传 
           输入图片名字 ( 有水印请在结尾加上_1 ) 并附上图片,将图片保存到临时图库
           使用示例 : /upload 不也挺好吗 附上相应的图片"""

    await helper.finish(infor_str)


vv = on_command(
    "vv",
    priority=100,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=limit_permission
)
@vv.handle()
async def handle_message_vv(args: Message = CommandArg()):
    if location := args.extract_plain_text().lower().strip():
        results = simple_search(location, 1)
        if len(results) > 0:
            result = choice(results)
            logger.info(f"/vv : query:{location}, result:{result[1]}")
            await vv.finish(MessageSegment.image(Path(__file__).parent / "assets" / result[1]))
        else:
            logger.info(f"/vv : query:{location}, result:not found")
            await vv.finish("not found\n你可以使用/upload命令上传缺失的照片, 具体请参照/help\n也可以使用/f进行模糊搜索")
    else:
        await vv.finish("全随机请使用/r命令")


r = on_command(
    "r",
    aliases={"每日一签", "打卡"},
    priority=102,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=limit_permission
)

@r.handle()
async def handle_message_r(args: Message = CommandArg()):
        result = simple_search("whatcanisay",0)
        logger.info(f"/r : result:{result}")
        await vv.finish(MessageSegment.image(Path(__file__).parent / "assets" / result))


d = on_command(
    "d",
    aliases={"精确搜索", "精确"},
    priority=101,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=limit_permission
)

result = []
@d.handle()
async def handle_message_d(args: Message = CommandArg()):
    global result; result = []
    if location := args.extract_plain_text().lower().strip():
        result=simple_search(location,3426)
        if len(result) == 1:
            logger.info(f"/d : query:{location}, result:{', '.join(map(str, result))}")
            await d.finish(MessageSegment.image(Path(__file__).parent / "assets" / result[0][1]))
        if len(result) > 1:
            logger.info(f"/d : query:{location}, result:{', '.join(map(str, result))}")
            msg = "匹配到多张图片, 请选择, _1后缀的图片代表有水印的图片\n"
            for i in range(len(result)):
                msg += str(i+1) + " : " + result[i][2] + "\n"
            msg+=str(len(result)+1)+" : 退出"
            await d.pause(msg)
        else:
            logger.info(f"/d : query:{location}, result:not found")
            await d.finish("not found\n你可以使用/upload命令上传缺失的照片, 具体请参照/help\n也可以使用/f进行模糊搜索")

@d.handle()
async def handle_message_dl(args: Message = CommandArg()):
    global result;location = args.extract_plain_text()
    if location.isdigit():
        if int(location)<=len(result):
            logger.info(f"/d : query:{location}, result:{result[int(location)-1][1]}")
            await d.reject(MessageSegment.image(Path(__file__).parent / "assets" / result[int(location)-1][1]))
        elif int(location)==len(result)+1:
            await d.finish("已退出")
        else:
            await d.finish("out of range")
    await d.reject("仍在30秒会话期内, 请按照规范输入或者选择相应数字退出")


uploader = on_command(
    "upload",
    aliases={"上传"},
    priority=98,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    block=True,
)

headers = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
}

async def fetch(session, url):
    try:
        async with session.get(url, headers=headers) as response:
            content_type = response.headers.get('Content-Type')
            extension = mimetypes.guess_extension(content_type)
            return await response.read(), extension
    except aiohttp.ClientError as e:
        print(f"Request failed: {e}")

def is_valid_domain(url):
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    return domain == "gchat.qpic.cn" or domain == "multimedia.nt.qq.com.cn"

def is_valid_filename(filename):
    pattern = r'^[\u4e00-\u9fa5A-Za-z0-9_ ]+$'
    return re.match(pattern, filename) is not None

@uploader.handle()
async def handle_message_uploader(args: Message = CommandArg()):
    name: str = args.extract_plain_text().strip()
    URL = None
    for segment in args:
        if segment.type == 'image':
            URL = segment.data['url']
    if is_valid_domain(URL) and is_valid_filename(name):
        async with aiohttp.ClientSession() as session:
            r, extension = await fetch(session, URL)
            if r:
                full_filename = f"{name}{extension}"
                print(full_filename)
                with open("assets/uploads/" + full_filename, 'wb') as f:
                    f.write(r)
                logger.info(f"Image saved: {full_filename} from URL: {URL}")
                await uploader.finish("saved")
            else:
                logger.error(f"Failed to fetch image from URL: {URL}")
                await uploader.finish("network err")
    else:
        logger.error(f"Invalid URL or filename: {URL}, {name}")
        await uploader.finish("do not hack")


fuzzy_search = on_command(
    "f",
    aliases={"模糊搜索", "模糊"},
    priority=99,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=limit_permission
)

very_ex_name=very_ex_name_handler()
name=name_handler()
idf = compute_idf(very_ex_name)
@fuzzy_search.handle()
async def handle_message_fuzzy_search(bot: Bot, event: Event) -> None:
    message: str = event.get_plaintext().lower();global very_ex_name,idf
    ranked_results = rank_documents(message, very_ex_name, idf)
    if ranked_results:
        top_index, top_score = ranked_results[0]
    logger.info(f"/f : query:{message}, result:{name[top_index]}")
    await fuzzy_search.send(f"最高权重: {top_score}")
    await fuzzy_search.finish(MessageSegment.image(Path(__file__).parent / "assets" / name[top_index]))


image_recognition = on_command(
    "image_recognition",
    priority=10,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=SUPERUSER
)

@image_recognition.handle()
async def handle_image_recognition(bot: Bot, event: Event):
    await image_recognition.send("starting task")
    folder_path = __dir.joinpath("assets", "uploads")
    rename_images(folder_path)
    process_images(folder_path)
    await image_recognition.finish("done")


add = on_command(
    "add",
    priority=103,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=SUPERUSER
)

@add.handle()
async def handle_message_add(args: Message = CommandArg()):
    uid = args.extract_plain_text().strip()
    global BLACKLIST
    if uid in BLACKLIST:
        await add.finish("User already in blacklist")
    else:
        BLACKLIST.append(uid)
        logger.info(f"User {uid} added to blacklist")   
        await add.finish("User added to blacklist")


remove = on_command(
    "remove",
    priority=104,
    block=True,
    rule = is_type(PrivateMessageEvent, GroupMessageEvent),
    permission=SUPERUSER
)

@remove.handle()
async def handle_message_remove(args: Message = CommandArg()):
    uid = args.extract_plain_text().strip()
    global BLACKLIST
    if uid not in BLACKLIST:
        await remove.finish("User not in blacklist")
    else:
        BLACKLIST.remove(uid)
        logger.info(f"User {uid} removed from blacklist")
        await remove.finish("User removed from blacklist")

