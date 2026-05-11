"""
memory: feedback_artist_photo_absolute_rule.md
規定強化 (2026-05-11): 「source_url がある全記事で og:image 取得を試行する」
これは priority順以前の問題。og:image を *一切試行せず* artist photo に行くのは違反。
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_thumbnail_auto_repair_extracts_source_url():
    """thumbnail_auto_repair が source_url 抽出ロジックを持つこと"""
    from pipeline import thumbnail_auto_repair
    src = inspect.getsource(thumbnail_auto_repair)
    assert '_fetch_source_url_from_post' in src, \
        "thumbnail_auto_repair に source_url 抽出関数なし"


def test_resolve_function_accepts_source_url():
    """thumbnail_source_resolver.resolve() が source_url パラメータを受け付けること"""
    from lib import thumbnail_source_resolver
    sig = inspect.signature(thumbnail_source_resolver.resolve)
    assert 'source_url' in sig.parameters, \
        "resolve() に source_url パラメータなし"


def test_unified_publisher_passes_source_url_to_artist_resolver():
    """unified_publisher が artist fallback時 source_url を resolve() に渡すこと"""
    from lib import unified_publisher
    src = inspect.getsource(unified_publisher)
    # resolve呼出に source_url が含まれること
    assert 'source_url=source_url' in src or 'source_url=source_url or' in src, \
        "unified_publisher の artist resolver呼出に source_url plumbing なし"


def test_priority_order_og_image_first():
    """resolve()内のconcrete分岐で og:image 試行が artist 試行より前にあること"""
    from lib import thumbnail_source_resolver
    src = inspect.getsource(thumbnail_source_resolver.resolve)
    # concrete記事分岐の中での順序を見る
    concrete_start = src.find('if article_type == "concrete"')
    if concrete_start == -1:
        import pytest; pytest.skip('concrete branch not found')
    branch = src[concrete_start:]
    # 実呼出 (関数定義ではない使用)
    og_call_idx = branch.find('resolve_source_og_image(')
    artist_call_idx = branch.find('_resolve_artist_sources(')
    assert og_call_idx > 0 and artist_call_idx > 0, \
        f"概念抽出失敗: og={og_call_idx} artist={artist_call_idx}"
    assert og_call_idx < artist_call_idx, \
        f"og_image呼出 ({og_call_idx}) が artist呼出 ({artist_call_idx}) より後 — priority逆"
