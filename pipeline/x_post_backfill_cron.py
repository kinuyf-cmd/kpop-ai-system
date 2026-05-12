#!/usr/bin/env python3
"""publish済みでX未投稿の記事を自動enqueue (2026-05-11新設)

cron想定 (15分間隔):
  */15 * * * * cd /home/aiuser/kpop-ai-system && python3 pipeline/x_post_backfill_cron.py >> logs/x_post_backfill_cron.log 2>&1

動作:
  1. 直近6h以内に publishされた記事を取得
  2. 各記事のX投稿状況を確認 (logs/x_posts.jsonl)
  3. 未投稿 + queue未登録 → enqueue
  4. publish直後の grace 15分は除外 (publish_hookの enqueue を待つ)

memory feedback_audit_depth: 「件数だけで監査済と報告しない」を遵守、本文照合まで実施。
2026-05-10 で19730/19477がX未投稿で放置された事故の再発防止。
"""
import sys, os, json, subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.full_audit_engine import get_x_post_summary
from pipeline.x_scheduled_poster import enqueue, load_queue

WP_BASE = 'https://www.kpopjournal.tokyo'
WP_AUTH = '/home/aiuser/.wp_auth'

GRACE_MINUTES = 15  # publish直後はpublish_hook待ち
LOOKBACK_HOURS = 6
BEGINNER_HUB_CATS = (112, 113)  # X投稿対象外 (memory project_beginner_hub_articles)


def wp_get(path):
    return json.loads(subprocess.check_output(
        ['curl', '-sf', f'{WP_BASE}{path}', '-K', WP_AUTH], timeout=30
    ).decode())


def main():
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=LOOKBACK_HOURS)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = wp_get(f'/wp-json/wp/v2/posts?status=publish&after={cutoff}&per_page=50&_fields=id,title,date_gmt,slug,link,categories')
    print(f"[{now.isoformat()}] X未投稿check 対象publish記事 {len(posts)}件 (直近{LOOKBACK_HOURS}h)")

    grace_cutoff = now - timedelta(minutes=GRACE_MINUTES)
    queue = load_queue()
    queue_urls = {e.get('url', '') for e in queue}

    enqueued = 0
    skipped_in_grace = 0
    posted = 0
    skipped_hub = 0
    enqueued_ids = []

    for p in posts:
        pid = p['id']
        title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
        slug = p.get('slug', '')
        link = p.get('link', '')
        cats = p.get('categories', []) or []

        # ビギナーHUB記事はX対象外
        if any(c in BEGINNER_HUB_CATS for c in cats):
            skipped_hub += 1
            continue

        # publish後 grace check
        try:
            pub_dt = datetime.fromisoformat(p['date_gmt'].replace('Z', '+00:00'))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if pub_dt > grace_cutoff:
            skipped_in_grace += 1
            continue

        # 既存X投稿確認
        x_info = get_x_post_summary(pid, post_slug=slug, post_url=link)
        if x_info.get('posted'):
            posted += 1
            continue

        # queue既存check
        if link in queue_urls:
            continue

        # 未投稿 + queue未登録 → enqueue
        ok = enqueue(
            title=title,
            url=link,
            post_id=pid,
            genre='news',
            artist='',
            priority='normal',
        )
        if ok:
            enqueued += 1
            enqueued_ids.append({'id': pid, 'title': title[:50], 'url': link})
            print(f"  ENQUEUE: id={pid} {title[:40]}")

    print(f"--- summary ---")
    print(f"  in_grace(skip): {skipped_in_grace}")
    print(f"  hub_skip: {skipped_hub}")
    print(f"  already_posted: {posted}")
    print(f"  newly_enqueued: {enqueued}")
    if enqueued_ids:
        evid_dir = '/home/aiuser/kpop-ai-system/logs/x_post_backfill'
        os.makedirs(evid_dir, exist_ok=True)
        evid_path = os.path.join(evid_dir, f"{now.strftime('%Y%m%d_%H%M')}.json")
        with open(evid_path, 'w', encoding='utf-8') as f:
            json.dump({'ts': now.isoformat(), 'enqueued': enqueued_ids}, f, ensure_ascii=False, indent=2)
        print(f"  evidence: {evid_path}")


if __name__ == '__main__':
    main()
