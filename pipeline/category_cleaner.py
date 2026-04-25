#!/usr/bin/env python3
"""カテゴリ誤付与の一括修正 (event汚染を中心に)"""
import os, json, urllib.request, base64, re
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

# カテゴリ判定キーワード
CATEGORY_KEYWORDS = {
    'event': ['コンサート', 'ライブ', 'ファンミーティング', 'ファンミ', 'ツアー', '公演', '握手会',
              'WORLD TOUR', 'CONCERT', 'FAN MEETING', 'チケット', '開催'],
    'beauty': ['メイク', 'コスメ', 'カラコン', 'スキンケア', '化粧', 'ベースメイク', 'リップ',
               'PDRN', 'CICA', '美肌', '美容'],
    'style': ['ファッション', 'コーデ', 'コーディネート', '私服', '空港ファッション'],
    'korea-travel': ['韓国旅行', 'ソウル', '釜山', '聖地巡礼', '韓国観光', 'インチョン空港',
                     '韓国カフェ', '韓国グルメ'],
    'kdrama-movie': ['ドラマ', '映画', 'バラエティ', 'Netflix', '視聴率', '主演'],
    'oshikatsu': ['推し活', 'ペンライト', '応援', '韓国語', 'ハングル', '歌詞', 'ファンチャント',
                  'グッズ', 'トレカ'],
}


def detect_correct_category(title, content):
    text = (title + ' ' + content).lower()
    plain = re.sub(r'<[^>]+>', '', text)
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        score = sum(plain.count(kw.lower()) for kw in kws)
        if score > 0:
            scores[cat] = score
    if not scores:
        return 'news'
    return max(scores, key=scores.get)


def get_categories_map():
    cats = {}
    for page in range(1, 5):
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?per_page=100&page={page}"
        try:
            data = json.loads(urllib.request.urlopen(url, timeout=20).read())
            if not data:
                break
            for c in data:
                cats[c['slug']] = c['id']
        except:
            break
    return cats


def get_posts_in_category(category_id):
    posts = []
    page = 1
    while True:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?categories={category_id}&per_page=100&page={page}&_fields=id,title,content,categories&context=edit"
        try:
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            if not data:
                break
            posts.extend(data)
            if len(data) < 100:
                break
            page += 1
        except:
            break
    return posts


def update_post_categories(post_id, category_ids):
    body = json.dumps({'categories': category_ids}).encode()
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}",
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as e:
        print(f"  更新err: {e}")
        return False


def main():
    cats_map = get_categories_map()
    event_id = cats_map.get('event')
    if not event_id:
        print("eventカテゴリが見つからない")
        return

    posts = get_posts_in_category(event_id)
    print(f"event内の記事: {len(posts)}件")

    fixed = 0
    for post in posts:
        pid = post['id']
        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        content = post.get('content', {}).get('raw') or post.get('content', {}).get('rendered', '')
        current_cats = post.get('categories', [])

        correct_slug = detect_correct_category(title, content)
        correct_id = cats_map.get(correct_slug)

        if correct_slug == 'event' or not correct_id:
            continue

        new_cats = [c for c in current_cats if c != event_id]
        if correct_id not in new_cats:
            new_cats.append(correct_id)
        if not new_cats and 'news' in cats_map:
            new_cats = [cats_map['news']]

        print(f"  post_id={pid} {title[:40]} → event外す+{correct_slug}追加")
        if update_post_categories(pid, new_cats):
            fixed += 1

    print(f"\n{fixed}件 カテゴリ修正完了")


if __name__ == '__main__':
    main()
