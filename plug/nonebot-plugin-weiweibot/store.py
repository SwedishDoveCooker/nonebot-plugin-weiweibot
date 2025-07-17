from nonebot import require
from typing import Optional
import nonebot_plugin_localstore as store

require("nonebot_plugin_localstore")


def read(filename) -> Optional[str]:
    data_file = store.get_plugin_data_file(filename)
    if not data_file.exists():
        return None
    data = data_file.read_text()
    return data


def write(filename, data) -> None:
    data_file = store.get_plugin_data_file(filename)
    # may be useless
    if not data_file.exists():
        data_file.touch()
    data_file.write_text(data)
    return


def dele(filename) -> None:
    data_file = store.get_plugin_data_file(filename)
    # if data_file.exists():
    data_file.unlink(missing_ok=True)
    return
