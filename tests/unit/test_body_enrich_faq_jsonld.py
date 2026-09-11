"""body_enrich が追記した FAQ に FAQPage JSON-LD を付ける(2026-09-11)

FAQ 本文だけ追記して schema を出していなかったため、リッチリザルトの機会を
落としていた。実測: FAQ を持つ37記事のうち schema があるのは14記事のみ。
pos5-7 帯の停滞主因は FAQPage 不在という実証があるため、機会損失が大きい。
"""
import json
import re
import sys

sys.path.insert(0, "/home/aiuser/kpop-ai-system")

from lib.body_enrich import _append_faq_jsonld

FAQ_HTML = (
    "<h2>よくある質問</h2>\n"
    "<h3>Q. Netflix以外で見る方法はありますか?</h3>\n"
    '<p>現状Netflixが基本です。<a href="https://example.test">関連記事</a></p>\n'
    "<h3>Q. 途中から見始めても楽しめますか?</h3>\n"
    "<p>1話から順番がおすすめです。</p>"
)


def _extract(html):
    m = re.search(r'application/ld\+json">\n(.*?)\n</script>', html, re.S)
    assert m, "JSON-LD が出力されていない"
    return json.loads(m.group(1))


def test_faq_jsonld_is_appended():
    data = _extract(_append_faq_jsonld(FAQ_HTML, "既存本文"))
    assert data["@type"] == "FAQPage"
    assert len(data["mainEntity"]) == 2
    assert data["mainEntity"][0]["name"] == "Netflix以外で見る方法はありますか?"


def test_inline_links_are_stripped_from_answer():
    """回答に内部リンクが注入されるため、schema にはタグを残さない。"""
    data = _extract(_append_faq_jsonld(FAQ_HTML, ""))
    text = data["mainEntity"][0]["acceptedAnswer"]["text"]
    assert "<a" not in text and "href" not in text
    assert "関連記事" in text


def test_not_appended_when_article_already_has_schema():
    """重複 schema を出さない。"""
    assert _append_faq_jsonld(FAQ_HTML, "<script>FAQPage</script>") == FAQ_HTML


def test_not_appended_when_no_faq():
    plain = "<h2>詳細・基本情報</h2><p>本文</p>"
    assert _append_faq_jsonld(plain, "") == plain
