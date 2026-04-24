#!/usr/bin/env python3
"""build_events.py — 1ヶ月以内のイベント記事からJSON生成 (厳格版 2026-04-24)

考察・まとめ系記事を除外し、会場名の存在を必須条件にすることで
UpcomingEvents に不適切な記事が混入するのを防ぐ。
"""
import json
import os
import re
import urllib.request
import urllib.parse
import base64
from datetime import datetime, timezone, timedelta

OUT = '/home/aiuser/kpopjournal-frontend/public/data/events.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)
auth = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()

# 除外パターン (考察・まとめ・解説系)
EXCLUDE_TITLE = re.compile(
    r'考察|ガイド|徹底|なぜ|全貌|真相|解説|まとめ|入門|初心者|'
    r'〜とは|ルーティン|完全体|秘密|裏側|正体|論$'
)

# 会場キーワード (必須)
VENUE_PATTERN = re.compile(
    r'(東京ドーム|京セラドーム|国立競技場|さいたまスーパーアリーナ|'
    r'ナゴヤドーム|福岡PayPayドーム|横浜アリーナ|Kアリーナ横浜|'
    r'日本武道館|代々木第一体育館|有明アリーナ|幕張メッセ|'
    r'[一-龠ぁ-ん]{2,6}ホール|[一-龠ぁ-ん]{2,6}ドーム|'
    r'[一-龠ぁ-ん]{2,6}アリーナ|[一-龠ぁ-ん]{2,6}スタジアム|'
    r'[A-Z][A-Za-z ]*(?:Arena|Stadium|Dome))'
)

# 日付パターン
DATE_YMD = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')
DATE_MD = re.compile(r'(\d{1,2})月(\d{1,2})日')

items = []
try:
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug=event&_fields=id",
        headers={'Authorization': f'Basic {auth}'})
    cid = json.loads(urllib.request.urlopen(req, timeout=20).read())[0]['id']

    params = urllib.parse.urlencode({
        'categories': cid, 'per_page': 30, 'status': 'publish',
        '_fields': 'id,slug,title,excerpt,content,date',
    })
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?{params}",
        headers={'Authorization': f'Basic {auth}'})
    posts = json.loads(urllib.request.urlopen(req, timeout=20).read())

    for p in posts:
        title = re.sub(r'<[^>]+>', '', p['title']['rendered'])

        # 考察系を除外
        if EXCLUDE_TITLE.search(title):
            continue

        body = ' '.join([
            title,
            p.get('excerpt', {}).get('rendered', ''),
            (p.get('content', {}).get('rendered', '') or '')[:3000],
        ])

        # 日付抽出 (年月日 > 月日)
        m_ymd = DATE_YMD.search(body)
        if m_ymd:
            y, mo, da = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
        else:
            m_md = DATE_MD.search(body)
            if not m_md:
                continue
            mo, da = int(m_md.group(1)), int(m_md.group(2))
            y = datetime.now().year

        try:
            d = datetime(y, mo, da)
            # 過去日付で年が明示されていなければ翌年に
            if d < datetime.now() - timedelta(days=1):
                if not m_ymd:
                    d = datetime(y + 1, mo, da)
                else:
                    continue  # 年明示で過去 → 終了済みイベント
            if d > datetime.now() + timedelta(days=31):
                continue
        except ValueError:
            continue

        # 会場必須
        venue_m = VENUE_PATTERN.search(body)
        if not venue_m:
            continue

        items.append({
            'title': title[:80],
            'date': d.strftime('%Y-%m-%d'),
            'venue': venue_m.group(1),
            'slug': p['slug'],
        })
except Exception as e:
    print(f"Error: {e}")

# 重複除去
seen = set()
unique = []
for it in items:
    key = f"{it['date']}-{it['venue']}"
    if key in seen:
        continue
    seen.add(key)
    unique.append(it)

unique.sort(key=lambda x: x['date'])
json.dump({'updated_at': datetime.now().isoformat(), 'items': unique[:12]},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"events.json: {len(unique)}件 (厳格版)")
for it in unique[:5]:
    print(f"  {it['date']}: {it['title'][:50]} @ {it['venue']}")
