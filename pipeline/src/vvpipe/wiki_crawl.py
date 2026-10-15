"""Fetch the wikitext of a MediaWiki category (and its sub-categories) slowly and politely.

Used for the bot's knowledge base: the mirror at moegirl.icu answers the MediaWiki API; the
original site does not. One request per second, a descriptive User-Agent, and every page is
written to disk once so a stopped crawl resumes where it was.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://moegirl.icu/api.php"
UA = "weiweibot-kb/0.1 (personal non-commercial QQ bot; contact: repo owner on GitHub)"


def _get(params: dict, pause_s: float) -> dict:
    url = API + "?" + urllib.parse.urlencode({"format": "json", **params})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    time.sleep(pause_s)
    return data


def category_pages(
    category: str, depth: int = 1, pause_s: float = 1.0, seen: set[str] | None = None
) -> list[str]:
    """Titles of the articles in ``category`` and, down to ``depth`` levels, its sub-categories."""
    seen = seen if seen is not None else set()
    titles: list[str] = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": "500",
        "cmtype": "page|subcat",
    }
    while True:
        data = _get(params, pause_s)
        for m in data.get("query", {}).get("categorymembers", []):
            title = m["title"]
            if m.get("ns") == 14:  # a sub-category
                sub = title.split(":", 1)[1]
                if depth > 0 and sub not in seen:
                    seen.add(sub)
                    titles += category_pages(sub, depth - 1, pause_s, seen)
            elif m.get("ns") == 0:
                titles.append(title)
        if "continue" not in data:
            break
        params |= data["continue"]
    return list(dict.fromkeys(titles))


def safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", title)[:120]


def fetch_wikitext(title: str, pause_s: float = 1.0) -> str | None:
    data = _get({"action": "parse", "prop": "wikitext", "redirects": "1", "page": title}, pause_s)
    if "error" in data:
        return None
    return data["parse"]["wikitext"]["*"]


def crawl(titles: list[str], out_dir: Path, pause_s: float = 1.0, log=sys.stderr) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"fetched": 0, "had": 0, "missing": 0}
    for i, title in enumerate(titles, 1):
        dest = out_dir / f"{safe_name(title)}.json"
        if dest.exists():
            counts["had"] += 1
            continue
        text = fetch_wikitext(title, pause_s)
        if text is None:
            counts["missing"] += 1
            continue
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps({"title": title, "wikitext": text}, ensure_ascii=False), "utf-8")
        tmp.replace(dest)
        counts["fetched"] += 1
        if i % 20 == 0:
            print(f"{time.strftime('%H:%M:%S')} {i}/{len(titles)} {counts}", file=log, flush=True)
    return counts
