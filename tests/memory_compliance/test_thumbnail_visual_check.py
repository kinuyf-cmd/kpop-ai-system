"""
memory: feedback_thumbnail_visual_check.md
規定: 「投稿時・監査時の両方で画像をReadで開き記事内容との整合性を毎回確認」
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_audit_steps_thumbnail_step_exists():
    """4項目procedural の中に thumbnail step が必須として記録されること"""
    from lib.audit_steps_log import REQUIRED_STEPS
    assert 'thumbnail' in REQUIRED_STEPS


def test_thumbnail_contamination_audit_records_step():
    """thumbnail_contamination_audit が record_step を呼ぶこと"""
    import inspect
    from pipeline import thumbnail_contamination_audit as tca
    src = inspect.getsource(tca)
    assert 'record_step' in src and "'thumbnail'" in src, \
        "thumbnail_contamination_audit が audit_steps_log.record_step('thumbnail', ...) を呼んでいない"


def test_thumbnail_vision_validator_exists():
    """thumbnail_vision_validator (artist一致確認) が import可能"""
    from lib import thumbnail_vision_validator
    assert hasattr(thumbnail_vision_validator, 'validate_thumbnail')
