#!/usr/bin/env python3
"""月次ポップアップ集約ページ生成
毎月1日 09:00 + 毎週月曜 10:00 にcron実行
当月・翌月・翌々月の3ヶ月分を生成/更新
"""
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

JP_KW = ['東京', '大阪', '原宿', '渋谷', '表参道', '梅田', '名古屋', '福岡',
         '横浜', '京都', '日本', '池袋', '銀座', '六本木', '新宿', '札幌',
         'PARCO', 'LUMINE', 'ハルカス', 'ラフォーレ']
KR_KW = ['ソウル', '江南', '弘大', '明洞', '釜山', '韓国', '聖水', '蚕室', '新沙', '龍山']


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


def fetch_popups_for_month(year, month):
    """該当月に開催中/予定のpopup記事を取得"""
    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100'
        )
    except Exception as e:
        print(f"  fetch err: {e}")
        return []

    target = f'{year}-{month:02d}'
    matched = []
    for p in popups:
        meta = p.get('meta', {})
        start = meta.get('_popup_start_date', '')
        end = meta.get('_popup_end_date', '')
        # 該当月に重なるもの
        if start and start[:7] <= target and (not end or end[:7] >= target):
            matched.append(p)
        elif start and start[:7] == target:
            matched.append(p)
        elif not start:
            # 日程未確定だが投稿月が該当月
            pub_month = p.get('date', '')[:7]
            if pub_month == target:
                matched.append(p)

    # 重複排除
    seen = set()
    dedup = []
    for p in matched:
        if p['id'] not in seen:
            seen.add(p['id'])
            dedup.append(p)
    return dedup


def classify_region(title, meta):
    venue = meta.get('_popup_address', '') or meta.get('_popup_venue', '')
    text = title + ' ' + venue
    if any(k in text for k in JP_KW):
        return 'jp'
    if any(k in text for k in KR_KW):
        return 'kr'
    return 'other'


def generate_roundup_html(year, month, popups):
    jp = []
    kr = []
    other = []
    for p in popups:
        title = p.get('title', {}).get('rendered', '')
        meta = p.get('meta', {})
        region = classify_region(title, meta)
        if region == 'jp':
            jp.append(p)
        elif region == 'kr':
            kr.append(p)
        else:
            other.append(p)

    html = (
        f'<p>{year}年{month}月に日本・韓国で開催されるK-POP関連のポップアップストア、'
        f'コラボカフェ、期間限定ストアを完全網羅。会場・日程・最寄駅まで詳細解説します。</p>'
    )

    for region_name, items, flag in [
        ('日本', jp, '\U0001f1ef\U0001f1f5'),
        ('韓国', kr, '\U0001f1f0\U0001f1f7'),
        ('その他', other, '\U0001f30f'),
    ]:
        if not items:
            continue
        html += f'<h2>{flag} {region_name} ({len(items)}件)</h2>\n<ul>\n'
        for p in items:
            title = p.get('title', {}).get('rendered', '')
            link = p.get('link', '')
            meta = p.get('meta', {})
            start = meta.get('_popup_start_date', '')
            end = meta.get('_popup_end_date', '')
            venue = meta.get('_popup_address', '') or 'TBA'
            dates = f'{start[:10]}〜{end[:10]}' if start and end else (start[:10] if start else 'TBA')
            html += (
                f'<li><strong><a href="{link}">{title}</a></strong>'
                f'<br>\U0001f4cd {venue} / \U0001f4c5 {dates}</li>\n'
            )
        html += '</ul>\n'

    if not popups:
        html += '<p>現在、該当月のポップアップ情報はまだ登録されていません。情報が入り次第更新します。</p>\n'

    html += (
        f'<p class="kpj-disclaimer"><em>このページは毎週月曜と毎月1日に自動更新されます。'
        f'最新情報は各個別記事をご覧ください。</em></p>'
    )
    return html


def _upload_thumbnail(image_path, title_slug):
    """サムネをWP media libraryにアップロード"""
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
        import urllib.parse
        filename = f'roundup_{title_slug}.png'
        req = urllib.request.Request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/media',
            data=data, method='POST',
            headers={
                'Authorization': f'Basic {AUTH}',
                'Content-Type': 'image/png',
                'Content-Disposition': f'attachment; filename="{filename}"',
            },
        )
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return r.get('id')
    except Exception as e:
        print(f"  thumb upload err: {e}")
        return None


def upsert_roundup(year, month):
    popups = fetch_popups_for_month(year, month)
    html = generate_roundup_html(year, month, popups)
    title = f'{year}年{month}月 K-POPポップアップ完全マップ'
    slug = f'popup-roundup-{year}-{month:02d}'

    # サムネ生成
    thumb_media_id = None
    try:
        from lib.popup_roundup_thumbnail import generate_roundup_thumbnail
        jp_count = sum(1 for p in popups
                       if any(k in p.get('title', {}).get('rendered', '')
                              for k in JP_KW))
        kr_count = sum(1 for p in popups
                       if any(k in p.get('title', {}).get('rendered', '')
                              for k in KR_KW))
        gl_count = len(popups) - jp_count - kr_count
        thumb_path = f'/tmp/roundup_{year}_{month:02d}.png'
        if generate_roundup_thumbnail(year, month, jp_count, kr_count, gl_count, thumb_path):
            thumb_media_id = _upload_thumbnail(thumb_path, f'{year}_{month:02d}')
            if thumb_media_id:
                print(f"  サムネ: media_id={thumb_media_id}")
    except Exception as e:
        print(f"  サムネ生成skip: {e}")

    # 既存記事を検索
    try:
        existing = _wp_request(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?slug={slug}&_fields=id'
        )
    except Exception:
        existing = []

    payload = {
        'title': title,
        'content': html,
        'status': 'publish',
        'slug': slug,
    }
    if thumb_media_id:
        payload['featured_media'] = thumb_media_id

    try:
        if existing:
            pid = existing[0]['id']
            _wp_request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}',
                data=payload,
            )
            return {'action': 'updated', 'id': pid, 'popup_count': len(popups)}
        else:
            result = _wp_request(
                'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts',
                data=payload,
            )
            return {'action': 'created', 'id': result.get('id'), 'popup_count': len(popups)}
    except Exception as e:
        return {'action': 'error', 'error': str(e), 'popup_count': len(popups)}


def main():
    now = datetime.now(JST)
    print(f"=== popup月次集約: {now.strftime('%Y-%m-%d %H:%M')} ===")

    for offset in range(3):
        m = now.month + offset
        y = now.year
        if m > 12:
            m -= 12
            y += 1
        result = upsert_roundup(y, m)
        print(f"  {y}年{m}月: {result}")


if __name__ == '__main__':
    main()
