from vvpipe.weekly_fetch import pick

ENTRIES = [
    {"id": "A", "title": "这就是中国 第351期：沙漠绿色奇迹｜#沙漠绿色奇迹｜#生态文明"},
    {"id": "B", "title": "这就是中国 第352期：新疆最美的是人｜#真实新疆"},
    {"id": "C", "title": "这就是中国 第352期：中国科创——中国基础科学研究的进展｜#中国科创"},
    {"id": "D", "title": "完全无关的视频"},
]


def test_topic_beats_a_mislabelled_number():
    # YouTube calls the Xinjiang episode 352; Bilibili calls it 351.
    assert pick(ENTRIES, 351, "《这就是中国》第351集 新疆最美的是人") == "B"
    assert pick(ENTRIES, 352, "《这就是中国》第352集 中国科创——中国基础科学研究的进展") == "C"


def test_minor_title_differences_still_match():
    entries = [{"id": "X", "title": "这就是中国 第347期：中国六张网构建民族复兴的坚实底座｜#基建"}]
    assert pick(entries, 346, "《这就是中国》第346集 中国“六张网”筑牢中国式现代化的基建底座") == "X"


def test_no_confident_match_returns_none():
    assert pick(ENTRIES, 353, "《这就是中国》第353集 一个还没有上传的话题") is None
    assert pick([], 353, "《这就是中国》第353集 x") is None
