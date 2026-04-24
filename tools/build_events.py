#!/usr/bin/env python3
"""build_events.py — 厳格ファクトチェック版 (2026-04-27 第3世代)

条件 (ALL必須):
1. 記事タイトルに会場名が含まれる
2. タイトルに年月日が明示 (4/27形式OK、「来月」等NG)
3. タイトルにアーティスト名
4. 除外ワードNG (考察/ガイド/解説等)
5. eventカテゴリ直下の記事のみ
"""
import json, os, re, urllib.request, urllib.parse, base64
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpopjournal-frontend/public/data/events.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)
auth = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()

EXCLUDE = re.compile(
    r'考察|ガイド|徹底|なぜ|全貌|真相|解説|まとめ|入門|初心者|'
    r'〜とは|ルーティン|完全体|秘密|裏側|正体|論$|予想|予測|振り返り'
)

VENUE = re.compile(
    r'(東京ドーム|京セラドーム|国立競技場|さいたまスーパーアリーナ|'
    r'ナゴヤドーム|福岡PayPayドーム|横浜アリーナ|Kアリーナ横浜|'
    r'日本武道館|代々木第一体育館|有明アリーナ|幕張メッセ|'
    r'東京ガーデンシアター|大阪城ホール|ぴあアリーナMM|'
    r'Zepp [一-龠A-Za-z]+|Kアリーナ|インテックス大阪)'
)

DATE_YMD = re.compile(r'(20\d{2})[年/\-](\d{1,2})[月/\-](\d{1,2})[日]?')
DATE_MD = re.compile(r'(\d{1,2})月(\d{1,2})日')

ARTIST_PATTERN = re.compile(
    r'(BTS|BLACKPINK|aespa|NewJeans|SEVENTEEN|TWICE|IVE|LE SSERAFIM|ILLIT|'
    r'ITZY|Red Velvet|TXT|Stray Kids|ENHYPEN|NCT|ATEEZ|TWS|'
    r'KISS OF LIFE|&TEAM|BOYNEXTDOOR|RIIZE|ZEROBASEONE|MEOVV|'
    r'IU|LISA|JENNIE|Rosé|JISOO|V|Jungkook|Jimin|JIN|RM|J-HOPE|SUGA|'
    r'ジミン|ジョングク|ジン|ブイ)'
)

items = []
try:
    cr = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug=event&_fields=id",
        headers={'Authorization': f'Basic {auth}'})
    cid = json.loads(urllib.request.urlopen(cr, timeout=20).read())[0]['id']

    q = urllib.parse.urlencode({
        'categories': cid, 'per_page': 30, 'status': 'publish',
        '_fields': 'id,slug,title,date'
    })
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?{q}",
        headers={'Authorization': f'Basic {auth}'})
    posts = json.loads(urllib.request.urlopen(req, timeout=20).read())

    for p in posts:
        title = re.sub(r'<[^>]+>', '', p['title']['rendered'])

        # 除外ワード
        if EXCLUDE.search(title):
            continue

        # 会場必須 (タイトル内)
        v = VENUE.search(title)
        if not v:
            continue

        # アーティスト必須 (タイトル内)
        a = ARTIST_PATTERN.search(title)
        if not a:
            continue

        # 日付必須 (タイトル内、年付きまたは月日)
        m_ymd = DATE_YMD.search(title)
        if m_ymd:
            y, mo, da = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
        else:
            m_md = DATE_MD.search(title)
            if not m_md:
                continue
            mo, da = int(m_md.group(1)), int(m_md.group(2))
            y = datetime.now().year

        try:
            d = datetime(y, mo, da)
            if d < datetime.now() - timedelta(days=1):
                if not m_ymd:
                    d = datetime(y + 1, mo, da)
                else:
                    continue
            if d > datetime.now() + timedelta(days=31):
                continue
        except ValueError:
            continue

        items.append({
            'title': title[:80],
            'date': d.strftime('%Y-%m-%d'),
            'venue': v.group(1),
            'artist': a.group(1),
            'slug': p['slug'],
        })
except Exception as e:
    print(f"Error: {e}")

# 重複除去
seen = set()
unique = []
for it in items:
    key = f"{it['artist']}-{it['date']}-{it['venue']}"
    if key in seen:
        continue
    seen.add(key)
    unique.append(it)

unique.sort(key=lambda x: x['date'])

json.dump({'updated_at': datetime.now().isoformat(), 'items': unique[:12]},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"events.json: {len(unique)}件 (ファクトチェック厳格版)")
for it in unique[:5]:
    print(f"  {it['date']} {it['artist']} @ {it['venue']}: {it['title'][:40]}")
