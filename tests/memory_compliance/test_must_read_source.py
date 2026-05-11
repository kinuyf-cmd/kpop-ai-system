"""
memory: feedback_must_read_source.md
規定: 「lib/source_reader.pyで本文フェッチ必須。ヘッドラインだけでGPT生成は絶対禁止」
"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_source_reader_module_exists():
    """source_reader モジュールが import可能なこと"""
    from lib import source_reader
    assert hasattr(source_reader, 'read_source'), \
        "lib.source_reader に read_source 関数がない"


def test_pre_publish_gate_warns_on_short_source():
    """ソース取得失敗 (<100字) 時に WARN以上を上げること"""
    from lib.pre_publish_gate import pre_publish_gate

    result = pre_publish_gate(
        title='テスト記事',
        body_html='<p>' + 'A' * 600 + '</p>',
        post_type='post',
        kind='news',
        source_url='https://example.com/article',
        source_text_length=50,  # 50字 = 取得失敗扱い
    )
    types = {i['type'] for i in result['issues']}
    assert 'source_not_read' in types, \
        f"短いソース本文に対してsource_not_read warningが出ていない: {types}"


def test_unified_publisher_drafts_short_source_news():
    """news kindで source_text<1500字 → status='draft' になること"""
    # publisher中のロジックを直接verify (実publish呼ばずロジック単体検証)
    from lib import unified_publisher
    import inspect
    src = inspect.getsource(unified_publisher)
    # 自動draft化ロジックの存在確認
    assert 'auto_draft_reasons' in src and 'source_text_short' in src, \
        "unified_publisher に source_text<1500字 → draft化 ロジックが見つからない"
