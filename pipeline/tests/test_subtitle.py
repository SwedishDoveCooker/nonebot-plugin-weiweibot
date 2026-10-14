import numpy as np

from vvpipe import extract, subtitle


def test_clean_strips_trailing_punctuation_and_whitespace():
    assert subtitle.clean("  其实 不完全是因为这个。 ") == "其实 不完全是因为这个"
    assert subtitle.clean("a   b,") == "a b"


def test_same_text_masks():
    a = np.zeros((10, 10), bool)
    a[2:5, 2:8] = True
    b = a.copy()
    assert subtitle.same_text(a, b)
    c = np.zeros((10, 10), bool)
    c[6:9, 1:4] = True
    assert not subtitle.same_text(a, c)
    assert not subtitle.same_text(None, a)


def test_has_text_threshold():
    empty = np.zeros((50, 50), bool)
    assert not subtitle.has_text(empty)
    full = np.ones((50, 50), bool)
    assert subtitle.has_text(full)


def test_sponsor_tail_is_stripped_but_real_text_survives():
    assert subtitle.strip_sponsor("中国一代高端自酒") == "中国"
    assert subtitle.strip_sponsor("二八比例端一代高销自酒") == "二八比例"
    assert subtitle.strip_sponsor("新一代高端自酒") == ""
    assert subtitle.strip_sponsor("新一代高") == ""
    assert (
        subtitle.strip_sponsor("众所周知中国在应用研究方面特别强")
        == "众所周知中国在应用研究方面特别强"
    )
    assert subtitle.strip_sponsor("引力波其实不存在自酒") == "引力波其实不存在"
    assert subtitle.strip_sponsor("某些领域会很强高埔自酒") == "某些领域会很强"
    assert subtitle.strip_sponsor("蕲=代商纳自酒") == ""
    assert subtitle.strip_sponsor("《这就是中国》由新一代高端白酒国缘特约播出") == ""
    assert subtitle.strip_sponsor("或者是产量更高的白酒") == "或者是产量更高的白酒"
    assert subtitle.strip_sponsor("白酒这肯定应该是合成生物学") == "白酒这肯定应该是合成生物学"
    assert subtitle.strip_sponsor("合肥正在建设新一代可控核聚变装置BEST") == (
        "合肥正在建设新一代可控核聚变装置BEST"
    )


def test_norm_ignores_punctuation_and_case():
    assert extract.norm("Hello, 世界!") == "hello世界"
