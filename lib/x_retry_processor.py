#!/usr/bin/env python3
"""X投稿リトライプロセッサ — config/x_retry_queue.json から1件ずつ消化
cron: 45 * * * * (毎時45分)"""
import sys, os, json, time, pathlib
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

QUEUE_FILE = '/home/aiuser/kpop-ai-system/config/x_retry_queue.json'
LOG_FILE = '/home/aiuser/kpop-ai-system/logs/x_retry.log'

# Patch retry log path to avoid root-owned file issue
sys.path.insert(0, '/home/aiuser/kpop-ai-system/google_metrics')
import post_to_x
post_to_x.RETRY_LOG = pathlib.Path('/home/aiuser/kpop-ai-system/logs/x_retry_log_v2.jsonl')


def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    data = json.load(open(QUEUE_FILE))
    return data.get('queue', [])


def save_queue(queue):
    data = {'created': '2026-04-26', 'reason': 'X CreditsDepleted', 'queue': queue}
    json.dump(data, open(QUEUE_FILE, 'w'), ensure_ascii=False, indent=2)


def main():
    from datetime import datetime
    print(f"=== x_retry_processor {datetime.now().isoformat()} ===")

    queue = load_queue()
    if not queue:
        print("  queue empty")
        return

    print(f"  queue: {len(queue)}件")
    item = queue[0]
    # queue format: {id, title, url} or {pid, type}
    pid = item.get('pid') or item.get('id')
    ptype = item.get('type', 'post')
    title = item.get('title', '')
    url = item.get('url', '')

    if not title or not url:
        # Fetch post info from WP API
        import requests
        endpoint = 'posts' if ptype == 'post' else 'popup'
        try:
            p = requests.get(f'https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{pid}?_fields=id,title,link,meta',
                             timeout=10).json()
        except Exception as e:
            print(f"  fetch err {pid}: {e}")
            return
        title = p['title']['rendered'] if isinstance(p.get('title'), dict) else p.get('title', '')
        url = p.get('link', '')

    if ptype == 'popup':
        emoji = '📌'
        hashtags = '#ポップアップ #KPOP #韓国'
    else:
        emoji = '📰'
        hashtags = '#KPOPJOURNAL #KPOP'

    text = f"{emoji} {title[:80]}\n\n{hashtags}"

    from lib.x_poster import post_tweet
    result = post_tweet(text, url)

    if result.get('success'):
        print(f"  OK pid={pid} tweet_id={result.get('tweet_id')}")
        queue.pop(0)
        save_queue(queue)
        print(f"  remaining: {len(queue)}件")
    else:
        err = result.get('error', '')
        if '402' in err or 'CreditsDepleted' in err:
            print(f"  STILL NO CREDITS — keeping queue ({len(queue)}件)")
        else:
            print(f"  FAIL pid={pid}: {err}")
            # Move to end of queue for retry later
            queue.append(queue.pop(0))
            save_queue(queue)


if __name__ == '__main__':
    main()
