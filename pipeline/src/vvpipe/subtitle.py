"""Reading the burned-in subtitles."""

from __future__ import annotations

import re

import cv2
import numpy as np

# Subtitle band in a 1920x1080 frame (left, top, right, bottom). VV used (235, 900, 1435, 990);
# this is slightly wider so long lines are not clipped.
CROP = (200, 895, 1500, 1000)
WHITE = 225
MIN_WHITE_PIXELS = 220

_TRAIL = re.compile(r"[　-〿＀-￯ -⁯.,!?;:\s]+$")


def crop(frame: np.ndarray) -> np.ndarray:
    left, top, right, bottom = CROP
    return frame[top:bottom, left:right]


def white_mask(band: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    return gray >= WHITE


def has_text(mask: np.ndarray) -> bool:
    return int(mask.sum()) >= MIN_WHITE_PIXELS


def same_text(a: np.ndarray | None, b: np.ndarray) -> bool:
    """True when two white-pixel masks are (nearly) the same glyphs in the same place."""
    if a is None:
        return False
    inter = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    return union > 0 and inter / union >= 0.85


# The sponsor logo ("新一代高端白酒") shares the subtitle band, so OCR reads it as text, often glued
# to the end of a real line and with typical misreads (商/销, 自/白).
_LOGO_CHARS = "新一代高商端销自白酒國緣"
_LOGO_TAIL = re.compile(rf"[{_LOGO_CHARS}\s]{{5,}}$")


# Sponsor credits and slogan lines are not speech at all.
_CREDITS = re.compile(r"国缘|國[橡缘緣]|特约播出|成大事必有缘|新一代高端[白日自]酒")
# The logo is often cut by the tight crop, leaving only "(高x)自酒" ("自" misreads "白").
_LOGO_FRAGMENT = re.compile(r"(?:高[一-鿿]{0,2})?自酒$")
_LOGO_TAIL2 = re.compile(r"[一代高商端销辅埔纳]{2,}[白自日]酒$")
_LOGO_LEAD = re.compile(r"新?一代$")  # what is left once the rest of the logo was cut away
_LOGO_STRAY = re.compile(r"[端商销高辅埔纳]{1,2}$")
_JUNK = re.compile(r"[=<>|\\]")


def strip_sponsor(text: str) -> str:
    """Remove a sponsor-logo tail; an empty result means the line was only logo or junk."""
    if _CREDITS.search(text) or _JUNK.search(text):
        return ""
    changed = False
    for _ in range(3):
        new = _LOGO_FRAGMENT.sub("", text)
        new = _LOGO_TAIL2.sub("", new)
        new = _LOGO_LEAD.sub("", new)
        new = _LOGO_TAIL.sub("", new).strip()
        if new == text:
            break
        text, changed = new, True
    if changed:  # a logo was glued on, so a stray half-cut character before it is logo too
        text = _LOGO_STRAY.sub("", text)
    compact = text.replace(" ", "")
    if len(compact) <= 1 or (len(compact) <= 4 and all(ch in _LOGO_CHARS for ch in compact)):
        return ""
    return text


def clean(text: str) -> str:
    return _TRAIL.sub("", re.sub(r"\s+", " ", text.strip()))


def tight_crop(band: np.ndarray, mask: np.ndarray, merge_gap: int = 90, pad: int = 8):
    """Crop the band to the leftmost run of subtitle glyphs.

    Subtitles are left aligned, while the channel logo can reach into the band from the right,
    so only the first cluster of white columns is kept.
    """
    cols = np.flatnonzero(mask.any(axis=0))
    if cols.size == 0:
        return None
    end = cols[0]
    for c in cols[1:]:
        if c - end > merge_gap:
            break
        end = c
    left = cols[0]
    rows = np.flatnonzero(mask[:, left : end + 1].any(axis=1))
    top, bottom = rows[0], rows[-1]
    h, w = mask.shape
    return band[
        max(0, top - pad) : min(h, bottom + pad + 1), max(0, left - pad) : min(w, end + pad + 1)
    ]


class Reader:
    """RapidOCR (PaddleOCR models on onnxruntime) wrapped for subtitle bands."""

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self.engine = RapidOCR()

    def read(self, band: np.ndarray, mask: np.ndarray | None = None) -> tuple[str, float]:
        """Recognise one subtitle line. Fast path: tight crop, recognition only."""
        if mask is not None:
            tight = tight_crop(band, mask)
            if tight is not None and tight.size:
                result, _ = self.engine(tight, use_det=False, use_cls=False, use_rec=True)
                if result:
                    text, conf = clean(result[0][0]), float(result[0][1])
                    if text and conf >= 0.6:
                        return text, conf
        return self._read_full(band)

    def _read_full(self, band: np.ndarray) -> tuple[str, float]:
        result, _ = self.engine(band)
        if not result:
            return "", 0.0
        # Boxes are returned in detection order; sort them left to right on one line.
        result = sorted(result, key=lambda r: min(p[0] for p in r[0]))
        text = " ".join(r[1] for r in result)
        conf = float(np.mean([float(r[2]) for r in result]))
        return clean(text), conf
