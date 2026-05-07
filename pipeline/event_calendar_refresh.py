#!/usr/bin/env python3
"""イベントカレンダー週次更新 (毎週月曜9時)

1. events_manual.json → frontend/public/data/events.json 同期
2. WP固定ページ (event-calendar) のテーブルを最新化
"""
import sys, os, json, base64, urllib.request, urllib.parse
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
load_dotenv('/home/aiuser/kpop-ai-system/.env')

AUTH = base64.b64encode(
    f'{os.getenv("WP_USER","")}:{os.getenv("WP_PASS","")}'.encode()
).decode()
DAYNAMES = ['月', '火', '水', '木', '金', '土', '日']


def load_events():
    path = '/home/aiuser/kpop-ai-system/config/events_manual.json'
    d = json.load(open(path, encoding='utf-8'))
    return d.get('events', [])


def sync_frontend_json(events):
    today = datetime.now()
    items = []
    for e in events:
        ds = e.get('date_start', '')
        de = e.get('date_end', '') or ds
        if not ds:
            continue
        try:
            dt_start = datetime.fromisoformat(ds)
            dt_end = datetime.fromisoformat(de) if de else dt_start
            # 終了日が今日以降 = まだ開催中 or これから開催
            if dt_end >= today - timedelta(days=1):
                items.append({
                    'title': e.get('title', ''),
                    'date': ds,
                    'date_end': de,
                    'date_tba': e.get('date_tba', False),
                    'venue': e.get('venue', '') or e.get('location', ''),
                    'slug': e.get('article_slug', ''),
                    'url': e.get('official_url', '') or e.get('url', ''),
                    'artist': ','.join(e.get('tags', [])[:3]),
                })
        except Exception:
            pass
    # 日付未定は末尾に並べる（プレースホルダ日付に引きずられない）
    items.sort(key=lambda x: (x.get('date_tba', False), x['date']))
    out = {'updated_at': datetime.now().isoformat(), 'items': items}
    out_path = '/home/aiuser/kpopjournal-frontend/public/data/events.json'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return items


def update_wp_page(events):
    today = datetime.now()
    in30 = today + timedelta(days=30)

    up30 = []
    for e in events:
        ds = e.get('date_start', '')
        de = e.get('date_end', '') or ds
        if not ds:
            continue
        try:
            dt_start = datetime.fromisoformat(ds)
            dt_end = datetime.fromisoformat(de) if de else dt_start
            # 終了日が今日以降 AND 開始日が30日以内 = 開催中 or 近日開催
            if dt_end >= today and dt_start <= in30:
                up30.append((dt_start, e))
        except Exception:
            pass
    up30.sort(key=lambda x: x[0])

    content = f'<p>K-POPファン必見のイベント一覧。最終更新: {today.strftime("%Y年%m月%d日")}</p>\n'
    content += '<h2>近日開催のイベント</h2>\n'

    if up30:
        content += '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:#FF1493;color:white;"><th style="padding:12px;text-align:left;">開催日</th><th style="padding:12px;text-align:left;">イベント名</th><th style="padding:12px;text-align:left;">会場</th></tr></thead><tbody>\n'
        for dt, e in up30:
            venue = e.get('venue', '') or '未定'
            de = e.get('date_end', '')[:10]
            dd = f'{dt.strftime("%m/%d")}({DAYNAMES[dt.weekday()]})'
            if de and de != dt.strftime('%Y-%m-%d'):
                dd += f'~{de[5:]}'
            content += f'<tr style="border-bottom:1px solid #eee;"><td style="padding:10px;font-weight:bold;">{dd}</td><td style="padding:10px;">{e.get("title","")}</td><td style="padding:10px;color:#666;">{venue}</td></tr>\n'
        content += '</tbody></table>\n'
    else:
        content += '<p>現在、近日開催のイベント情報はありません。</p>\n'

    content += '\n<p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は各公式サイトをご確認ください。</p>'

    slug = 'event-calendar'
    sq = urllib.parse.quote(slug)
    req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages?slug={sq}&_fields=id',
        headers={'Authorization': f'Basic {AUTH}'},
    )
    existing = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if not existing:
        return 0

    pid = existing[0]['id']
    data = json.dumps({'content': content}).encode()
    req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/pages/{pid}',
        data=data, method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
    )
    urllib.request.urlopen(req, timeout=30)
    return len(up30)


def main():
    events = load_events()
    items = sync_frontend_json(events)
    count = update_wp_page(events)
    print(f'[{datetime.now().isoformat()}] event_calendar_refresh 完了: frontend={len(items)}件 wp_30d={count}件')


if __name__ == '__main__':
    main()
