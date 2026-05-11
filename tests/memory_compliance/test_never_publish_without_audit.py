"""
memory: feedback_never_publish_without_audit.md
規定: 「publish後にfull_auditでissue=0確認するまで完了報告禁止」
"""
import os, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_audit_steps_log_has_4_required():
    from lib.audit_steps_log import REQUIRED_STEPS
    assert set(REQUIRED_STEPS) == {'structure', 'thumbnail', 'factcheck', 'body_read'}


def test_audit_steps_enforcer_drafts_unaudited():
    """enforcerコードに status='draft' 切替ロジックがあること"""
    import inspect
    from pipeline import audit_steps_enforcer
    src = inspect.getsource(audit_steps_enforcer)
    assert "'status': 'draft'" in src or '"status": "draft"' in src, \
        "enforcer に draft切替ロジックなし"


def test_full_audit_runner_writes_audit_steps():
    """full_audit_runner が record_step を呼ぶこと"""
    import inspect
    from pipeline import full_audit_runner
    src = inspect.getsource(full_audit_runner)
    assert 'record_step' in src and "'structure'" in src
