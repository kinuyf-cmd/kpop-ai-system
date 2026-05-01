#!/usr/bin/env python3
"""BUZZLAB詳細記事を全文+画像で取得→WP公開 (A+F方式, オーナー許可済み)"""
import sys
import os
import json
import re
import urllib.request
import base64

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
except Exception:
    pass

from lib.buzzlab_full_scraper import scrape_buzzlab_article, fetch_buzzlab_latest_urls
from lib.wp_image_uploader import replace_external_images_in_html, download_and_upload_to_wp

WP = "https://www.kpopjournal.tokyo"
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

PROCESSED_FILE = '/home/aiuser/kpop-ai-system/data/buzzlab_processed_urls.txt'
LOG_FILE = '/home/aiuser/kpop-ai-system/logs/buzzlab_full_publisher.log'

# --- 動線ボタン (上部バナー + 下部CTA) ---

BUZZLAB_TOP_BANNER = '''<div class="kpj-buzzlab-banner" style="background:linear-gradient(135deg,#FFF0F5 0%,#FFE4E1 100%);padding:16px 20px;margin:24px 0;border-radius:12px;text-align:center;">
<p style="margin:0;"><a href="{url}" target="_blank" rel="noopener" style="display:inline-block;background:#FF1493;color:white;padding:10px 24px;border-radius:24px;text-decoration:none;font-weight:bold;">元記事をBUZZLABで読む →</a></p>
</div>'''

BUZZLAB_BOTTOM_CTA = '''<div class="kpj-buzzlab-cta" style="margin:32px 0;padding:20px;background:#fafafa;border-left:4px solid #FF1493;border-radius:0 8px 8px 0;">
<p style="margin:0 0 12px 0;font-weight:700;color:#FF1493;">ソウル最新ポップアップ情報はBUZZLABをチェック</p>
<p style="margin:0;"><a href="https://kbuzzlab.com" target="_blank" rel="noopener" style="display:inline-block;background:#FF1493;color:white;padding:8px 20px;border-radius:20px;text-decoration:none;font-size:14px;">BUZZLAB トップページへ →</a></p>
</div>'''

POPUP_HUB_CTA = '''<div class="kpj-popup-hub-cta" style="margin:30px 0 20px;padding:16px 20px;background:linear-gradient(135deg,#fff0f3,#f8f0ff);border-radius:12px;text-align:center;border:1px solid #ffd6e0;">
<p style="margin:0;font-size:1.05em;font-weight:700;"><a href="https://www.kpopjournal.tokyo/popup/" style="color:#FF1B6B;text-decoration:none;">\u2728 開催中の全ポップアップ情報はこちら \u2728</a></p></div>'''


def load_processed():
    try:
        return set(open(PROCESSED_FILE).read().strip().split('\n'))
    except FileNotFoundError:
        return set()


def mark_processed(url):
    with open(PROCESSED_FILE, 'a') as f:
        f.write(url + '\n')


def detect_city(title, body):
    """都市判定"""
    text = (title + ' ' + body).upper()
    kws = {
        'tokyo': ['東京', '渋谷', '原宿', '表参道', '新宿', '銀座', '六本木', '池袋'],
        'osaka': ['大阪', '梅田', '心斎橋', '難波'],
        'nagoya': ['名古屋', '栄'],
        'fukuoka': ['福岡', '博多', '天神'],
        'seoul-gangnam': ['江南', '新沙', '狎鴎亭', '蚕室', 'GANGNAM', '강남'],
        'seoul-seongsu': ['聖水', 'SEONGSU', '성수'],
        'seoul-hongdae': ['弘大', '新村', '合井', 'HONGDAE', '홍대'],
        'seoul-myeongdong': ['明洞', '東大門', '龍山', '汝矣島', 'MYEONGDONG', '명동'],
    }
    for city_id, words in kws.items():
        for w in words:
            if w.upper() in text:
                return city_id
    return ''


