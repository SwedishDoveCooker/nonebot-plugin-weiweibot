"""List and download the videos of a Bilibili account without logging in, in 1080p.

A guest normally gets 480p. The web player's guest ("try look") mode, which several userscripts
use, is different: the *non-wbi* player API with ``try_look=1`` also offers the 1080p DASH
streams. This module asks that API directly, downloads the video and audio streams and merges
them with ffmpeg. Nothing here needs an account, so the cookie never expires and nothing has to
be re-sent every week.

Bilibili throttles listing requests (-352) after a few pages; ``list_videos`` waits and retries.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
MIN_HEIGHT = 1000
_WBI_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29,
    28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25,
    54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]  # fmt: skip
_DM = {
    "dm_img_list": "[]",
    "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
    "dm_cover_img_str": (
        "QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgNjMwIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ"
    ),
    "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
}


class Blocked(RuntimeError):
    """Bilibili's risk control rejected the request (-352 / HTTP 412): wait and try again."""


class NoHighQuality(RuntimeError):
    """The video has no 1080p stream for guests; never fall back to something smaller."""


@dataclass
class Video:
    bvid: str
    title: str
    length_s: int
    pub: str  # YYYY-MM-DD


def windows(since: dt.date, until: dt.date, days: int) -> list[tuple[dt.datetime, dt.datetime]]:
    """Consecutive [begin, end] windows covering since..until (end of the last day included)."""
    out = []
    start = dt.datetime.combine(since, dt.time.min)
    stop = dt.datetime.combine(until, dt.time.max).replace(microsecond=0)
    while start <= stop:
        end = min(start + dt.timedelta(days=days) - dt.timedelta(seconds=1), stop)
        out.append((start, end))
        start = end + dt.timedelta(seconds=1)
    return out


_TAGS = re.compile(r"<[^>]+>")


def video_from_search(row: dict) -> Video:
    return Video(
        row["bvid"],
        _TAGS.sub("", row.get("title", "")).replace("&amp;", "&").strip(),
        _seconds(row.get("duration", "0")),
        time.strftime("%Y-%m-%d", time.localtime(row.get("pubdate", 0))),
    )


def _seconds(text: str) -> int:
    parts = [int(p) for p in str(text).split(":") if p.isdigit()]
    return sum(p * 60**i for i, p in enumerate(reversed(parts)))


class Session:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA), ("Referer", "https://www.bilibili.com/")]
        self.op.open("https://www.bilibili.com/", timeout=30).read()  # buvid3 / b_nut cookies
        self._mix: str | None = None

    def json(self, url: str) -> dict:
        try:
            data = json.loads(self.op.open(url, timeout=30).read())
        except urllib.error.HTTPError as err:
            if err.code in (412, 403, 429):
                raise Blocked(f"HTTP {err.code}") from err
            raise
        if data.get("code") == -352:
            raise Blocked("risk control (-352)")
        return data

    def _mixin(self) -> str:
        if self._mix is None:
            img = self.json("https://api.bilibili.com/x/web-interface/nav")["data"]["wbi_img"]
            key = (
                img["img_url"].rsplit("/", 1)[1].split(".")[0]
                + img["sub_url"].rsplit("/", 1)[1].split(".")[0]
            )
            self._mix = "".join(key[i] for i in _WBI_TAB)[:32]
        return self._mix

    def sign(self, params: dict) -> str:
        params = dict(params, wts=int(time.time()))
        query = urllib.parse.urlencode(
            sorted((k, "".join(c for c in str(v) if c not in "!'()*")) for k, v in params.items())
        )
        return query + "&w_rid=" + hashlib.md5((query + self._mixin()).encode()).hexdigest()

    # ---- listing -----------------------------------------------------------------------
    def list_videos(
        self, mid: int, pause_s: float = 6, retry_wait_s: float = 45, log=sys.stderr
    ) -> list[Video]:
        out: list[Video] = []
        for page in range(1, 200):
            params = {"mid": mid, "ps": 40, "pn": page, "order": "pubdate", "platform": "web"}
            params |= {"web_location": 1550101, **_DM}
            for attempt in range(6):
                try:
                    data = self.json(
                        "https://api.bilibili.com/x/space/wbi/arc/search?" + self.sign(params)
                    )
                    if data.get("code") != 0:
                        raise Blocked(f"code {data.get('code')}: {data.get('message')}")
                    break
                except Blocked as err:
                    print(f"listing page {page}: {err}, waiting ({attempt + 1}/6)", file=log)
                    if attempt == 5:
                        raise
                    time.sleep(retry_wait_s)
                    self.op.open("https://www.bilibili.com/", timeout=30).read()
            rows = data["data"]["list"]["vlist"]
            if not rows:
                break
            for r in rows:
                out.append(
                    Video(
                        r["bvid"],
                        r["title"],
                        _seconds(r.get("length", "0")),
                        time.strftime("%Y-%m-%d", time.localtime(r["created"])),
                    )
                )
            time.sleep(pause_s)
        return out

    def recent(self, mid: int) -> list[Video]:
        """The newest page only: what the daily check looks at."""
        params = {"mid": mid, "ps": 40, "pn": 1, "order": "pubdate", "platform": "web"}
        params |= {"web_location": 1550101, **_DM}
        data = self.json("https://api.bilibili.com/x/space/wbi/arc/search?" + self.sign(params))
        if data.get("code") != 0:
            raise Blocked(f"code {data.get('code')}: {data.get('message')}")
        return [
            Video(
                r["bvid"],
                r["title"],
                _seconds(r.get("length", "0")),
                time.strftime("%Y-%m-%d", time.localtime(r["created"])),
            )
            for r in data["data"]["list"]["vlist"]
        ]

    # ---- search-based listing ----------------------------------------------------------
    def search_window(
        self, mid: int, keyword: str, begin: dt.datetime, end: dt.datetime, pause_s: float = 2.0
    ) -> list[Video]:
        """Videos of ``mid`` found by searching ``keyword`` (the account's name) in a time window.

        The space-listing API is risk-controlled for guests, the search API is not. A window of a
        month holds well under the 1000 results one search can return.
        """
        out: list[Video] = []
        for page in range(1, 51):
            query = urllib.parse.urlencode(
                {
                    "search_type": "video",
                    "keyword": keyword,
                    "order": "pubdate",
                    "page": page,
                    "pubtime_begin_s": int(begin.timestamp()),
                    "pubtime_end_s": int(end.timestamp()),
                }
            )
            data = self.json("https://api.bilibili.com/x/web-interface/search/type?" + query)
            rows = (data.get("data") or {}).get("result") or []
            if not rows:
                break
            out += [video_from_search(r) for r in rows if r.get("mid") == mid]
            time.sleep(pause_s)
        return out

    def list_all(
        self, mid: int, keyword: str, since: dt.date, until: dt.date | None = None,
        window_days: int = 30, log=sys.stderr,
    ) -> list[Video]:  # fmt: skip
        seen: dict[str, Video] = {}
        for begin, end in windows(since, until or dt.date.today(), window_days):
            for v in self.search_window(mid, keyword, begin, end):
                seen.setdefault(v.bvid, v)
            print(f"{begin:%Y-%m-%d}: {len(seen)} videos so far", file=log, flush=True)
        return sorted(seen.values(), key=lambda v: v.pub, reverse=True)

    # ---- streams -----------------------------------------------------------------------
    def parts(self, bvid: str) -> list[dict]:
        return self.json(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}")["data"]

    def streams(self, bvid: str, cid: int, min_height: int = MIN_HEIGHT) -> tuple[dict, dict]:
        """(video, audio) DASH entries: 1080p H.264 when there is one, never anything smaller."""
        url = (
            "https://api.bilibili.com/x/player/playurl?"
            f"bvid={bvid}&cid={cid}&qn=80&fnval=4048&fnver=0&fourk=1&try_look=1"
        )
        data = self.json(url)
        if data.get("code") != 0:
            raise RuntimeError(f"playurl code {data.get('code')}: {data.get('message')}")
        dash = (data.get("data") or {}).get("dash") or {}
        return pick_streams(dash, min_height)

    def fetch_file(self, urls: list[str], dest: Path, log=sys.stderr) -> None:
        """Download one stream, resuming a partial file; tries the backup URLs in turn."""
        part = dest.with_suffix(dest.suffix + ".part")
        last: Exception | None = None
        for url in urls:
            try:
                have = part.stat().st_size if part.exists() else 0
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://www.bilibili.com/",
                        "Range": f"bytes={have}-",
                    },
                )
                with urllib.request.urlopen(req, timeout=60) as resp, open(part, "ab") as f:
                    if resp.status == 200 and have:  # server ignored the range: start over
                        f.truncate(0)
                    while chunk := resp.read(1 << 20):
                        f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(part, dest)
                return
            except (OSError, urllib.error.URLError) as err:
                last = err
                print(f"stream failed ({err}), trying the next URL", file=log)
        raise RuntimeError(f"all URLs failed: {last}")


