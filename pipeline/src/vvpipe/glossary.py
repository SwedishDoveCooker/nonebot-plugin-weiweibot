"""A glossary of slang and memes, built from the cleaned wiki pages.

The bot reads group chat; when a message contains a term from here, the model is handed the
term's short meaning for that turn, so it understands what people are alluding to. Generic
words must not trigger this, so a term is kept only when it is not an everyday word: it must be
defined by few pages and be rare in ordinary speech (the show's subtitles stand in for that).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

MAX_EXPLANATION = 130
# Headings that structure a page instead of naming a term.
_STRUCTURAL = re.compile(
    r"^(简介|概述|来源|起源|典故|由来|衍生|相关|相关条目|外部链接|参考资料|参见|注释|脚注|备注|其他|"
    r"争议|评价|历史|详情|角色|人物|登场作品|使用|用法|影响|总结|评论|分类|综合篇|目录|"
    r"一般典故|其他典故|游戏内|游戏外|原作|事件|结果|后续|补充|图片|视频|音乐|台词|关联|"
    r"与.{1,6}的关系|.{1,6}相关|.{0,4}梗|.{0,4}用语)$"
)
_ITEM = re.compile(r"^- ([^：:]{1,24})[：:]\s*(.+)$")
_SENTENCE_END = "。！？"


def short(text: str, limit: int = MAX_EXPLANATION) -> str:
    """The first sentence or two of ``text``, cut at ``limit`` characters."""
    text = re.sub(r"\s+", " ", text).strip()
    out = ""
    for part in re.split(rf"(?<=[{_SENTENCE_END}])", text):
        if out and len(out) + len(part) > limit:
            break
        out += part
        if len(out) >= 40:
            break
    out = out or text
    return out if len(out) <= limit else out[: limit - 1] + "…"


def _terms(name: str) -> list[str]:
    """Names of one entry: "A/B", "A、B" and "A（别称）" give several terms."""
    name = re.sub(r"[（(][^）)]*[）)]", "", name)
    out = []
    for part in re.split(r"[/、,，;；]|\s{2,}", name):
        part = part.strip(" \"'“”‘’「」『』《》")
        if _usable(part):
            out.append(part)
    return out


def _usable(term: str) -> bool:
    if not 2 <= len(term) <= 16 or _STRUCTURAL.match(term):
        return False
    if re.fullmatch(r"[\d\W_]+", term):  # digits and symbols only
        return False
    if re.search(r"[。！？：:;；=<>|\[\]{}]", term):
        return False
    letters = re.sub(r"[^A-Za-z]", "", term)
    return len(letters) == 0 or len(term) >= 3  # a two-letter latin word is far too common


def extract(title: str, text: str) -> list[tuple[str, str]]:
    """(term, short explanation) pairs found in a cleaned page."""
    out: list[tuple[str, str]] = []
    lines = text.splitlines()
    heading: str | None = None
    body: list[str] = []

    def close() -> None:
        if heading and body:
            for term in _terms(heading):
                out.append((term, short(" ".join(body))))

    for line in lines:
        if m := re.match(r"^#{2,6} (.*)$", line):
            close()
            heading, body = m.group(1).strip(), []
            continue
        if not line.strip():
            continue
        if m := _ITEM.match(line.strip()):
            for term in _terms(m.group(1)):
                out.append((term, short(m.group(2))))
            continue
        if heading is not None and len(" ".join(body)) < 200:
            body.append(re.sub(r"^- ", "", line.strip()))
    close()
    # a page about one meme (title is the meme): its first paragraph explains it
    if not re.search(r"梗|用语|列表|文化|术语", title) and _usable(title):
        first = next(
            (
                ln
                for ln in lines
                if ln.strip() and not ln.startswith(("#", "-", "来源")) and len(ln) > 20
            ),
            "",
        )
        if first:
            out.append((title, short(first)))
    return out


def build(
    pages: Iterable[tuple[str, str]],
    common_texts: Iterable[str] = (),
    max_pages_per_term: int = 4,
    max_common: int = 12,
) -> dict[str, list[dict]]:
    """Glossary {term: [{"page": ..., "text": ...}, ...]} from (title, cleaned text) pairs.

    ``common_texts`` are ordinary sentences (the subtitles): a term occurring in more than
    ``max_common`` of them is an everyday word, not a meme, and is dropped.
    """
    found: dict[str, dict[str, str]] = defaultdict(dict)
    for title, text in pages:
        for term, expl in extract(title, text):
            found[term].setdefault(title, expl)
    found = {t: d for t, d in found.items() if len(d) <= max_pages_per_term}
    if common_texts:
        blob = [s for s in common_texts]
        counts = dict.fromkeys(found, 0)
        by_len: dict[int, set[str]] = defaultdict(set)
        for t in found:
            by_len[len(t)].add(t)
        for s in blob:
            seen: set[str] = set()
            for n, terms in by_len.items():
                for i in range(len(s) - n + 1):
                    if s[i : i + n] in terms:
                        seen.add(s[i : i + n])
            for t in seen:
                counts[t] += 1
        found = {t: d for t, d in found.items() if counts[t] <= max_common}
    return {t: [{"page": p, "text": x} for p, x in d.items()] for t, d in sorted(found.items())}


def save(glossary: dict, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(glossary, ensure_ascii=False, separators=(",", ":")), "utf-8")
    tmp.replace(path)


def find(text: str, glossary: dict, limit: int = 4) -> list[tuple[str, list[dict]]]:
    """Terms of ``glossary`` found in ``text``: longest win, no overlaps, at most ``limit``."""
    lengths = sorted({len(t) for t in glossary}, reverse=True)
    taken = [False] * len(text)
    hits: list[tuple[int, str]] = []
    for n in lengths:
        for i in range(len(text) - n + 1):
            term = text[i : i + n]
            if term in glossary and not any(taken[i : i + n]):
                hits.append((i, term))
                for k in range(i, i + n):
                    taken[k] = True
    hits.sort()
    return [(t, glossary[t]) for _, t in hits[:limit]]


_JUNK_EXPLANATION = re.compile(r"\.(jpg|png|gif|webp)|^\W*$|\|", re.I)


def clean_entries(glossary: dict) -> dict:
    """Drop definitions that are image remnants or too short to explain anything."""
    out = {}
    for term, defs in glossary.items():
        good = [d for d in defs if len(d["text"]) >= 6 and not _JUNK_EXPLANATION.search(d["text"])]
        if good:
            out[term] = good
    return out


FILTER_SYSTEM = (
    "你在整理一份网络梗词典。下面每行是“编号 | 词 | 解释片段”。"
    "找出其中日常聊天里会很自然地说出来、并不特指某个梗的词或短语"
    "(例如“晚安”“加班”“吃火锅”“哈哈哈哈”),这些词会在普通对话里误触发,必须删掉。"
    "有明确梗义、圈内黑话、专有名词、作品或节目里的特定用语的词要保留。"
    "不要写任何解释。只输出一行,格式固定为“删除: 编号,编号,编号”;一个都不用删就输出“删除: 无”。"
)


def parse_numbers(answer: str, limit: int) -> set[int]:
    """The numbers after the first "删除:" in the answer; anything else in it is ignored."""
    marks = re.findall(r"删除[:：]\s*([^\n]*)", answer)
    if not marks:
        return set()
    return {int(n) for n in re.findall(r"\d+", marks[0]) if int(n) < limit}


def filter_generic(
    glossary: dict, ask, batch: int = 60, passes: int = 1, seed: int = 1, log=None
) -> dict:
    """Remove everyday words with a language model. ``ask(system, user) -> str`` does one call.

    The model's verdicts vary from run to run, so with ``passes`` > 1 the terms are shuffled into
    different batches each time and a term is dropped if any pass flags it. Wrongly dropping a rare
    meme costs little; keeping "晚安" would make the bot chime in on ordinary chat.
    """
    import random

    rng = random.Random(seed)
    dropped: set[str] = set()
    for n in range(passes):
        terms = sorted(glossary)
        if n:
            rng.shuffle(terms)
        for start in range(0, len(terms), batch):
            chunk = terms[start : start + batch]
            rows = [f"{i} | {t} | {glossary[t][0]['text'][:30]}" for i, t in enumerate(chunk)]
            try:
                answer = ask(FILTER_SYSTEM, "\n".join(rows))
            except Exception as err:  # noqa: BLE001 - a failed batch is kept as it is, not dropped
                if log:
                    log(f"pass {n + 1} batch at {start} failed: {err!r}")
                continue
            dropped |= {chunk[i] for i in parse_numbers(answer, len(chunk))}
            if log and (start // batch) % 20 == 0:
                log(
                    f"pass {n + 1}: {start + len(chunk)}/{len(terms)} dropped so far {len(dropped)}"
                )
    return {t: d for t, d in glossary.items() if t not in dropped}


# Chat fillers the model sometimes lets through; they must never trigger an explanation.
STOP_TERMS = frozenset(
    [
        "哈哈哈",
        "哈哈哈哈",
        "哈哈哈哈哈",
        "无语",
        "你说得对",
        "晚安",
        "早安",
        "加班",
        "吃火锅",
        "行吧",
        "好的",
        "谢谢",
        "对不起",
        "没问题",
        "不知道",
        "真的吗",
        "是吗",
        "好吧",
        "可以",
        "不行",
        "没事",
        "厉害",
        "牛逼",
        "笑死",
        "太强了",
        "怎么了",
        "为什么",
        "什么意思",
    ]
)


def confirm_drops(
    glossary: dict,
    candidates: Iterable[str],
    ask,
    passes: int = 3,
    quorum: int = 2,
    batch: int = 60,
) -> set[str]:
    """Ask again about flagged terms; only those flagged ``quorum`` times are really dropped."""
    import random

    cands = sorted(set(candidates) & set(glossary))
    votes = dict.fromkeys(cands, 0)
    rng = random.Random(7)
    for n in range(passes):
        order = cands[:]
        if n:
            rng.shuffle(order)
        for start in range(0, len(order), batch):
            chunk = order[start : start + batch]
            rows = [f"{i} | {t} | {glossary[t][0]['text'][:30]}" for i, t in enumerate(chunk)]
            try:
                answer = ask(FILTER_SYSTEM, "\n".join(rows))
            except Exception:  # noqa: BLE001 - no answer is no vote
                continue
            for i in parse_numbers(answer, len(chunk)):
                votes[chunk[i]] += 1
    return {t for t, v in votes.items() if v >= quorum}
