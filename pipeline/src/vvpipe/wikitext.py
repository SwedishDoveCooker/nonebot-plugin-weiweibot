"""Turn MediaWiki wikitext into readable plain text, for the bot's knowledge base.

Not a full parser: it keeps what a reader would read (paragraphs, headings, list items, table
cells, the visible text of links and of the few templates that only wrap text) and drops
everything else (infoboxes, navigation, references, images, styling).
"""

from __future__ import annotations

import html
import re

# Templates whose last argument is the text a reader sees (spoiler bars, language tags, ruby).
_KEEP_LAST = {"黑幕", "黑字", "heimu", "lang", "ruby", "tooltip", "color", "注", "bd", "吐槽"}
_INNER_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.S | re.I)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_LINK = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_FILE = re.compile(r"\[\[(?:file|image|文件|图像|图片|分类|category):[^\]]*\]\]", re.I)
_EXT_LINK = re.compile(r"\[(?:https?:)?//\S+ ([^\]]+)\]|\[(?:https?:)?//\S+\]")
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_TABLE_ATTR = re.compile(r"^[^|]*?\|(?!\|)")


def _template(match: re.Match) -> str:
    parts = match.group(1).split("|")
    name = parts[0].strip().lower()
    if name in _KEEP_LAST and len(parts) > 1:
        last = parts[-1]
        return last.split("=", 1)[-1].strip() if "=" in last and name != "lang" else last.strip()
    return ""


def _strip_templates(text: str) -> str:
    prev = None
    while prev != text:
        prev, text = text, _INNER_TEMPLATE.sub(_template, text)
    return text


def _cell(line: str) -> str:
    cells = []
    for raw in re.split(r"\|\||!!", line.lstrip("|!")):
        cell = _TABLE_ATTR.sub("", raw, count=1) if "=" in raw.split("|")[0] and "|" in raw else raw
        cells.append(cell.strip())
    return " | ".join(c for c in cells if c)


def clean(wikitext: str) -> str:
    text = _COMMENT.sub("", wikitext)
    text = _REF.sub("", text)
    text = _strip_templates(text)
    text = _FILE.sub("", text)
    text = _LINK.sub(lambda m: (m.group(2) if m.group(2) is not None else m.group(1)).strip(), text)
    text = _EXT_LINK.sub(lambda m: m.group(1) or "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = _TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    out: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        s = line.strip()
        if s.startswith(("|-", "|+")) or s in {"{|", "|}"}:
            continue  # table scaffolding: rows stay together
        if not s or s.startswith("__") or s == "----":
            if out and out[-1] != "":
                out.append("")
            continue
        if m := _HEADING.match(s):
            out += ["", "## " + m.group(2), ""]
            continue
        if s.startswith("{|"):
            continue
        if s.startswith(("|", "!")):
            row = _cell(s)
            if row:
                out.append(row)
            continue
        out.append(re.sub(r"^[*#:;]+\s*", "- ", s) if s[0] in "*#:;" else s)
    text = html.unescape("\n".join(out))
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def chunks(title: str, text: str, max_chars: int = 480) -> list[str]:
    """Split cleaned text into passages that each carry where they come from.

    A passage never mixes two sections and starts with "《title》> section > subsection", so a
    retrieved passage still says what it is about when it is read alone.
    """
    out: list[str] = []
    path: list[str] = []
    body: list[str] = []

    def label() -> str:
        return "》".join([f"《{title}", *path]) if path else f"《{title}》"

    def head() -> str:
        return (f"《{title}》" + (" > " + " > ".join(path) if path else "")) + "\n"

    def flush() -> None:
        if body:
            out.append(head() + "\n".join(body).strip())
            body.clear()

    size = 0
    for line in text.splitlines():
        if m := re.match(r"^(#{2,6}) (.*)$", line):
            flush()
            size = 0
            depth = len(m.group(1)) - 2
            path[:] = [*path[:depth], m.group(2).strip()]
            continue
        if not line.strip():
            continue
        while len(line) > max_chars:  # one very long paragraph: cut at a sentence end if possible
            cut = max(line.rfind(c, 0, max_chars) for c in "。！？；")
            cut = cut + 1 if cut > max_chars // 3 else max_chars
            if size + cut > max_chars:
                flush()
                size = 0
            body.append(line[:cut])
            flush()
            size, line = 0, line[cut:]
        if size + len(line) > max_chars:
            flush()
            size = 0
        body.append(line)
        size += len(line) + 1
    flush()
    return [c for c in out if len(c.split("\n", 1)[-1].strip()) >= 4]


def _cut(line: str, max_chars: int) -> list[str]:
    """Pieces of at most ``max_chars``, cut at a sentence end when there is one."""
    pieces = []
    while len(line) > max_chars:
        cut = max(line.rfind(c, 0, max_chars) for c in "。！？；")
        cut = cut + 1 if cut > max_chars // 3 else max_chars
        pieces.append(line[:cut])
        line = line[cut:]
    return [*pieces, line] if line else pieces


def entries(title: str, text: str, max_chars: int = 480, merge_below: int = 120) -> list[str]:
    """Passages for retrieval, one per entry: the name of a slang term stays the first words.

    Every list item (and every paragraph) is an entry; entries shorter than ``merge_below``
    are joined with the ones after them in the same section, up to ``max_chars``. A passage
    starts with "《title》 > section path", so it still says what it is about on its own.
    """
    out: list[str] = []
    path: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            where = " > ".join(path)
            out.append(f"《{title}》" + (f" > {where}" if where else "") + "\n" + buf.strip())
        buf = ""

    for line in text.splitlines():
        if m := re.match(r"^(#{2,6}) (.*)$", line):
            flush()
            path[:] = [*path[: len(m.group(1)) - 2], m.group(2).strip()]
            continue
        item = re.sub(r"^- ", "", line.strip())
        if not item:
            continue
        for piece in _cut(item, max_chars):
            if buf and len(buf) + len(piece) + 1 > max_chars:
                flush()
            buf = f"{buf}\n{piece}" if buf else piece
            if len(buf) >= merge_below:
                flush()
    flush()
    return [c for c in out if len(c.split("\n", 1)[-1].strip()) >= 4]