def pick_streams(dash: dict, min_height: int = MIN_HEIGHT) -> tuple[dict, dict]:
    videos = [v for v in dash.get("video", []) if (v.get("height") or 0) >= min_height]
    if not videos:
        heights = sorted({v.get("height") for v in dash.get("video", [])})
        raise NoHighQuality(f"no {min_height}p stream for guests (offered: {heights})")
    # codecid 7 is H.264, which every machine here decodes; then HEVC (12), then AV1 (13)
    videos.sort(
        key=lambda v: ({7: 0, 12: 1, 13: 2}.get(v.get("codecid"), 3), -(v.get("bandwidth") or 0))
    )
    audios = sorted(dash.get("audio") or [], key=lambda a: -(a.get("bandwidth") or 0))
    if not audios:
        raise RuntimeError("no audio stream")
    return videos[0], audios[0]


def urls_of(stream: dict) -> list[str]:
    return [
        u
        for u in [
            stream.get("baseUrl") or stream.get("base_url"),
            *(stream.get("backupUrl") or stream.get("backup_url") or []),
        ]
        if u
    ]


def download(
    session: Session,
    bvid: str,
    dest_dir: Path,
    part_index: int = 0,
    log=sys.stderr,
    min_height: int = MIN_HEIGHT,
) -> Path:
    """Download part ``part_index`` of a video as <bvid>[_pN].mkv; returns the finished file."""
    from .extract import video_height

    parts = session.parts(bvid)
    cid = parts[part_index]["cid"]
    video, audio = session.streams(bvid, cid, min_height)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = bvid if part_index == 0 else f"{bvid}_p{part_index + 1}"
    final = dest_dir / f"{stem}.mkv"
    if final.exists():
        return final
    v_file, a_file = dest_dir / f"{stem}.video.m4s", dest_dir / f"{stem}.audio.m4s"
    session.fetch_file(urls_of(video), v_file, log)
    session.fetch_file(urls_of(audio), a_file, log)
    tmp = dest_dir / f"{stem}.merge.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(v_file),
            "-i",
            str(a_file),
            "-c",
            "copy",
            str(tmp),
        ],
        check=True,
    )
    height = video_height(tmp)
    if height < min_height:
        tmp.unlink(missing_ok=True)
        raise NoHighQuality(f"{bvid} came out as {height}p")
    os.replace(tmp, final)
    v_file.unlink(missing_ok=True)
    a_file.unlink(missing_ok=True)
    return final
