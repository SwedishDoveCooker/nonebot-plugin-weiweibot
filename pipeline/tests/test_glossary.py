from vvpipe import glossary


def test_short_cuts_at_sentence_ends():
    long_first = "第一句话" + "写得很长" * 10 + "。"  # 45 characters: enough on its own
    assert glossary.short(long_first + "第二句不该出现。") == long_first
    assert glossary.short("短句。第二句也要。") == "短句。第二句也要。"  # too short alone: take two
    assert glossary.short("很短。") == "很短。"
    assert len(glossary.short("字" * 400)) <= glossary.MAX_EXPLANATION


def test_list_items_headings_and_the_page_title_become_terms():
    text = (
        "这是一个足够长的开头段落,用来介绍这个条目到底在讲什么内容。\n\n"
        "## 大师兄\n\n选手在采访中说我是最强的，被叫做大师兄。\n\n"
        "## 简介\n\n泛泛而谈。\n\n- 鱼传家：传送回塔被单杀。\n- 3：太短\n"
        "- 童传塔/塔传童（别称）：另一个梗。\n"
    )
    got = dict(glossary.extract("某迷因", text))
    assert "大师兄" in got and "被叫做大师兄" in got["大师兄"]
    assert "简介" not in got and "3" not in got  # structural heading, too short
    assert got["鱼传家"] == "传送回塔被单杀。"
    assert "童传塔" in got and "塔传童" in got
    assert "某迷因" in got  # the page is about one meme


def test_pages_called_lists_do_not_make_their_title_a_term():
    assert "英雄联盟梗" not in dict(
        glossary.extract("英雄联盟梗", "一个足够长的第一段落用来介绍这个条目的内容和范围。\n")
    )


def test_generic_terms_are_dropped_by_page_count_and_by_everyday_use():
    pages = [(f"页{i}", f"- 毕业：含义{i}。\n- 鱼传家：传送。") for i in range(6)]
    pages.append(("独占页", "- 狂鼠：只在这里。\n- 日常词：很普通的词。"))
    common = ["今天我们谈日常词的问题"] * 30
    g = glossary.build(pages, common_texts=common, max_pages_per_term=4, max_common=12)
    assert "毕业" not in g and "鱼传家" not in g  # defined by six pages: generic
    assert "日常词" not in g  # shows up in ordinary sentences
    assert g["狂鼠"] == [{"page": "独占页", "text": "只在这里。"}]


def test_find_takes_the_longest_non_overlapping_terms_in_order():
    g = {
        "大师兄": [{"page": "p", "text": "a"}],
        "师兄": [{"page": "q", "text": "b"}],
        "鱼传家": [{"page": "r", "text": "c"}],
    }
    assert [t for t, _ in glossary.find("鱼传家和大师兄都来了", g)] == ["鱼传家", "大师兄"]
    assert glossary.find("什么都没有", g) == []
    assert len(glossary.find("鱼传家大师兄", g, limit=1)) == 1


def test_clean_entries_drops_image_remnants_and_tiny_explanations():
    g = {
        "甲": [{"page": "p", "text": "Dacat.jpg|快给我变"}],
        "乙": [{"page": "p", "text": "短"}],
        "丙": [{"page": "p", "text": "一个像样的解释文字。"}, {"page": "q", "text": "x.png"}],
    }
    assert glossary.clean_entries(g) == {"丙": [{"page": "p", "text": "一个像样的解释文字。"}]}


def test_parse_numbers():
    assert glossary.parse_numbers("删除: 0, 3,5", 10) == {0, 3, 5}
    assert glossary.parse_numbers("删除: 无", 10) == set()
    assert glossary.parse_numbers("删除：2, 99", 10) == {2}  # out-of-range numbers are ignored
    # a talkative answer: only the first 删除 line counts (later second thoughts are ignored)
    assert glossary.parse_numbers("删除: 7\nWait, let me reconsider.\n删除: 1,2", 10) == {7}
    assert glossary.parse_numbers("没有格式的回答 1 2 3", 10) == set()


def test_filter_generic_removes_what_the_model_names_and_survives_failures():
    g = {
        t: [{"page": "p", "text": f"{t}的解释文字很长很长"}]
        for t in ("晚安", "鱼传家", "加班", "大师兄")
    }
    calls = []

    def ask(system, user):
        calls.append(user)
        if len(calls) == 2:
            raise RuntimeError("api down")
        return "删除: 0, 1"  # the first two of the batch, by sorted order

    out = glossary.filter_generic(g, ask, batch=2)
    sorted_terms = sorted(g)
    assert sorted_terms[0] not in out and sorted_terms[1] not in out  # first batch: dropped
    assert sorted_terms[2] in out and sorted_terms[3] in out  # second batch failed: kept


def test_more_passes_catch_what_one_pass_missed():
    g = {t: [{"page": "p", "text": f"{t}的解释文字很长很长"}] for t in ("甲", "乙", "丙", "丁")}
    answers = iter(["删除: 无", "删除: 0", "删除: 0"])  # pass 1 finds nothing; pass 2 flags one

    def ask(system, user):
        return next(answers)

    out = glossary.filter_generic(g, ask, batch=4, passes=2)
    assert len(out) == 3
