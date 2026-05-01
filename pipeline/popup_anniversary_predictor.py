#!/usr/bin/env python3
"""過去のポップアップから来月の周年予測記事を生成 (毎月1日10:00 cron)"""
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


def main():
    now = datetime.now(JST)
    next_month = now.month + 1 if now.month < 12 else 1
    next_year = now.year if now.month < 12 else now.year + 1
    last_year_prefix = f'{now.year - 1}-{next_month:02d}'

    # 全popup取得
    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100&_fields=id,title,date,meta'
        )
    except Exception as e:
        print(f"fetch err: {e}")
        return

    # 1年前の同月に開催されたpopupを抽出
    last_year_popups = [
        p for p in popups
        if str(p.get('date', '')).startswith(last_year_prefix)
    ]

    if not last_year_popups:
        print(f'{last_year_prefix}: 過去popup 0件、予測スキップ')
        return

    # 予測記事生成
    html = (
        f'<p>昨年 {now.year - 1}年{next_month}月 に開催されたポップアップを参考に、'
        f'{next_year}年{next_month}月の開催が予想されるイベントをまとめました。</p>\n'
        f'<div style="border-left:4px solid #2196F3;background:#E3F2FD;padding:12px 16px;'
        f'margin:16px 0;border-radius:4px;">'
        f'<p style="margin:0;font-weight:bold;">本記事は予測情報です</p>'
        f'<p style="margin:8px 0 0 0;font-size:0.95em;">確定情報は公式発表をご確認ください。'
        f'確定次第、本サイトで随時更新します。</p></div>\n'
    )

    html += f'<h2>昨年同月開催実績 ({len(last_year_popups)}件)</h2>\n<ul>\n'
    for p in last_year_popups[:20]:
        title = p.get('title', {}).get('rendered', '')
        pub_date = p.get('date', '')[:10]
        html += f'<li><strong>{title}</strong> ({pub_date})</li>\n'
    html += '</ul>\n'

    html += (
        f'<h2>{next_year}年の再開催可能性</h2>\n'
        f'<p>例年同時期に周年企画やコラボイベントが行われる傾向があり、'
        f'本年も同種のポップアップ開催が期待されます。'
        f'最新情報は本サイトで随時更新します。</p>\n'
        f'<p class="kpj-disclaimer"><em>このページは毎月1日に自動更新されます。</em></p>\n'
    )

    title = f'{next_year}年{next_month}月開催予想 K-POPポップアップ'
    slug = f'popup-prediction-{next_year}-{next_month:02d}'

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

    try:
        if existing:
            _wp_request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{existing[0]["id"]}',
                data=payload,
            )
            print(f'予測記事更新: {slug} ({len(last_year_popups)}件)')
        else:
            _wp_request(
                'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts',
                data=payload,
            )
            print(f'予測記事新規: {slug} ({len(last_year_popups)}件)')
    except Exception as e:
        print(f'予測記事err: {e}')


if __name__ == '__main__':
    main()
