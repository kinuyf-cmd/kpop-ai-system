#!/usr/bin/env python3
"""地域別ポップアップまとめページ生成 (毎週火曜10:00 cron)"""
import sys
import os
import json
import urllib.request
import base64

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
except Exception:
    pass

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

REGIONS = {
    'tokyo': {
        'name': '東京',
        'keywords': ['東京', '原宿', '渋谷', '表参道', '新宿', '池袋', '銀座',
                     '六本木', 'PARCO', 'LUMINE', 'KITTE', '丸の内', '代官山', '下北沢'],
    },
    'osaka': {
        'name': '大阪',
        'keywords': ['大阪', '梅田', 'ハルカス', '心斎橋', '難波', 'なんば',
                     'ルクア', 'グランフロント', '天王寺'],
    },
    'nagoya': {
        'name': '名古屋',
        'keywords': ['名古屋', '栄', '金山', '大須'],
    },
    'fukuoka': {
        'name': '福岡',
        'keywords': ['福岡', '博多', '天神', 'キャナルシティ'],
    },
    'yokohama': {
        'name': '横浜',
        'keywords': ['横浜', 'みなとみらい', 'Kアリーナ', 'ランドマーク'],
    },
    'kyoto': {
        'name': '京都',
        'keywords': ['京都', '四条', '河原町'],
    },
}


def _wp_request(url, data=None):
    headers = {'Authorization': f'Basic {AUTH}'}
    method = 'GET'
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/json'
        method = 'POST'
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def fetch_popups_in_region(keywords):
    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100'
                + '&_fields=id,title,meta,link'
        )
    except Exception:
        return []
    matched = []
    for p in popups:
        title = p.get('title', {}).get('rendered', '')
        venue = p.get('meta', {}).get('_popup_address', '') or ''
        text = title + ' ' + venue
        if any(k in text for k in keywords):
            matched.append(p)
    return matched


def generate_region_html(region_name, popups):
    html = (
        f'<p>{region_name}で開催中・開催予定のK-POP関連ポップアップストア、'
        f'コラボカフェ、期間限定イベントを完全網羅します。</p>\n'
    )
    if not popups:
        html += '<p>現在、該当地域のポップアップ情報はありません。情報が入り次第更新します。</p>\n'
        return html

    html += f'<h2>開催中・開催予定 ({len(popups)}件)</h2>\n<ul>\n'
    for p in popups[:30]:
        meta = p.get('meta', {})
        start = meta.get('_popup_start_date', '')
        end = meta.get('_popup_end_date', '')
        dates = f'{start[:10]}\u301c{end[:10]}' if start and end else (start[:10] if start else 'TBA')
        link = p.get('link', '#')
        title = p.get('title', {}).get('rendered', '')
        html += (
            f'<li><strong><a href="{link}">{title}</a></strong>'
            f' \U0001f4c5 {dates}</li>\n'
        )
    html += '</ul>\n'
    html += (
        '<div class="kpj-popup-hub-cta" style="margin:30px 0 20px;padding:16px 20px;'
        'background:linear-gradient(135deg,#fff0f3,#f8f0ff);border-radius:12px;'
        'text-align:center;border:1px solid #ffd6e0;">'
        '<p style="margin:0;font-size:1.05em;font-weight:700;">'
        '<a href="https://www.kpopjournal.tokyo/popup/" '
        'style="color:#FF1B6B;text-decoration:none;">'
        '\u2728 開催中の全ポップアップ情報はこちら \u2728</a></p></div>\n'
    )
    html += '<p class="kpj-disclaimer"><em>このページは毎週火曜に自動更新されます。</em></p>\n'
    return html


def _upload_local_image(image_path, alt_text=''):
    """ローカル画像をWP Mediaにアップロード→media_idを返す"""
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
    except Exception:
        return None
    ext = os.path.splitext(image_path)[1][1:].lower() or 'jpg'
    ct = 'image/png' if ext == 'png' else ('image/webp' if ext == 'webp' else 'image/jpeg')
    filename = f"popup_region_{int(datetime.now(timezone.utc).timestamp())}.{ext}"
    req = urllib.request.Request(
        'https://www.kpopjournal.tokyo/wp-json/wp/v2/media',
        data=data,
        headers={
            'Authorization': f'Basic {AUTH}',
            'Content-Type': ct,
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            media_id = json.loads(r.read()).get('id')
        if media_id and alt_text:
            alt_body = json.dumps({'alt_text': alt_text}).encode()
            alt_req = urllib.request.Request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}',
                data=alt_body, method='POST',
                headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
            urllib.request.urlopen(alt_req, timeout=30)
        return media_id
    except Exception as e:
        print(f"    media upload error: {e}")
        return None


def _generate_and_set_thumbnail(post_id, title):
    """サムネイル生成→WPにアップロード→featured_media設定"""
    try:
        from lib.make_thumbnail_v6 import make_thumbnail_v6
        result = make_thumbnail_v6(title=title, post_id=str(post_id))
        path = result.get('output_path')
        if not path:
            print(f"    thumbnail generation returned no path")
            return False
        media_id = _upload_local_image(path, alt_text=title)
        if not media_id:
            print(f"    thumbnail upload failed")
            return False
        _wp_request(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}',
            data={'featured_media': media_id},
        )
        print(f"    thumbnail set: media_id={media_id}")
        return True
    except Exception as e:
        print(f"    thumbnail error: {e}")
    return False


def upsert_region_page(slug, region_name, popups):
    html = generate_region_html(region_name, popups)
    title = f'{region_name} K-POPポップアップ完全ガイド'
    page_slug = f'popup-region-{slug}'

    try:
        existing = _wp_request(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?slug={page_slug}&_fields=id'
        )
    except Exception:
        existing = []

    payload = {
        'title': title,
        'content': html,
        'status': 'publish',
        'slug': page_slug,
    }

    try:
        if existing:
            _wp_request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{existing[0]["id"]}',
                data=payload,
            )
            return 'updated', len(popups)
        else:
            resp = _wp_request(
                'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts',
                data=payload,
            )
            new_id = resp.get('id')
            if new_id:
                _generate_and_set_thumbnail(new_id, title)
                try:
                    from lib.post_publish_hook import run_post_publish
                    run_post_publish(new_id)
                except Exception as e:
                    print(f"    post_publish_hook error: {e}")
            return 'created', len(popups)
    except Exception as e:
        return 'error', str(e)


def main():
    print(f"=== popup地域別ページ: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} ===")
    for slug, info in REGIONS.items():
        popups = fetch_popups_in_region(info['keywords'])
        if not popups:
            print(f"  {slug}: 0件 skip")
            continue
        action, count = upsert_region_page(slug, info['name'], popups)
        print(f"  {slug}: {action} ({count}件)")


if __name__ == '__main__':
    main()
