"""
memory: feedback_gsc_indexing_quota_mgmt.md
規定: 「200/日上限、URL重複禁止、429観測時は当日全停止」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_gsc_indexing_module_exists():
    """gsc_indexing モジュール存在"""
    from lib import gsc_indexing
    src = inspect.getsource(gsc_indexing)
    # 200日次上限の定数 or 言及
    assert '200' in src or 'DAILY_LIMIT' in src or 'quota' in src.lower(), \
        "200/日上限の言及がない"


def test_gsc_429_handling():
    """429 status code への対応コードあり"""
    from lib import gsc_indexing
    src = inspect.getsource(gsc_indexing)
    assert '429' in src or 'RateLimited' in src, \
        "429 rate limit handling なし"
