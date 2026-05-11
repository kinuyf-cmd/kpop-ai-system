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
BASE_DIR = '/home/aiuser/kpop-ai-system'
WEEKLY_JOB_CONFIG = os.path.join(BASE_DIR, 'config', 'weekly_job_health.json')

# 監視対象のheartbeatファイル一覧
HEARTBEATS = {
    '/home/aiuser/kpop-ai-system/logs/thumb_audit_heartbeat': {
        'name': 'thumbnail_contamination_audit',
        'expected_freq_hours': 24,
        'stale_threshold_hours': 30,
    },
}


def check_weekly_jobs() -> list[dict]:
    """config/weekly_job_health.json を読み、各週次ジョブの出力ファイル古さを判定"""
    if not os.path.exists(WEEKLY_JOB_CONFIG):
        return []
    try:
        cfg = json.load(open(WEEKLY_JOB_CONFIG))
    except Exception as e:
        return [{'name': 'weekly_job_config_load_error', 'status': 'error', 'detail': str(e)}]
    default_max = cfg.get('default_max_age_days', 8)
    results = []
    for job_id, job in cfg.get('jobs', {}).items():
        path = os.path.join(BASE_DIR, job['output_file'])
        max_age = job.get('max_age_days', default_max)
        if not os.path.exists(path):
            results.append({
                'name': f'weekly:{job_id}',
                'status': 'missing',
                'detail': f"{job['output_file']} 未生成 (cron 一度も成功していない可能性) — recovery: {job.get('recovery','')[:80]}",
            })
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        age_days = (datetime.now() - mtime).total_seconds() / 86400
        if age_days > max_age:
            results.append({
                'name': f'weekly:{job_id}',
                'status': 'stale',
                'age_hours': round(age_days * 24, 1),
                'detail': f"{job['output_file']} {age_days:.1f}日経過 (>{max_age}d) — {job.get('description','')[:60]}",
            })
        else:
            results.append({
                'name': f'weekly:{job_id}',
                'status': 'fresh',
                'age_hours': round(age_days * 24, 1),
                'detail': f"{job['output_file']} {age_days:.1f}日前",
            })
    return results


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

    # 週次ジョブの silent rot 検出 (2026-05-11追加, chart pipeline事故対策)
    for r in check_weekly_jobs():
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
