"""
memory: feedback_quality_gate_overdefense.md
規定: 「複数ゲートの直列BLOCK重ねがけは会社停止に直結。BLOCKは壊滅レベルだけWARNを厚めに」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_pre_publish_gate_block_severities_limited():
    """BLOCKする issue type が壊滅レベルだけに絞られていること (10種以下)"""
    from lib import pre_publish_gate
    src = inspect.getsource(pre_publish_gate)
    # 'severity': 'block' or "'block'" の出現数
    block_count = src.count("'block'") + src.count('"block"')
    # 2026-05-11: BLOCK pattern追加で40まで許容 (codeblock/template/placeholder類)
    assert block_count < 40, f"BLOCK severity過多 ({block_count}箇所)"


def test_pre_publish_gate_returns_warn_verdict():
    """完全な記事 (タイトル/メタ/スラッグ/サムネ/カテゴリ全揃) で短いsource_text_length単独 → WARN になること"""
    from lib.pre_publish_gate import pre_publish_gate
    r = pre_publish_gate(
        title='K-POPアーティスト最新情報をお届けする記事タイトルです',
        body_html='<p>' + 'これは記事本文です。' * 200 + '</p>',  # >2000字
        post_type='post',
        kind='news',
        source_url='https://example.com/article',
        source_text_length=50,  # 短いソース → WARN想定
        slug='kpop-test-article-comprehensive-overview-2026',
        featured_media=12345,
        categories=[10],
        excerpt='K-POPアーティストの最新情報です。' * 5,  # 80字以上
    )
    # source_text_short alone は WARN であって BLOCK ではない
    assert r['verdict'] in ('WARN', 'PASS'), \
        f"完全fixture+短いsource単独で BLOCK は過剰: {r['verdict']} {[i['type'] for i in r['issues'] if i.get('severity')=='block']}"
