"""内部リンクの関連性: 汎用語やタイトル長だけで無関係な記事へリンクしない。

2026-10-01: KGMA ハブ(post 21866)と『100日の嘘』(post 21915)の冒頭段落に、
二子玉川のポップアップ記事や無関係なゴシップ記事へのリンクが入った。
真因は _score_relevance のタイトル長ボーナス(20点)だけで閾値(15点)を超えることと、
段落の選定が「韓国」「ソウル」などの汎用語の一致で行われること。
"""
from lib.internal_links import _find_related_articles, _insert_inline_links

POPUP = {"title": "【東京・二子玉川】韓国・ソウルのローカルカルチャーを紹介。「andoor」初のPOP UP STORE開催",
         "url": "https://example.test/popup/"}
GOSSIP = {"title": "笠松将、韓国ファンを信じたら大恥…「空港にはIVEユジンのファンだけ…寂しい",
          "url": "https://example.test/gossip/"}
DRAMA = {"title": "韓国版『ドクターX ～白衣のマフィア～』キャスト・何話・配信日まとめ｜キム・ジウォン主演",
         "url": "https://example.test/doctor-x/"}
RIIZE = {"title": "RIIZE、新曲で音楽番組1位を獲得", "url": "https://example.test/riize/"}

KGMA_TITLE = "2026 KGMA 日程・出演者・Hulu配信情報"
KGMA_BODY = (
    "<p>K-POPの年末授賞式「2026 KGMA」が韓国・ソウルの高尺スカイドームで開かれます。</p>"
    "<p>日程と会場、日別の出演者を整理します。</p>"
    "<p>RIIZEとATEEZは2日目に出演します。</p>"
)


def test_generic_keyword_only_article_is_not_related():
    related = _find_related_articles(KGMA_BODY, KGMA_TITLE, [POPUP, GOSSIP, RIIZE])
    urls = [r["url"] for r in related]
    assert POPUP["url"] not in urls
    assert GOSSIP["url"] not in urls
    assert RIIZE["url"] in urls


def test_same_type_guide_is_related_by_title_tokens():
    title = "『100日の嘘』キャスト・全何話・配信日まとめ｜Netflixでいつから?"
    body = "<p>韓国ドラマ『100日の嘘』がNetflixで配信されます。</p><p>全16話です。</p>"
    related = _find_related_articles(body, title, [DRAMA, POPUP])
    assert [r["url"] for r in related] == [DRAMA["url"]]


def test_inline_link_never_goes_into_lead_paragraph():
    out = _insert_inline_links(KGMA_BODY, [dict(RIIZE, score=50)])
    lead = out.split("</p>")[0]
    assert "example.test" not in lead
    assert 'href="https://example.test/riize/"' in out


def test_inline_link_is_not_placed_by_generic_keyword():
    out = _insert_inline_links(KGMA_BODY, [dict(POPUP, score=50)])
    assert "example.test/popup" not in out
