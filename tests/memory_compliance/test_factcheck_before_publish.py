"""
memory: feedback_factcheck_before_publish.md
規定: 「llm_proofreader.proofread_post()を全公開経路に統合。HIGH以上で自動draft化」
"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_llm_proofreader_proofread_post_exists():
    from pipeline import llm_proofreader
    assert hasattr(llm_proofreader, 'proofread_post'), \
        "pipeline.llm_proofreader.proofread_post が存在しない"


def test_pre_publish_gate_runs_factcheck_section():
    """pre_publish_gate に factcheck系のチェック呼び出しが存在すること"""
    from lib import pre_publish_gate
    import inspect
    src = inspect.getsource(pre_publish_gate)
    # _verify_with_tavily か proofread_post か web_factcheck の呼出
    assert any(s in src for s in ('proofread_post', '_verify_with_tavily', 'web_factcheck',
                                    'factcheck')), \
        "pre_publish_gate に factcheck呼出がない"


def test_audit_steps_log_factcheck_step():
    """4項目audit_steps の中に factcheck step が含まれていること"""
    from lib.audit_steps_log import REQUIRED_STEPS
    assert 'factcheck' in REQUIRED_STEPS, \
        f"audit_steps_log REQUIRED_STEPS に factcheck がない: {REQUIRED_STEPS}"
