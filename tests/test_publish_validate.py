"""publish-validate の判定ロジック(ネットワーク不要部分)のテスト。"""
import json

from tools.content_pipeline.publish_validate import (check_faq, check_identity, check_numbers,
                                                      parse_ldjson)

CFG = {"site_name": "KPOP JOURNAL", "og_site_name": "KPOP JOURNAL", "title_suffix": " - KPOP JOURNAL",
       "alternate_names": ["Kジャーナル", "K-Journal", "KPOPジャーナル", "kpopjournal"],
       "description_min_chars": 10, "description_max_chars": 160, "post_title_max_chars": 60}


def test_leading_zero_loss_is_caught():
    errs = check_numbers("<p>会員番号 000000141</p>", "<p>会員番号 00141</p>", "本文")
    assert len(errs) == 1 and "000000141" in errs[0] and "00141" in errs[0]


def test_identical_render_passes_and_entities_ok():
    raw = '<!-- wp:paragraph {"id":999} --><p><a href="https://x.jp/a?b=1&c=2">11/14 18:00</a> 1,200円</p>'
    rendered = '<p><a href="https://x.jp/a?b=1&#038;c=2">11/14 18:00</a> 1,200円</p>\n<p>追加 2026</p>'
    assert check_numbers(raw, rendered, "本文") == []


def test_changed_url_and_count_are_caught():
    assert check_numbers('<a href="https://a.jp/p/123">x</a>', '<a href="https://a.jp/p/124">x</a>', "b")
    assert check_numbers("<p>5 5</p>", "<p>5</p>", "b")  # 回数も見る


def _faq(q="Q1はいつ?", a="11月14日です。"):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}}]}


def _doc(ld, visible="<h3>Q1はいつ?</h3><p>11月14日です。</p>"):
    return visible + f'<script type="application/ld+json">{ld}</script>'


def test_faq_ok():
    doc = _doc(json.dumps(_faq(), ensure_ascii=False))
    nodes, errs = parse_ldjson(doc)
    assert check_faq(nodes, errs, doc) == []


def test_faq_missing_broken_invalid_hidden():
    doc = "<p>本文</p>"
    assert any("無い" in e for e in check_faq(*parse_ldjson(doc), doc))
    broken = _doc('{"@type":"FAQPage", "mainEntity": [}')
    assert any("壊れて" in e for e in check_faq(*parse_ldjson(broken), broken))
    bad = _doc(json.dumps({"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "Q1はいつ?"}]},
                          ensure_ascii=False))
    assert any("acceptedAnswer" in e for e in check_faq(*parse_ldjson(bad), bad))
    hidden = _doc(json.dumps(_faq(), ensure_ascii=False), visible="<p>別の本文</p>")
    assert any("見えていない" in e for e in check_faq(*parse_ldjson(hidden), hidden))
    # grep なら通ってしまう「文字列としては FAQPage を含むが JSON が壊れている」ケース
    assert check_faq(*parse_ldjson(broken), broken)


def _head(alt=None, desc="これは十分な長さの説明文です。", title="記事 - KPOP JOURNAL", site="KPOP JOURNAL"):
    alt = alt if alt is not None else CFG["alternate_names"]
    g = {"@graph": [{"@type": "WebSite", "name": "KPOP JOURNAL", "alternateName": alt},
                    {"@type": "Organization", "name": "KPOP JOURNAL", "alternateName": alt}]}
    return (f'<title>{title}</title><meta name="description" content="{desc}" />'
            f'<meta property="og:site_name" content="{site}" />'
            f'<script type="application/ld+json">{json.dumps(g, ensure_ascii=False)}</script>')


def _identity(head, title_out="記事 - KPOP JOURNAL", stored="これは十分な長さの説明文です。", blog="KPOP JOURNAL"):
    nodes, _ = parse_ldjson(head)
    return check_identity(CFG, "記事", title_out, head, nodes, stored, blog)


def test_identity_ok():
    assert _identity(_head()) == []


def test_identity_mismatches():
    assert any("alternateName" in e for e in _identity(_head(alt=CFG["alternate_names"] + ["K Journal"])))
    assert any("<title>" in e for e in _identity(_head(), title_out="記事 | KPOP JOURNAL"))
    assert any("description" in e for e in _identity(_head(desc="別の説明文で十分な長さがあるもの")))
    assert any("og:site_name" in e for e in _identity(_head(site="KPOP JOURNAL - Kジャーナル")))
    assert any("blogname" in e for e in _identity(_head(), blog="K Journal"))
    assert any("空" in e for e in _identity(_head(), stored=""))
