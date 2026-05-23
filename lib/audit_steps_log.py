#!/usr/bin/env python3
"""4項目監査ログ統合モジュール (2026-05-10追加)

memory「監査は4項目セット必須」procedural化のためのログ仕組み。
publish後に4項目それぞれのentryが logs/audit_steps.jsonl に記録される。
30分以内に4項目揃わない記事は cron で自動 draft 戻し。

4項目:
  - structure  : full_audit_engine の構造チェック
  - thumbnail  : サムネ画像目視確認 (Read or thumbnail_vision_validator pass)
  - factcheck  : llm_proofreader 実行
  - body_read  : 本文精読 (BeautifulSoup parse + entity check)
"""
import os, json, time
from datetime import datetime, timezone

LOG_PATH = '/home/aiuser/kpop-ai-system/logs/audit_steps.jsonl'
REQUIRED_STEPS = ('structure', 'thumbnail', 'factcheck', 'body_read')


def record_step(post_id: int, step: str, status: str = 'ok',
                detail: str = '', source: str = ''):
    """1項目分の監査entry記録

    Args:
        post_id: WP post ID
        step: 'structure'|'thumbnail'|'factcheck'|'body_read'
        status: 'ok'|'warn'|'error'
        detail: optional detail string
        source: 実行主体識別 (e.g., 'full_audit_runner', 'manual', 'cron')
    """
    if step not in REQUIRED_STEPS:
        raise ValueError(f"step must be one of {REQUIRED_STEPS}, got {step}")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        'post_id': int(post_id),
        'step': step,
        'status': status,
        'detail': detail[:300],
        'source': source,
        'ts': datetime.now(timezone.utc).isoformat(),
    }
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def get_steps_for_post(post_id: int, since_ts: float = 0) -> dict:
    """指定postの4項目audit entry を集計

    Returns: {'structure': True/False, 'thumbnail': ..., 'factcheck': ..., 'body_read': ...}
    """
    result = {step: False for step in REQUIRED_STEPS}
    if not os.path.exists(LOG_PATH):
        return result
    with open(LOG_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get('post_id') != int(post_id):
                continue
            try:
                ts = datetime.fromisoformat(e['ts']).timestamp()
            except Exception:
                continue
            if ts < since_ts:
                continue
            step = e.get('step')
            if step in result and e.get('status') in ('ok', 'warn'):
                result[step] = True
    return result


def is_fully_audited(post_id: int, since_ts: float = 0) -> bool:
    """4項目すべてが ok または warn で記録されているか"""
    steps = get_steps_for_post(post_id, since_ts)
    return all(steps.values())


def missing_steps(post_id: int, since_ts: float = 0) -> list:
    """揃っていないstep名を返す"""
    steps = get_steps_for_post(post_id, since_ts)
    return [s for s, ok in steps.items() if not ok]
