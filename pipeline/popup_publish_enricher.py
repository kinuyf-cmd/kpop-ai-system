#!/usr/bin/env python3
"""popup記事をGSC Indexing通知 + X投稿"""
import sys, os, json, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

CITY_NAMES = {
    'tokyo': '東京', 'osaka': '大阪', 'nagoya': '名古屋', 'fukuoka': '福岡',
    'seoul-gangnam': 'ソウル江南', 'seoul-seongsu': 'ソウル聖水',
    'seoul-hongdae': 'ソウル弘大', 'seoul-myeongdong': 'ソウル明洞',
}


def fetch_recent_popups(hours=6):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?after={cutoff}&per_page=20&_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except:
        return []


def is_in_log(post_id, log_file):
    if not os.path.exists(log_file):
        return False
    with open(log_file, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('post_id') == post_id:
                    return True
            except:
                pass
    return False


def gsc_indexing_notify(post):
    pid = post['id']
    log_file = '/home/aiuser/kpop-ai-system/logs/indexing_api_sends.jsonl'
    if is_in_log(pid, log_file):
        return False

    try:
        from lib.gsc_indexing import notify_url_updated
        city = post.get('meta', {}).get('_popup_city', '')
        url = f"https://www.kpopjournal.tokyo/popup/{city}/{pid}/"
        result = notify_url_updated(url)
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'post_id': pid, 'url': url, 'status': 'submitted',
                'sent_at': datetime.now(timezone(timedelta(hours=9))).isoformat(),
                'post_type': 'popup',
            }, ensure_ascii=False) + '\n')
        print(f"  GSC: post_id={pid}")
        return True
    except Exception as e:
        print(f"  GSC err: {e}")
        return False


def x_post_popup(post):
    pid = post['id']
    log_file = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    if is_in_log(pid, log_file):
        return False

    try:
        from lib.x_poster import post_tweet
        title = post['title']['rendered']
        city_id = post.get('meta', {}).get('_popup_city', '')
        url = f"https://www.kpopjournal.tokyo/popup/{city_id}/{pid}/"

        status = post.get('meta', {}).get('_popup_status', '')
        emoji = '🆕' if status == 'upcoming' else '🎉' if status == 'ongoing' else '📌'
        city_jp = CITY_NAMES.get(city_id, '')

        text = f"{emoji} {title[:60]}\n📍 {city_jp}\n\n{url}\n\n#ポップアップ #KPOP #韓国 #推し活"
        if len(text) > 280:
            text = text[:277] + '...'

        result = post_tweet(text, url)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'post_id': pid, 'text': text[:100],
                'ts': datetime.now().isoformat(),
                'status': 'ok' if result else 'failed',
                'post_type': 'popup',
            }, ensure_ascii=False) + '\n')
        print(f"  X: post_id={pid}")
        return True
    except Exception as e:
        print(f"  X err: {e}")
        return False


def main():
    popups = fetch_recent_popups(hours=6)
    print(f"=== popup配信enricher: {len(popups)}件 ===")

    gsc_done = x_done = 0
    for p in popups:
        if gsc_indexing_notify(p):
            gsc_done += 1
        if x_post_popup(p):
            x_done += 1

    print(f"GSC: {gsc_done}件 / X: {x_done}件")


if __name__ == '__main__':
    main()
