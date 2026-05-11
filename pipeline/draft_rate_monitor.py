#!/usr/bin/env python3
"""draft_rate_monitor.py — 公開試行 vs publish 成功率の silent rot 検出

2026-05-11 事故契機: breaking_articles.jsonl に14件記録されたのに WP publish は
3件のみ (publish率21%)。残11件は gate BLOCK/draft化されていたが誰も気付かなかった。
同種の silent rot を翌朝に Discord 通知する。

判定基準:
  - 直近24h で breaking_articles.jsonl 5件以上 AND publish率<50% → ALERT
  - 直近24h で feature_article_generator 3件以上 AND publish率<50% → ALERT (将来拡張)

cron 推奨: 0 9 * * * (毎朝9時、daily_editor の前)
"""
from __future__ import annotations
import os
import sys
import json
import urllib.request
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = Path('/home/aiuser/kpop-ai-system')
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '')
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''
JST = timezone(timedelta(hours=9))

ALERT_MIN_ATTEMPTS = 5  # この件数未満なら sample 小すぎてアラート出さない
ALERT_PUBLISH_RATIO = 0.5  # 50% 未満の publish 率でアラート


def _fetch_wp_post_status(post_ids: set[int]) -> dict[int, str]:
    """WP API で post_id → status マップを取得 (publish/draft/trash)"""
    if not post_ids or not AUTH:
        return {}
    out = {}
    # API は include で複数 ID 同時取得可
    ids_csv = ','.join(str(i) for i in sorted(post_ids))
    url = (f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts'
           f'?include={ids_csv}&per_page=100&status=publish,draft,future,private,trash'
           f'&_fields=id,status&context=edit')
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
        for p in posts:
            out[p['id']] = p.get('status', 'unknown')
    except Exception as e:
        print(f'  WP API err: {e}')
    return out


def check_breaking_publish_rate(hours: int = 24) -> dict:
    """breaking_articles.jsonl の直近N時間分の publish 率を計算"""
    cutoff = (datetime.now(JST) - timedelta(hours=hours)).isoformat()
    log_path = BASE / 'logs' / 'breaking_articles.jsonl'
    attempts: list[dict] = []
    if not log_path.exists():
        return {'attempts': 0, 'published': 0, 'ratio': 1.0, 'alert': False}
    try:
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = d.get('ts') or d.get('published_at', '')
                    if ts < cutoff:
                        continue
                    if d.get('post_id'):
                        attempts.append(d)
                except Exception:
                    continue
    except Exception as e:
        print(f'  jsonl read err: {e}')

    post_ids = {a['post_id'] for a in attempts}
    statuses = _fetch_wp_post_status(post_ids)
    published_ids = {pid for pid, st in statuses.items() if st == 'publish'}
    not_published = post_ids - published_ids

    ratio = (len(published_ids) / len(post_ids)) if post_ids else 1.0
    alert = (len(attempts) >= ALERT_MIN_ATTEMPTS and ratio < ALERT_PUBLISH_RATIO)

    return {
        'window_hours': hours,
        'attempts': len(attempts),
        'published': len(published_ids),
        'not_published': len(not_published),
        'ratio': round(ratio, 3),
        'alert': alert,
        'not_published_ids': sorted(not_published)[:10],
        'status_breakdown': {st: sum(1 for s in statuses.values() if s == st)
                             for st in set(statuses.values())},
    }


def post_discord(msg: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=json.dumps({'content': msg[:1950]}).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def main():
    r = check_breaking_publish_rate(hours=24)
    print(f"[draft_rate_monitor] breaking 24h: "
          f"attempts={r['attempts']} publish={r['published']} "
          f"ratio={r['ratio']*100:.0f}% alert={r['alert']}")
    print(f"  status_breakdown: {r['status_breakdown']}")
    if r['not_published_ids']:
        print(f"  not-published sample ids: {r['not_published_ids']}")

    out_path = BASE / 'logs' / 'draft_rate_monitor.json'
    out_path.write_text(json.dumps({
        'generated_at': datetime.now(JST).isoformat(),
        'breaking_24h': r,
    }, ensure_ascii=False, indent=2))
    print(f"  report: {out_path}")

    if r['alert']:
        msg = (
            f"⚠️ breaking publish silent rot 検出\n"
            f"直近24h: 試行 {r['attempts']}件 / publish {r['published']}件 "
            f"({r['ratio']*100:.0f}%、しきい値 {ALERT_PUBLISH_RATIO*100:.0f}%未満)\n"
            f"status内訳: {r['status_breakdown']}\n"
            f"draft落ち sample: {r['not_published_ids']}\n"
            f"→ logs/post_publish_hook.jsonl で原因確認"
        )
        print(msg)
        post_discord(msg)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
