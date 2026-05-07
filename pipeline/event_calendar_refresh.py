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
                    'category': e.get('type', 'event'),
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


def _classify_event_type(e):
    """イベントをフィルターカテゴリに分類"""
    t = e.get('type', 'event')
    title = e.get('title', '').lower()
    if t in ('concert', 'festival') or any(k in title for k in ['ツアー', 'コンサート', 'ライブ', 'フェス', 'kcon', 'アリーナ', 'ドーム']):
        return 'concert'
    if t == 'popup' or 'ポップアップ' in title or 'pop-up' in title.lower():
        return 'popup'
    if t == 'comeback' or any(k in title for k in ['カムバック', 'comeback', 'アルバム', 'ミニアルバム', 'シングル']):
        return 'comeback'
    if t == 'fanmeeting' or 'ファンミ' in title:
        return 'concert'  # コンサート/フェスに統合
    return 'other'


FILTER_LABELS = {
    'concert': 'コンサート / フェス',
    'popup': 'ポップアップ',
    'comeback': 'カムバック',
    'other': 'その他',
}

FILTER_COLORS = {
    'concert': '#FF1493',
    'popup': '#8B5CF6',
    'comeback': '#F59E0B',
    'other': '#6B7280',
}


def update_wp_page(events):
    today = datetime.now()
    in60 = today + timedelta(days=60)

    up_events = []
    for e in events:
        ds = e.get('date_start', '')
        de = e.get('date_end', '') or ds
        if not ds:
            continue
        try:
            dt_start = datetime.fromisoformat(ds)
            dt_end = datetime.fromisoformat(de) if de else dt_start
            if dt_end >= today and dt_start <= in60:
                cat = _classify_event_type(e)
                up_events.append((dt_start, e, cat))
        except Exception:
            pass
    up_events.sort(key=lambda x: x[0])

    # カムバック情報も追加
    try:
        cb_path = '/home/aiuser/kpop-ai-system/config/comeback_calendar.json'
        cb_data = json.load(open(cb_path, encoding='utf-8'))
        for p in cb_data.get('predictions', []) + cb_data.get('ai_predictions', []):
            pred_date = p.get('predicted_next', '')
            if not pred_date:
                continue
            try:
                dt = datetime.fromisoformat(pred_date)
                if dt >= today and dt <= in60:
                    e = {
                        'title': f'{p.get("name", "")} カムバック予測',
                        'date_start': pred_date,
                        'date_end': pred_date,
                        'venue': '',
                        'type': 'comeback',
                        'tags': [p.get('name', '')],
                    }
                    up_events.append((dt, e, 'comeback'))
            except:
                pass
        up_events.sort(key=lambda x: x[0])
    except:
        pass

    # 存在するカテゴリのみフィルターボタンを表示
    active_cats = sorted(set(cat for _, _, cat in up_events),
                         key=lambda c: list(FILTER_LABELS.keys()).index(c) if c in FILTER_LABELS else 99)

    # HTML生成 — カテゴリ別セクション方式（JSなし、WPテーマ互換）
    content = f'<p>K-POPファン必見のイベント一覧。最終更新: {today.strftime("%Y年%m月%d日")}</p>\n'

    # フィルターナビゲーション（ページ内リンク）
    content += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:20px 0;">\n'
    content += (
        '<a href="#all-events" style="display:inline-block;padding:8px 18px;border:2px solid #333;'
        'background:#333;color:white;border-radius:20px;text-decoration:none;font-size:14px;'
        'font-weight:bold;">すべて</a>\n'
    )
    for cat in active_cats:
        label = FILTER_LABELS.get(cat, cat)
        color = FILTER_COLORS.get(cat, '#6B7280')
        content += (
            f'<a href="#{cat}" style="display:inline-block;padding:8px 18px;border:2px solid {color};'
            f'background:{color};color:white;border-radius:20px;text-decoration:none;font-size:14px;'
            f'font-weight:bold;">{label}</a>\n'
        )
    content += '</div>\n'

    # 全イベント表示セクション
    content += '<div id="all-events">\n'
    content += '<h2>近日開催のイベント</h2>\n'

    if up_events:
        content += '<table style="width:100%;border-collapse:collapse;">\n'
        content += '<thead><tr style="background:#FF1493;color:white;">'
        content += '<th style="padding:12px;text-align:left;">開催日</th>'
        content += '<th style="padding:12px;text-align:left;">カテゴリ</th>'
        content += '<th style="padding:12px;text-align:left;">イベント名</th>'
        content += '<th style="padding:12px;text-align:left;">会場</th>'
        content += '</tr></thead><tbody>\n'

        for dt, e, cat in up_events:
            venue = e.get('venue', '') or '未定'
            de = e.get('date_end', '')[:10]
            dd = f'{dt.strftime("%m/%d")}({DAYNAMES[dt.weekday()]})'
            if de and de != dt.strftime('%Y-%m-%d'):
                dd += f'~{de[5:]}'
            color = FILTER_COLORS.get(cat, '#6B7280')
            label = FILTER_LABELS.get(cat, cat)
            badge = (
                f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
                f'font-size:11px;font-weight:bold;color:white;background:{color};">'
                f'{label}</span>'
            )
            content += (
                f'<tr style="border-bottom:1px solid #eee;">'
                f'<td style="padding:10px;font-weight:bold;white-space:nowrap;">{dd}</td>'
                f'<td style="padding:10px;">{badge}</td>'
                f'<td style="padding:10px;">{e.get("title","")}</td>'
                f'<td style="padding:10px;color:#666;">{venue}</td>'
                f'</tr>\n'
            )
        content += '</tbody></table>\n'
    else:
        content += '<p>現在、近日開催のイベント情報はありません。</p>\n'
    content += '</div>\n'

    # カテゴリ別セクション
    for cat in active_cats:
        label = FILTER_LABELS.get(cat, cat)
        color = FILTER_COLORS.get(cat, '#6B7280')
        cat_events = [(dt, e) for dt, e, c in up_events if c == cat]
        if not cat_events:
            continue

        content += f'<div id="{cat}">\n'
        content += f'<h2 style="border-left:4px solid {color};padding-left:10px;margin-top:30px;">{label}</h2>\n'
        content += '<table style="width:100%;border-collapse:collapse;"><thead><tr style="background:' + color + ';color:white;">'
        content += '<th style="padding:12px;text-align:left;">開催日</th>'
        content += '<th style="padding:12px;text-align:left;">イベント名</th>'
        content += '<th style="padding:12px;text-align:left;">会場</th>'
        content += '</tr></thead><tbody>\n'

        for dt, e in cat_events:
            venue = e.get('venue', '') or '未定'
            de = e.get('date_end', '')[:10]
            dd = f'{dt.strftime("%m/%d")}({DAYNAMES[dt.weekday()]})'
            if de and de != dt.strftime('%Y-%m-%d'):
                dd += f'~{de[5:]}'
            content += (
                f'<tr style="border-bottom:1px solid #eee;">'
                f'<td style="padding:10px;font-weight:bold;white-space:nowrap;">{dd}</td>'
                f'<td style="padding:10px;">{e.get("title","")}</td>'
                f'<td style="padding:10px;color:#666;">{venue}</td>'
                f'</tr>\n'
            )
        content += '</tbody></table>\n'
        content += '</div>\n'

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
    return len(up_events)


def main():
    events = load_events()
    items = sync_frontend_json(events)
    count = update_wp_page(events)
    print(f'[{datetime.now().isoformat()}] event_calendar_refresh 完了: frontend={len(items)}件 wp_30d={count}件')


if __name__ == '__main__':
    main()
