"""内部リンクの自動挿入は FAQ の答えと出典の段落に入れない(2026-11-12)。

FAQ の答え(<p class="kpop-faq-a">)にリンクを足すと、FAQPage JSON-LD の text と
本文がずれる。post 27634 で無関係な記事(IVEレイの渋谷イベント)が答えの末尾に付いた。
"""
from lib import internal_links as il

REL = [{"url": "https://www.kpopjournal.tokyo/ive-x/", "title": "IVEレイ、渋谷で韓国メイクイベント登場"}]


def _run(body):
    il.ARTIST_NAMES = set(il.ARTIST_NAMES) | {"IVE"}
    return il._insert_inline_links(body, REL)


def test_faq_answer_gets_no_link():
    body = ('<p>リード</p>'
            '<div class="kpop-faq-item"><h3 class="kpop-faq-q">MCは?</h3>'
            '<p class="kpop-faq-a">13日はチャン・ウォニョン(IVE)です。</p></div>')
    assert "ive-x" not in _run(body)


def test_citation_paragraph_gets_no_link():
    body = '<p>リード</p><p class="kpop-citation-source">参考: IVE公式</p>'
    assert "ive-x" not in _run(body)


def test_normal_paragraph_still_gets_link():
    body = '<p>リード</p><p>13日はIVEが出演します。</p>'
    assert "ive-x" in _run(body)
