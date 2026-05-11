"""
memory: feedback_audit_script_is_not_audit.md
規定: 「scriptが回ったこと=監査が完了したこと ではない。サムネ目視・force factcheck・本文精読は別途独立実行」
"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_stop_hook_exists():
    """Stop hook (audit_completion_check.py) が存在し実行可能"""
    p = '/home/aiuser/kpop-ai-system/.claude/hooks/audit_completion_check.py'
    assert os.path.exists(p), f"Stop hook がない: {p}"
    assert os.access(p, os.X_OK), "Stop hook が実行可能でない"


def test_settings_json_registers_stop_hook():
    """.claude/settings.json で Stop hook が登録されている"""
    import json
    s = json.load(open('/home/aiuser/kpop-ai-system/.claude/settings.json'))
    stops = s.get('hooks', {}).get('Stop', [])
    cmds = []
    for entry in stops:
        for h in entry.get('hooks', []):
            if h.get('type') == 'command':
                cmds.append(h.get('command', ''))
    assert any('audit_completion_check' in c for c in cmds), \
        f"Stop hookに audit_completion_check が登録されていない: {cmds}"


def test_audit_steps_required_4_items():
    """4項目すべて (structure/thumbnail/factcheck/body_read) が必須"""
    from lib.audit_steps_log import REQUIRED_STEPS
    assert set(REQUIRED_STEPS) == {'structure', 'thumbnail', 'factcheck', 'body_read'}, \
        f"REQUIRED_STEPS が4項目セットでない: {REQUIRED_STEPS}"


def test_claude_md_contains_4_step_procedural():
    """CLAUDE.md に4項目procedural が記載されていること"""
    p = '/home/aiuser/kpop-ai-system/CLAUDE.md'
    assert os.path.exists(p)
    text = open(p, encoding='utf-8').read()
    for step in ('structure', 'thumbnail', 'factcheck', 'body_read'):
        assert step in text, f"CLAUDE.md に '{step}' の言及がない"