def publish_to_wp(article):
    """BUZZLAB記事をWPに公開"""
    title = article['title'][:80]
    url = article['url']

    # 画像をWPに保存して本文内URL置換
    new_body, saved_urls = replace_external_images_in_html(
        article['body_html'], 'kbuzzlab', title
    )
    images_saved = len(saved_urls)

    # featured画像 (OG画像優先)
    featured_id = 0
    if article.get('images'):
        result = download_and_upload_to_wp(article['images'][0], title)
        if result:
            featured_id = result.get('media_id', 0)
            # alt text設定
            if featured_id:
                try:
                    alt_body = json.dumps({'alt_text': title}).encode()
                    req = urllib.request.Request(
                        f"{WP}/wp-json/wp/v2/media/{featured_id}",
                        data=alt_body, method='POST',
                        headers={'Authorization': f'Basic {AUTH}',
                                 'Content-Type': 'application/json'})
                    urllib.request.urlopen(req, timeout=15)
                except Exception:
                    pass

    # Markdownコードブロックマーカー除去
    new_body = re.sub(r'```\w*\s*\n?', '', new_body)
    new_body = re.sub(r'```\s*\n?', '', new_body)

    # 本文構築: 上部バナー + 本文 + ポップアップ一覧CTA + 下部CTA
    full_content = (
        BUZZLAB_TOP_BANNER.format(url=url) + '\n'
        + new_body + '\n'
        + POPUP_HUB_CTA + '\n'
        + BUZZLAB_BOTTOM_CTA.format(url=url)
    )

    city = detect_city(title, article['body_html'])
    info = article.get('info', {})

    meta = {
        '_popup_city': city,
        '_popup_official_url': url,
        '_popup_status': 'ongoing',
        '_buzzlab_source': 'true',
    }
    if article.get('start_date'):
        meta['_popup_start_date'] = article['start_date']
    if article.get('end_date'):
        meta['_popup_end_date'] = article['end_date']
    # 営業時間 (絵文字除去)
    hours = re.sub(r'[^\d:~〜\-\s]', '', info.get('営業時間', '')).strip()
    if hours:
        meta['_popup_hours'] = hours
    # 住所 (絵文字除去)
    address = re.sub(r'[📍\U0001f4cd]', '', info.get('住所', '')).strip()
    if address:
        meta['_popup_address'] = address

    payload = {
        'title': title,
        'content': full_content,
        'status': 'publish',
        'meta': meta,
    }
    if featured_id:
        payload['featured_media'] = featured_id

    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            f"{WP}/wp-json/wp/v2/popup",
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}',
                     'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        post_id = r.get('id')
        return post_id, featured_id, images_saved
    except Exception as e:
        print(f"  WP post err: {e}")
        return None, 0, 0


def main(max_articles=10):
    ts = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
    print(f"=== BUZZLAB A+F publisher: {ts} ===")

    processed = load_processed()
    urls = fetch_buzzlab_latest_urls(limit=30)
    print(f"BUZZLAB候補URL: {len(urls)}件")

    new_urls = [u for u in urls if u not in processed]
    print(f"未処理: {len(new_urls)}件")

    published = 0
    total_images = 0
    total_featured = 0

    for url in new_urls[:max_articles]:
        print(f"\n処理中: {url[:70]}")
        article = scrape_buzzlab_article(url)
        if not article:
            print("  スクレイプ失敗")
            mark_processed(url)
            continue
        if not article.get('title') or len(article.get('body_html', '')) < 200:
            print(f"  内容不足 (title={bool(article.get('title'))}, "
                  f"body={len(article.get('body_html', ''))}字), スキップ")
            mark_processed(url)
            continue

        post_id, feat_id, img_count = publish_to_wp(article)
        if post_id:
            print(f"  post_id={post_id} featured={feat_id} images={img_count}")
            published += 1
            total_images += img_count
            if feat_id:
                total_featured += 1
        else:
            print("  WP公開失敗")
        mark_processed(url)

    print(f"\n=== 公開: {published}件 / featured: {total_featured} / "
          f"画像保存: {total_images}枚 ===")


if __name__ == '__main__':
    main(max_articles=10)
