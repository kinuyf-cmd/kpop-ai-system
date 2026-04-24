#!/usr/bin/env python3
"""
daily_material_audit.py — 毎日10時の素材品質監査
前日公開記事のサムネイル＋本文＋メタデータを総合チェック。
CRITICAL検出時は自動draft化＋Discord通知。
"""
import json
import os
import re
import sys
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from pipeline.pre_publish_hook import check_content_quality

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
YESTERDAY = (NOW - timedelta(days=1)).strftime('%Y-%m-%dT00:00:00')

def load_env():
    env = {}
    with open(BASE / '.env') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k] = v.strip().strip('"').strip("'")
    return env


def notify_discord(message: str):
    script = BASE / "kpop_notify.sh"
    if script.exists():
        try:
            subprocess.run(['bash', str(script), 'warn', 'daily_audit', message],
                           timeout=10, capture_output=True)
        except Exception:
            pass


def main():
    import requests
    env = load_env()
    auth = (env['WP_USER'], env['WP_PASS'])
    wp = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'

    print(f"[{NOW.isoformat()}] Daily Material Audit starting...")
    print(f"  Checking posts published after {YESTERDAY}")

    # Fetch yesterday's posts
    posts = []
    page = 1
    while True:
        r = requests.get(f'{wp}/posts', auth=auth, timeout=30,
                         params={'per_page': 50, 'page': page, 'context': 'edit',
                                 'after': YESTERDAY, 'status': 'publish'})
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        posts.extend(data)
        page += 1

    print(f"  Found {len(posts)} posts to audit")

    if not posts:
        print("  No posts to audit. Done.")
        return

    results = {
        'date': NOW.strftime('%Y-%m-%d'),
        'total': len(posts),
        'pass': 0,
        'critical': 0,
        'critical_posts': [],
        'warning_posts': [],
    }

    for post in posts:
        pid = post['id']
        title = post['title']['raw']
        content = post['content']['raw']

        critical, warnings = check_content_quality(content, title)

        # サムネイルチェック
        mid = post.get('featured_media', 0)
        if mid == 0:
            critical.append('No featured image')
        else:
            # alt textチェック
            try:
                mr = requests.get(f'{wp}/media/{mid}', auth=auth, timeout=10,
                                  params={'_fields': 'id,alt_text'})
                if mr.status_code == 200:
                    alt = mr.json().get('alt_text', '')
                    if not alt or len(alt) < 5:
                        warnings.append(f'Featured image missing alt text (media_id={mid})')
            except Exception:
                pass

        # meta_descriptionチェック
        meta_desc = post.get('meta', {}).get('_aioseo_description', '')
        if not meta_desc or len(meta_desc) < 20:
            warnings.append('Empty or too short meta_description')

        if critical:
            results['critical'] += 1
            results['critical_posts'].append({
                'id': pid, 'title': title[:60],
                'issues': critical[:3]
            })
            # CRITICAL → 自動draft化
            try:
                requests.post(f'{wp}/posts/{pid}', auth=auth, timeout=15,
                              json={'status': 'draft'})
                print(f"  CRITICAL ID={pid} → auto-drafted: {title[:50]}")
            except Exception:
                print(f"  CRITICAL ID={pid} (draft failed): {title[:50]}")
            for c in critical[:3]:
                print(f"    - {c}")
        else:
            results['pass'] += 1
            if warnings:
                results['warning_posts'].append({
                    'id': pid, 'title': title[:60],
                    'warnings': warnings[:3]
                })

    # Save results
    log_path = BASE / 'logs' / 'daily_material_audit.jsonl'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(results, ensure_ascii=False) + '\n')

    # Summary
    print(f"\n  Results: {results['pass']} PASS, {results['critical']} CRITICAL")

    # Discord notification
    if results['critical'] > 0:
        msg = f"📋 Daily Audit {NOW.strftime('%m/%d')}: {results['critical']} CRITICAL / {results['total']} posts\n"
        for cp in results['critical_posts'][:5]:
            msg += f"  ID={cp['id']}: {cp['issues'][0][:50]}\n"
        notify_discord(msg)
        print(f"  Discord notification sent")

    print(f"  Audit complete. Log: {log_path}")


if __name__ == '__main__':
    main()
