import numpy as np

from vvpipe import extract


def test_same_line_tolerates_ocr_noise():
    assert extract.same_line("其实不完全是因为这个", "其实不完全是因为这")
    assert extract.same_line("众所周知中国在应用研究方面特别强", "众所周知中国在应用研究防面特别强")
    assert not extract.same_line("它加入了应用研究", "然后迅速地拉开了差距")
    assert not extract.same_line("", "abc")


def test_group_votes_prefer_frequent_then_longer():
    frame = np.zeros((2, 2, 3), np.uint8)
    g = extract.Group(0, 0, 0.1, frame)
    g.add(0, "其实不完全是因为这", 0.1, frame)
    g.add(1, "其实不完全是因为这个", 0.2, frame)
    assert g.text == "其实不完全是因为这个"  # tie: the longer reading wins
    g.add(2, "其实不完全是因为这", 0.3, frame)
    assert g.text == "其实不完全是因为这"  # now the more frequent reading wins
    assert g.sim == 0.3
