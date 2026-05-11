"""
memory: feedback_recurrence_prevention.md
規定: 「設定JSON化+共通lib化+学習対象拡張+error_patterns.json登録の4層で必ず封じる」
"""
import json, os, sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_error_patterns_json_loadable():
    p = '/home/aiuser/kpop-ai-system/config/error_patterns.json'
    d = json.load(open(p, encoding='utf-8'))
    assert 'patterns' in d


def test_error_patterns_has_recent_entries():
    """直近 patterns 登録されていることを確認 (memory更新が反映されている指標)"""
    p = '/home/aiuser/kpop-ai-system/config/error_patterns.json'
    d = json.load(open(p, encoding='utf-8'))
    assert len(d['patterns']) > 50, f"error_patterns 件数少: {len(d['patterns'])}"


def test_audit_engine_format_mismatch_pattern_recorded():
    """2026-05-10で発見した取り込みバグがerror_patternsに登録されていること"""
    p = '/home/aiuser/kpop-ai-system/config/error_patterns.json'
    d = json.load(open(p, encoding='utf-8'))
    assert 'audit_engine_format_mismatch' in d['patterns']


def test_thumbnail_priority_inverted_recorded():
    """2026-05-11で発見したサムネpriority逆転がerror_patternsに登録"""
    p = '/home/aiuser/kpop-ai-system/config/error_patterns.json'
    d = json.load(open(p, encoding='utf-8'))
    assert 'thumbnail_priority_inverted' in d['patterns']
