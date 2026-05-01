#!/usr/bin/env python3
"""アーティスト別ポップアップま��めページ生成 (毎週水曜10:00 cron)"""
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

ARTISTS = {
    'bts': {'name': 'BTS', 'keywords': ['BTS', 'Jin', 'SUGA', 'j-hope', 'RM', 'Jimin', 'V', 'Jung Kook']},
    'blackpink': {'name': 'BLACKPINK', 'keywords': ['BLACKPINK', 'LISA', 'JISOO', 'JENNIE', 'ROSÉ', 'LLOUD']},
    'newjeans': {'name': 'NewJeans', 'keywords': ['NewJeans']},
    'aespa': {'name': 'aespa', 'keywords': ['aespa']},
    'twice': {'name': 'TWICE', 'keywords': ['TWICE']},
    'seventeen': {'name': 'SEVENTEEN', 'keywords': ['SEVENTEEN']},
    'straykids': {'name': 'Stray Kids', 'keywords': ['Stray Kids']},
    'ive': {'name': 'IVE', 'keywords': ['IVE']},
    'lesserafim': {'name': 'LE SSERAFIM', 'keywords': ['LE SSERAFIM']},
    'enhypen': {'name': 'ENHYPEN', 'keywords': ['ENHYPEN']},
    'itzy': {'name': 'ITZY', 'keywords': ['ITZY']},
    'txt': {'name': 'TXT', 'keywords': ['TXT', 'TOMORROW X TOGETHER']},
    'nct': {'name': 'NCT', 'keywords': ['NCT', 'NCT WISH', 'NCT DREAM']},
    'riize': {'name': 'RIIZE', 'keywords': ['RIIZE']},
    'ateez': {'name': 'ATEEZ', 'keywords': ['ATEEZ', 'MIGHTEEZ']},
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


_popup_cache = None

def _get_all_popups():
    global _popup_cache
    if _popup_cache is not None:
        return _popup_cache
    try:
        _popup_cache = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100'
            '&_fields=id,title,meta,link,content'
        )
    except Exception:
        _popup_cache = []
    return _popup_cache


def fetch_popups_for_artist(keywords):
    popups = _get_all_popups()
    matched = []
    for p in popups:
        title = p.get('title', {}).get('rendered', '')
        content = p.get('content', {})
        if isinstance(content, dict):
            content = content.get('rendered', '')
        text = (title + ' ' + str(content)).upper()
        if any(k.upper() in text for k in keywords):
            matched.append(p)
    return matched


def generate_artist_html(artist_name, popups):
    html = (
        f'<p>{artist_name}\u95a2\u9023\u306e\u6700\u65b0\u30dd\u30c3\u30d7\u30a2\u30c3\u30d7\u30b9\u30c8\u30a2\u3001'
        f'\u30b3\u30e9\u30dc\u30ab\u30d5\u30a7\u3001\u671f\u9593\u9650\u5b9a\u30a4\u30d9\u30f3\u30c8\u3092'
        f'\u5b8c\u5168\u7db2\u7f85\u3002\u65e5\u672c\u30fb\u97d3\u56fd\u30fb\u6d77\u5916\u958b\u50ac\u3092'
        f'\u5730\u57df\u5225\u306b\u307e\u3068\u3081\u3066\u3044\u307e\u3059\u3002</p>\n'
    )
    if not popups:
        html += '<p>\u73fe\u5728\u3001\u8a72\u5f53\u30a2\u30fc\u30c6\u30a3\u30b9\u30c8\u306e\u30dd\u30c3\u30d7\u30a2\u30c3\u30d7\u60c5\u5831\u306f\u3042\u308a\u307e\u305b\u3093\u3002</p>\n'
        return html

    html += f'<h2>\u95a2\u9023\u30dd\u30c3\u30d7\u30a2\u30c3\u30d7 ({len(popups)}\u4ef6)</h2>\n<ul>\n'
    for p in popups[:30]:
        meta = p.get('meta', {})
        start = meta.get('_popup_start_date', '')
        end = meta.get('_popup_end_date', '')
        venue = meta.get('_popup_address', '') or 'TBA'
        dates = f'{start[:10]}\u301c{end[:10]}' if start and end else (start[:10] if start else 'TBA')
        link = p.get('link', '#')
        title = p.get('title', {}).get('rendered', '')
        html += (
            f'<li><strong><a href="{link}">{title}</a></strong>'
            f'<br>\U0001f4cd {venue} / \U0001f4c5 {dates}</li>\n'
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
    html += '<p class="kpj-disclaimer"><em>\u3053\u306e\u30da\u30fc\u30b8\u306f\u6bce\u9031\u6c34\u66dc\u306b\u81ea\u52d5\u66f4\u65b0\u3055\u308c\u307e\u3059\u3002</em></p>\n'
    return html


def main():
    print(f"=== popup\u30a2\u30fc\u30c6\u30a3\u30b9\u30c8\u5225\u30da\u30fc\u30b8: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} ===")
    created = 0
    updated = 0
    for slug, info in ARTISTS.items():
        popups = fetch_popups_for_artist(info['keywords'])
        if not popups:
            continue
        title = f'{info["name"]} \u30dd\u30c3\u30d7\u30a2\u30c3\u30d7\u5b8c\u5168\u30ac\u30a4\u30c9'
        page_slug = f'popup-artist-{slug}'

        try:
            existing = _wp_request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?slug={page_slug}&_fields=id'
            )
        except Exception:
            existing = []

        html = generate_artist_html(info['name'], popups)
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
                updated += 1
            else:
                _wp_request(
                    'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts',
                    data=payload,
                )
                created += 1
            print(f"  {slug}: {len(popups)}\u4ef6")
        except Exception as e:
            print(f"  {slug}: err {e}")

    print(f"\u65b0\u898f {created} / \u66f4\u65b0 {updated}")


if __name__ == '__main__':
    main()
