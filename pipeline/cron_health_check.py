#!/usr/bin/env python3
"""Cron silent failure 検知 (2026-05-10)

各種重要cronのheartbeatファイルが古くなっていないか監視。
独立cronで実行することで、対象cronが silent failure しても気づける。

Cron: 0 8 * * * (毎日8時JST、対象cronより前)
"""
import os
import sys
import json
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '')

# 監視対象のheartbeatファイル一覧
HEARTBEATS = {
    '/home/aiuser/kpop-ai-system/logs/thumb_audit_heartbeat': {
        'name': 'thumbnail_contamination_audit',
        'expected_freq_hours': 24,
        'stale_threshold_hours': 30,
    },
}


def check_heartbeat(path: str, cfg: dict) -> dict:
    if not os.path.exists(path):
        return {'name': cfg['name'], 'status': 'missing', 'detail': 'heartbeat file not found'}
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        age_hours = (datetime.now() - mtime).total_seconds() / 3600
        threshold = cfg.get('stale_threshold_hours', 30)
        return {
            'name': cfg['name'],
            'status': 'stale' if age_hours > threshold else 'fresh',
            'age_hours': round(age_hours, 1),
            'detail': f'last beat: {mtime.isoformat()}',
        }
    except Exception as e:
        return {'name': cfg['name'], 'status': 'error', 'detail': str(e)}


def post_discord(message: str):
    if not DISCORD_WEBHOOK: return
    try:
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=json.dumps({'content': message}).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def main():
    failures = []
    for path, cfg in HEARTBEATS.items():
        r = check_heartbeat(path, cfg)
        print(f"  [{r['name']}] {r['status']} {r.get('age_hours', '?')}h - {r['detail']}")
        if r['status'] in ('stale', 'missing', 'error'):
            failures.append(r)
    if failures:
        msg_lines = [f"⚠️ Cron health alert ({len(failures)}件)"]
        for f in failures:
            msg_lines.append(f"- {f['name']}: {f['status']} ({f.get('age_hours','?')}h) {f['detail'][:80]}")
        post_discord('\n'.join(msg_lines))
    else:
        print('[cron-health] all heartbeats fresh')
    return len(failures)


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
