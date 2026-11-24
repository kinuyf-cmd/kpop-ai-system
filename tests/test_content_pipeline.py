"""自律コンテンツパイプラインの機械判定部分のテスト(ネットワーク・claude 不要)。"""
import json

from tools.content_pipeline.pipeline import judge_factcheck, render_faq
from tools.content_pipeline.publish_validate import check_faq, parse_ldjson


def _claim(text, typ="date", st="confirmed", urls=("https://mma.melon.com/a", "https://www.unext.jp/b")):
    return {"text": text, "type": typ, "status": st,
            "primary_sources": [{"url": u} for u in urls]}


def test_factcheck_pass():
    fc = {"claims": [_claim("11月15日(土) 18:00 から U-NEXT で独占ライブ配信")], "discrepancies": []}
    assert judge_factcheck(fc, "MMAは11月15日 18:00からU-NEXTで配信") == []


def test_factcheck_requires_two_primary_publishers():
    fc = {"claims": [_claim("11月15日", urls=("https://mma.melon.com/a", "https://mma.melon.com/b"))]}
    assert any("2つ以上" in p for p in judge_factcheck(fc, "11月15日"))
    # 同じ組織の別ドメイン(publisher 名で判定)も1つ。co.jp を「co.jp」と数えない
    same = {"claims": [{"text": "U-NEXT独占", "type": "platform", "status": "confirmed", "primary_sources": [
        {"url": "https://help.unext.jp/a", "publisher": "U-NEXT"},
        {"url": "https://www.unext.co.jp/b", "publisher": "U-NEXT 公式"}]}]}
    assert any("2つ以上" in p for p in judge_factcheck(same, "U-NEXT"))
    two = {"claims": [{"text": "U-NEXT独占", "type": "platform", "status": "confirmed", "primary_sources": [
        {"url": "https://help.unext.jp/a"}, {"url": "https://www.unext.co.jp/b"}, ]}]}
    assert judge_factcheck(two, "U-NEXT") == []  # publisher 無しなら登録ドメイン(unext.jp / unext.co.jp)


def test_date_token_ignores_labels():
    fc = {"claims": [_claim("11月14日")]}
    assert judge_factcheck(fc, "DAY1:11月14日 DAY2:11月14日") == []


def test_factcheck_rejects_unconfirmed_discrepancy_and_unchecked_dates():
    fc = {"claims": [_claim("会場は高尺スカイドーム", typ="name", st="unconfirmed")],
          "discrepancies": ["記事の18:00は公式では17:00"]}
    probs = judge_factcheck(fc, "11月15日 18:00 高尺スカイドーム")
    assert any("unconfirmed" in p for p in probs)
    assert any("食い違い" in p for p in probs)
    assert any("11月15日" in p for p in probs) and any("18:00" in p for p in probs)
    assert judge_factcheck({"claims": []}, "x") == ["ファクトチェックの claims が空"]


def test_render_faq_is_valid_and_visible():
    h = render_faq([{"q": "MMA2026はどこで見られる?", "a": "日本では U-NEXT が独占配信します。"},
                    {"q": "</script>を含む質問?", "a": "エスケープされる"}])
    nodes, errs = parse_ldjson(h)
    assert errs == []
    assert check_faq(nodes, errs, h) == []
    faq = [n for n in nodes if n.get("@type") == "FAQPage"][0]
    assert len(faq["mainEntity"]) == 2
    assert "</script>を" not in h.split('<script type="application/ld+json">')[1].split("</script>")[0]


def test_sanitize_strips_injection():
    from tools.content_pipeline.sanitize import sanitize
    dirty = ('<p onclick="x()">本文<script>alert(1)</script></p><a href="javascript:alert(1)">x</a>'
             '<iframe src="https://e.vil"></iframe><img src=x onerror=alert(1)>'
             '<a href="https://official.jp/a">公式</a><p class="kpj-sources evil">出典</p>')
    out, removed = sanitize(dirty)
    low = out.lower()
    assert "<script" not in low and "onclick" not in low and "javascript:" not in low
    assert "<iframe" not in low and "<img" not in low and "onerror" not in low
    assert '<a href="https://official.jp/a" rel="noopener" target="_blank">公式</a>' in out
    assert '<p class="kpj-sources">出典</p>' in out
    assert any(r.startswith("<script") for r in removed)


def test_validator_flags_unsafe_raw():
    from tools.content_pipeline.publish_validate import check_unsafe_html
    ok = '<p>x</p><script type="application/ld+json">{}</script>'
    assert check_unsafe_html(ok) == []
    assert check_unsafe_html('<script>alert(1)</script>')
    assert check_unsafe_html('<p onmouseover="x">a</p>')
    assert check_unsafe_html('<a href="javascript:void(0)">a</a>')
    assert check_unsafe_html('<iframe src="https://a"></iframe>')
