from vvpipe import wikitext


def test_links_templates_and_markup():
    text = (
        "'''数字梗'''是[[网络用语|网络流行语]]的一种{{黑幕|其实很好懂}}。"
        "{{noteTA|G1=IT}}[[文件:x.jpg|200px]]<ref>来源</ref>"
    )
    assert wikitext.clean(text) == "数字梗是网络流行语的一种其实很好懂。\n"


def test_headings_and_lists():
    text = "== 简介 ==\n正文\n* 条目一\n** 条目二\n=== 子节 ===\n后文"
    assert wikitext.clean(text) == "## 简介\n\n正文\n- 条目一\n- 条目二\n\n## 子节\n\n后文\n"


def test_nested_templates_are_removed():
    assert wikitext.clean("甲{{a|b{{c|d}}e}}乙") == "甲乙\n"
    assert wikitext.clean("{{lang|ja|こんにちは}}") == "こんにちは\n"


def test_tables_become_rows():
    text = '{|class="wikitable"\n! 梗 !! 含义\n|-\n| 666 || 厉害\n|-\n| style="x" | 233 || 笑\n|}'
    assert wikitext.clean(text) == "梗 | 含义\n666 | 厉害\n233 | 笑\n"


def test_external_links_and_entities():
    assert wikitext.clean("见[https://example.org 官网]&amp;[https://example.org]") == "见官网&\n"


def test_chunks_keep_their_section_path_and_never_mix_sections():
    text = "前言文字\n\n## 典故\n\n### 一般\n\n- 114514：臭\n- 1919：810\n\n### 其他\n\n- 233：笑\n"
    got = wikitext.chunks("数字梗", text)
    assert got == [
        "《数字梗》\n前言文字",
        "《数字梗》 > 典故 > 一般\n- 114514：臭\n- 1919：810",
        "《数字梗》 > 典故 > 其他\n- 233：笑",
    ]


def test_chunks_are_bounded_and_long_paragraphs_are_cut():
    para = "这是一个很长的句子。" * 120
    got = wikitext.chunks("T", "## S\n\n" + para, max_chars=200)
    assert len(got) >= 6
    assert all(len(c) <= 200 + 30 for c in got)
    assert "".join(c.split("\n", 1)[1] for c in got) == para


def test_entries_keep_each_term_name_first_and_merge_tiny_ones():
    long_item = "- 1919：" + "很" * 150
    text = "## 典故\n\n- 3：\n- 内恰的排名。\n" + long_item + "\n\n## 其他\n\n- 233：笑"
    got = wikitext.entries("数字梗", text)
    assert got[0] == "《数字梗》 > 典故\n3：\n内恰的排名。\n1919：" + "很" * 150
    assert got[1] == "《数字梗》 > 其他\n233：笑"


def test_entries_never_exceed_the_limit_and_lose_nothing():
    para = "这是一个很长的句子。" * 120
    got = wikitext.entries("T", "## S\n\n" + para, max_chars=200)
    assert all(len(c) <= 200 + 20 for c in got)
    assert "".join(c.split("\n", 1)[1].replace("\n", "") for c in got) == para
