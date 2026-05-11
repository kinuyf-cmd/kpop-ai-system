"""
memory: feedback_120_percent_quality.md
規定: 「スピード優先で検証省略は絶対禁止。サムネは目視確認、数字だけでOK判定しない」
proceduralだが、検証機構(audit_steps_log + Stop hook)が存在することは検証可能。
"""
import os, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_audit_steps_log_module_exists():
    from lib import audit_steps_log
    assert hasattr(audit_steps_log, 'record_step')
    assert hasattr(audit_steps_log, 'is_fully_audited')


def test_audit_steps_enforcer_cron_runs():
    """audit_steps_enforcer.py が存在し pipeline 配下にある"""
    p = '/home/aiuser/kpop-ai-system/pipeline/audit_steps_enforcer.py'
    assert os.path.exists(p), f"enforcer not found: {p}"


def test_4_required_audit_steps():
    """構造+サムネ+factcheck+本文精読 4項目セット"""
    from lib.audit_steps_log import REQUIRED_STEPS
    expected = {'structure', 'thumbnail', 'factcheck', 'body_read'}
    assert set(REQUIRED_STEPS) == expected, \
        f"4項目セット違反: {set(REQUIRED_STEPS)} != {expected}"
