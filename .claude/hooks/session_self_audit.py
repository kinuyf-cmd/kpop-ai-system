#!/usr/bin/env python3
"""Stop hook: session終了時のセルフ監査記録 (2026-05-11新設)

監査完了主張時には audit_completion_check.py が走る。
このhookは「completion主張の有無を問わず」セッション情報を集計し
logs/session_audit.jsonl に記録する。

記録項目:
  - session_id, end_ts
  - audit_steps mtime (最終audit step記録時刻)
  - memory_compliance test summary
  - 直近 user message 数
  - 直近 assistant tool calls 種別

これによりユーザーは週次で「私の行動の質」を機械的に評価できる。
"""
import json, sys, os, subprocess, time
from datetime import datetime, timezone


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get('stop_hook_active'):
        sys.exit(0)

    transcript_path = data.get('transcript_path', '')
    session_id = data.get('session_id', '')
    now = datetime.now(timezone.utc)

    record = {
        'session_id': session_id,
        'end_ts': now.isoformat(),
        'audit_steps_mtime': None,
        'user_msg_count': 0,
        'assistant_tool_uses': {},
    }

    log_path = '/home/aiuser/kpop-ai-system/logs/audit_steps.jsonl'
    if os.path.exists(log_path):
        record['audit_steps_mtime'] = os.path.getmtime(log_path)
        record['audit_steps_age_min'] = round((time.time() - record['audit_steps_mtime']) / 60, 1)

    try:
        r = subprocess.run(
            ['python3', '-m', 'pytest', 'tests/memory_compliance/',
             '--collect-only', '-q'],
            cwd='/home/aiuser/kpop-ai-system', capture_output=True, text=True, timeout=15
        )
        import re
        m = re.search(r'(\d+)\s+tests?\s+collected', r.stdout)
        if m:
            record['memory_test_total'] = int(m.group(1))
    except Exception:
        pass

    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, encoding='utf-8') as f:
                lines = f.readlines()[-200:]
            for line in lines:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('type') == 'user':
                    record['user_msg_count'] += 1
                elif rec.get('type') == 'assistant':
                    msg = rec.get('message', {})
                    if isinstance(msg, dict):
                        for c in (msg.get('content') or []):
                            if isinstance(c, dict) and c.get('type') == 'tool_use':
                                t = c.get('name', '')
                                record['assistant_tool_uses'][t] = \
                                    record['assistant_tool_uses'].get(t, 0) + 1
        except Exception:
            pass

    out_path = '/home/aiuser/kpop-ai-system/logs/session_audit.jsonl'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        with open(out_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass

    sys.exit(0)


if __name__ == '__main__':
    main()
