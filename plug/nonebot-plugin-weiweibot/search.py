# from .utils import extract_name
from enum import Enum
from random import choice
from typing import Dict, List, Optional, Union

from algoliasearch.search.client import SearchClientSync
from nonebot.config import Config


class search_mode(Enum):
    SINGLE = "single"
    COMPLETE = "complete"
    RANDOM = "random"
    ALGOLIA = "algolia"
    CLIP = "clip"


def agent(
    mode: search_mode,
    imglist: List[str] = None,
    keyword: Optional[str] = None,
    config: Optional[Config] = None,
) -> Optional[Union[List[str], str]]:
    match mode:
        case search_mode.SINGLE | search_mode.COMPLETE | search_mode.RANDOM:
            return simple_search(
                imglist=imglist,
                keyword=keyword,
                mode=mode,
            )
        case search_mode.ALGOLIA:
            return alg(
                keyword=keyword,
                config=config,
            )
        case search_mode.CLIP:
            return clip(
                keyword=keyword,
                config=config,
            )
        case _:
            assert 0


def simple_search(
    mode: search_mode, imglist: List[str], keyword: Optional[str]
) -> Optional[Union[List[str], str]]:
    # using match will cause duplicate code but its less ugly than if
    match mode:
        case search_mode.RANDOM:
            return choice(imglist)
        case search_mode.SINGLE | search_mode.COMPLETE:
            if not keyword:
                return None
            results: List[str] = [
                img for key in keyword.split() for img in imglist if key.lower() in img
            ]
            match mode:
                case search_mode.SINGLE:
                    return choice(results) if len(results) else None
                case search_mode.COMPLETE:
                    return results if len(results) else None
                case _:
                    assert 0
        # case search_mode.COMPLETE:
        #     if not keyword: return None
        #     results: List[str] = [img for key in keyword.split() for img in imglist if key.lower() in img]
        #     return results if len(results) else None
        case _:
            assert 0
    # results = []
    # if mod:
    #     for i in range(len(names)):
    #         if key_words in ex_name[i].lower():
    #             results.append([i,name[i],ex_name[i]])
    #     if mod==1:
    #         return results
    #     else:
    #         return results
    # else:
    #     return choice(name)


def alg(keyword: Optional[str], config: Config) -> Optional[List[str]]:
    client = SearchClientSync(
        app_id=config.algolia_application_id, api_key=config.algolia_api_key
    )
    payload: Dict = {
        "requests": [
            {
                "indexName": "output",
                "query": keyword,
                "hitsPerPage": 114514,
            }
        ]
    }
    response: Dict = client.search(payload).to_dict()
    results: List[str] = [result["图片名"] for result in response["results"][0]["hits"]]
    return results if len(results) else None


def clip(keyword: Optional[str], config: Config) -> Optional[List[str]]:
    pass


# alg("美国")

# def very_ex_name_handler():
#     return very_ex_name


# def name_handler():
#     return name
