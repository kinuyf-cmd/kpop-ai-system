"""pre_publish_gate の非K-POPトピックBLOCK統合テスト(2026-05-29)

『나는 SOLO』婚活番組・政治論争の news/breaking 記事を公開前ゲートで BLOCK する。
設計: docs/superpowers/specs/2026-05-29-non-kpop-topic-filter-design.md
"""
from lib.pre_publish_gate import pre_publish_gate

# content_empty(<400字)を回避する十分な長さの本文ひな型
_PAD = "あ" * 450


def _gate(title, kind='news'):
    return pre_publish_gate(
        title=title,
        body_html=f"<p>{_PAD}</p>",
        kind=kind,
        source_url="https://www.xportsnews.com/article/2153986",
        slug="some-valid-slug-here",
        featured_media=123,
        categories=[1],
        excerpt="x" * 80,
        status='publish',
        skip_llm_factcheck=True,
    )


def test_naneun_solo_news_blocked():
    res = _gate("「私はソロ」31期メンバー団体飲み会、ギョンスとスンジャ不在")
    assert res['verdict'] == 'BLOCK'
    assert any(i['type'] == 'non_kpop_topic' for i in res['issues'])


def test_politics_news_blocked():
    res = _gate("최준희 \"좌파 없는 나라에 살고 싶다\" 발언 논란")
    assert res['verdict'] == 'BLOCK'
    assert any(i['type'] == 'non_kpop_topic' for i in res['issues'])


def test_legit_kpop_news_not_blocked_by_topic():
    # 正当なK-POP速報は non_kpop_topic で弾かれない(他理由のBLOCKは別問題)
    res = _gate("aespa、正規2集『LEMONADE』でカムバック")
    assert not any(i['type'] == 'non_kpop_topic' for i in res['issues'])


def test_structural_only_pass_skips_topic_check():
    # 注入後の構造専用パスでは内容判定を走らせない
    res = pre_publish_gate(
        title="「私はソロ」31期メンバー団体飲み会",
        body_html=f"<p>{_PAD}</p>",
        kind='news',
        structural_only=True,
        status='publish',
    )
    assert not any(i['type'] == 'non_kpop_topic' for i in res['issues'])
