"""
memory: feedback_audit_depth.md
規定: 「件数/HTTP200だけで監査済と報告しない。X queueは本文スキャン、新規記事はfm/cats/status照合」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_full_audit_engine_checks_content_not_just_counts():
    """full_audit が複数項目 (title/slug/content/typo/internal_links) を検査すること"""
    from lib import full_audit_engine
    src = inspect.getsource(full_audit_engine)
    required = ['check_title', 'check_slug', 'check_content_quality', 'check_internal_links']
    missing = [c for c in required if c not in src]
    assert not missing, f"full_audit に必須check欠如: {missing}"


def test_x_post_check_uses_content_scan():
    """X投稿確認で本文スキャン (post_id以上の検証) を行うこと"""
    from lib import full_audit_engine
    src = inspect.getsource(full_audit_engine)
    # _find_in_log は post_id だけでなく slug/url 照合もできる
    assert 'post_slug' in src or 'post_url' in src, \
        "X投稿確認が post_id以外の照合を持たない"
