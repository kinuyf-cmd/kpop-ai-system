"""
2026-05-14: draft_auto_publisher が直近 audit_steps.thumbnail=fail の記事を
auto-republish しないことの機械検証。

事故: 23132 (ALL DAY RELIEF 薬 CM 画像、BTS V とは無関係) が auto-auditor で
thumbnail VISION_MISMATCH を出されて手動 draft 化 → draft_auto_publisher が
pre_publish_gate (vision check 含まず) で PASS と判定して再 publish。
"""
import json
import sys

import pytest

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_latest_audit_thumbnail_fail_returns_true_when_fail(tmp_path, monkeypatch):
    from pipeline import draft_auto_publisher as dap
    log = tmp_path / 'audit_steps.jsonl'
    log.write_text(
        '\n'.join([
            json.dumps({'post_id': 99001, 'step': 'thumbnail', 'status': 'ok', 'detail': 'old'}),
            json.dumps({'post_id': 99001, 'step': 'thumbnail', 'status': 'fail', 'detail': 'VISION_MISMATCH'}),
            json.dumps({'post_id': 99002, 'step': 'thumbnail', 'status': 'ok', 'detail': 'clean'}),
        ]) + '\n',
        encoding='utf-8'
    )
    monkeypatch.setattr(dap, 'AUDIT_STEPS_LOG', log)
    is_fail, detail = dap._latest_audit_thumbnail_fail(99001)
    assert is_fail is True
    assert 'VISION_MISMATCH' in detail

    is_fail, detail = dap._latest_audit_thumbnail_fail(99002)
    assert is_fail is False


def test_latest_audit_thumbnail_fail_uses_latest_entry(tmp_path, monkeypatch):
    """新しい thumbnail=ok が後から書かれた場合は fail 判定にならない"""
    from pipeline import draft_auto_publisher as dap
    log = tmp_path / 'audit_steps.jsonl'
    log.write_text(
        '\n'.join([
            json.dumps({'post_id': 99003, 'step': 'thumbnail', 'status': 'fail', 'detail': 'old_fail'}),
            json.dumps({'post_id': 99003, 'step': 'thumbnail', 'status': 'ok', 'detail': 'fixed_now'}),
        ]) + '\n',
        encoding='utf-8'
    )
    monkeypatch.setattr(dap, 'AUDIT_STEPS_LOG', log)
    is_fail, _ = dap._latest_audit_thumbnail_fail(99003)
    assert is_fail is False, '最新が ok なのに fail 判定された'


def test_latest_audit_thumbnail_fail_ignores_other_steps(tmp_path, monkeypatch):
    """factcheck=fail があっても thumbnail には無関係"""
    from pipeline import draft_auto_publisher as dap
    log = tmp_path / 'audit_steps.jsonl'
    log.write_text(
        '\n'.join([
            json.dumps({'post_id': 99004, 'step': 'factcheck', 'status': 'fail', 'detail': 'critical'}),
            json.dumps({'post_id': 99004, 'step': 'thumbnail', 'status': 'ok', 'detail': 'clean'}),
        ]) + '\n',
        encoding='utf-8'
    )
    monkeypatch.setattr(dap, 'AUDIT_STEPS_LOG', log)
    is_fail, _ = dap._latest_audit_thumbnail_fail(99004)
    assert is_fail is False


def test_latest_audit_thumbnail_fail_missing_file(tmp_path, monkeypatch):
    from pipeline import draft_auto_publisher as dap
    monkeypatch.setattr(dap, 'AUDIT_STEPS_LOG', tmp_path / 'nonexistent.jsonl')
    is_fail, detail = dap._latest_audit_thumbnail_fail(99005)
    assert is_fail is False
    assert detail == ''


def test_skip_logic_present_in_main_loop():
    """main loop 内に thumbnail=fail skip 分岐が組み込まれていること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/draft_auto_publisher.py',
               encoding='utf-8').read()
    assert '_latest_audit_thumbnail_fail' in src
    assert "SKIP: audit_steps.thumbnail=fail" in src
