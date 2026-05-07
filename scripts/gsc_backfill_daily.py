#!/usr/bin/env python3
"""
GSCインデックス未送信記事の日次バックフィル

audit_state.jsonl から no_gsc_indexing の記事を抽出し、
quota上限(180件/日)まで送信する。

cron: 毎日7:00に実行 (gsc_index_trackerの後)
"""
import sys, json, time
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

from lib.gsc_indexing import notify_url_updated, get_access_token, get_quota_remaining

BASE = Path('/home/aiuser/kpop-ai-system')
AUDIT_STATE = BASE / 'data' / 'audit_state.jsonl'
GSC_LOG = BASE / 'data' / 'gsc_indexing_log.jsonl'
JST = timezone(timedelta(hours=9))


def get_already_sent_urls():
    """gsc_indexing_log.jsonl から送信済みURLを取得"""
    urls = set()
    if GSC_LOG.exists():
        for line in GSC_LOG.read_text(errors='replace').splitlines():
            try:
                d = json.loads(line)
                if d.get('status') in ('ok', 'fallback_ok'):
                    urls.add(d.get('url', '').rstrip('/'))
            except:
                pass
    return urls


def get_missing_urls():
    """audit_state.jsonl から no_gsc_indexing の記事URLを取得"""
    import urllib.request, base64, os
    WP_USER = os.getenv('WP_USER', '')
    WP_PASS = os.getenv('WP_PASS', '')
    AUTH = base64.b64encode(f'{WP_USER}:{WP_PASS}'.encode()).decode()

    # 最新audit stateからno_gsc_indexingの記事IDを取得
    latest = {}
    with open(AUDIT_STATE, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                latest[d['post_id']] = d
            except:
                pass

    missing_ids = [pid for pid, rec in latest.items()
                   if any(i['type'] == 'no_gsc_indexing' for i in rec.get('issues', []))]

    # 全公開記事のURLマップ取得
    url_map = {}
    page = 1
    while True:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?status=publish&per_page=100&page={page}&_fields=id,link'
        try:
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
            for p in posts:
                url_map[p['id']] = p.get('link', '')
            if len(posts) < 100:
                break
            page += 1
        except:
            break

    return [(pid, url_map.get(pid, '')) for pid in missing_ids if url_map.get(pid)]


def main():
    now = datetime.now(JST)
    print(f"=== GSCバックフィル {now.strftime('%Y-%m-%d %H:%M')} ===")

    quota = get_quota_remaining()
    print(f"  残りquota: {quota}")

    if quota <= 10:
        print("  quota不足、スキップ")
        return

    already_sent = get_already_sent_urls()
    missing = get_missing_urls()

    # 送信済みを除外
    to_send = [(pid, url) for pid, url in missing if url.rstrip('/') not in already_sent]
    print(f"  未送信: {len(to_send)}件 (quota: {quota})")

    if not to_send:
        print("  送信対象なし")
        return

    token = get_access_token()
    if not token:
        print("  GSC認証失敗")
        return

    sent = 0
    for pid, url in to_send[:quota]:
        result = notify_url_updated(url, token)
        status = result.get('status', 'error')
        if status in ('ok', 'fallback_ok'):
            sent += 1
        elif status == 'quota_exceeded':
            print(f"  quota到達、中断")
            break
        else:
            print(f"  [WARN] id={pid} {status}")
        time.sleep(1)
        if sent % 30 == 0 and sent > 0:
            print(f"  ... {sent}件送信済み")

    print(f"  完了: {sent}/{len(to_send)}件送信")


if __name__ == '__main__':
    main()
