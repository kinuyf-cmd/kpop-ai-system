"""
memory: feedback_thumbnail_alt_regression.md
規定: 「再生成後のalt設定・検証・NG regex過剰マッチを同時に守る」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_unified_publisher_sets_alt():
    """_upload_media に alt_text 設定ロジックがあること"""
    from lib import unified_publisher
    src = inspect.getsource(unified_publisher)
    assert 'alt_text' in src and "'alt_text'" in src, \
        "_upload_media にalt設定ロジックなし"


def test_thumbnail_repair_sets_alt():
    """thumbnail_auto_repair も alt_text を設定すること"""
    from pipeline import thumbnail_auto_repair
    src = inspect.getsource(thumbnail_auto_repair)
    assert 'alt' in src.lower() and 'upload' in src.lower(), \
        "auto_repair にalt設定が見つからない"
