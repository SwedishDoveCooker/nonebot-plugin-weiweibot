from vvpipe.importer import episode_from_name


def test_episode_number_from_common_file_names():
    assert episode_from_name("这就是中国 第351期：新疆最美的是人.mp4") == 351
    assert episode_from_name("China Now EP120 full.mkv") == 120
    assert episode_from_name("352.mp4") == 352
    assert episode_from_name("【350】沙漠绿色奇迹.mp4") == 350


def test_resolution_in_the_name_is_not_an_episode():
    assert episode_from_name("some video 1080p.mp4") is None


def test_falls_back_to_closest_bilibili_title():
    titles = {349: "中资出海的文化自信与尊重", 350: "沙漠绿色奇迹"}
    assert episode_from_name("沙漠绿色奇迹 1080p.mp4", titles) == 350
    assert episode_from_name("completely unrelated.mp4", titles) is None
