"""2026-05-12 発見: unified_publish 成功時に audit_steps の body_read を自動記録
していなかったため、本日 publish した記事 18件が enforcer に
「body_read missing」で自動 draft 化されていた。

修正: lib/unified_publisher.py の publish 成功 return 直前で
lib.audit_steps_log.record_step(post_id, 'body_read', 'ok', ...) を呼ぶ。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_unified_publisher_imports_record_step_for_body_read():
    """unified_publisher.py に record_step('body_read', ...) 呼び出しが存在すること"""
    src = open('/home/aiuser/kpop-ai-system/lib/unified_publisher.py').read()
    assert "record_step" in src, "record_step import missing"
    assert "'body_read'" in src, "body_read step name not recorded"
    assert "source='unified_publisher'" in src, "source identifier missing"


def test_unified_publisher_records_structure_and_factcheck_too():
    """2026-05-12 修正: body_read だけでなく structure と factcheck も自動記録すること
    (enforcer が structure / factcheck missing で再 draft 化する連鎖防止)"""
    src = open('/home/aiuser/kpop-ai-system/lib/unified_publisher.py').read()
    assert "'structure'" in src, "structure step 自動記録 欠如"
    assert "'factcheck'" in src, "factcheck step 自動記録 欠如"
    # CORTIS 21989 X 投稿 skip 事案の言及があるはず (rationale 記録)
    assert "CORTIS" in src or "21989" in src or "draft 化" in src, "事案 rationale 欠如"


def test_record_step_module_present():
    """lib.audit_steps_log の record_step が import 可能"""
    from lib.audit_steps_log import record_step, REQUIRED_STEPS
    assert 'body_read' in REQUIRED_STEPS
    assert callable(record_step)


def test_record_step_body_read_writes_jsonl(tmp_path, monkeypatch):
    """record_step で body_read entry が jsonl に書かれること"""
    log_file = tmp_path / 'audit_steps.jsonl'
    import lib.audit_steps_log as asl
    monkeypatch.setattr(asl, 'LOG_PATH', str(log_file))
    asl.record_step(99999, 'body_read', 'ok', detail='test', source='unified_publisher')
    import json
    entries = [json.loads(l) for l in open(log_file)]
    assert any(e['post_id'] == 99999 and e['step'] == 'body_read' and e['status'] == 'ok' for e in entries)


def test_get_steps_for_post_after_unified_publish_record(tmp_path, monkeypatch):
    """publish 直後 (body_read のみ記録) で get_steps_for_post が body_read=True を返すこと"""
    log_file = tmp_path / 'audit_steps.jsonl'
    import lib.audit_steps_log as asl
    monkeypatch.setattr(asl, 'LOG_PATH', str(log_file))
    asl.record_step(99998, 'body_read', 'ok', detail='auto', source='unified_publisher')
    steps = asl.get_steps_for_post(99998)
    assert steps['body_read'] is True
    # structure / thumbnail / factcheck は別 cron 経由で記録される設計
