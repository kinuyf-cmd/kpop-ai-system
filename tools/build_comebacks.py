#!/usr/bin/env python3
"""
build_comebacks.py — カムバック予定JSONビルダー

WP記事タイトルから「カムバック」「リリース」等のキーワードを持つ記事を抽出し、
Next.jsのpublic/data/comebacks.jsonに出力する。

Usage:
  python3 tools/build_comebacks.py

Output:
  /home/aiuser/kpopjournal-frontend/public/data/comebacks.json
"""
import json
import os
import re
import urllib.request
import base64
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpopjournal-frontend/public/data/comebacks.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

WP_URL = 'https://www.kpopjournal.tokyo'
AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()

# Known upcoming events (manual seed — updated by cron/pipeline)
MANUAL_SEED = [
    {"artist": "BTS", "date": "2026-06-13", "title": "BTS 13周年 FESTA"},
    {"artist": "NewJeans", "date": "2026-05-15", "title": "新曲リリース予定"},
    {"artist": "aespa", "date": "2026-05-22", "title": "正規3集"},
    {"artist": "SEVENTEEN", "date": "2026-06-03", "title": "ワールドツアー開幕"},
    {"artist": "ILLIT", "date": "2026-05-08", "title": "2ndミニアルバム"},
]


def fetch_comeback_articles():
    """WPからカムバック/リリース関連記事を取得"""
    comebacks = []
    try:
        q = urllib.parse.urlencode({
            'search': 'カムバック リリース',
            'per_page': 20,
            'status': 'publish',
            '_fields': 'id,slug,title,date',
            'orderby': 'date',
            'order': 'desc',
        })
        req = urllib.request.Request(
            f"{WP_URL}/wp-json/wp/v2/posts?{q}",
            headers={'Authorization': f'Basic {AUTH}'}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            posts = json.loads(r.read())

        artist_pattern = re.compile(
            r'(BTS|BLACKPINK|aespa|NewJeans|SEVENTEEN|TWICE|IVE|Stray Kids|'
            r'ENHYPEN|TXT|NCT|RIIZE|ILLIT|BABYMONSTER|LE SSERAFIM|ATEEZ|'
            r'NMIXX|TREASURE|GOT7|EXO|Red Velvet|BIGBANG|\(G\)I-DLE|MAMAMOO)'
        )

        for p in posts:
            title = p['title']['rendered']
            m = artist_pattern.search(title)
            if m:
                # 日付抽出
                date_m = re.search(r'(\d{1,2})月(\d{1,2})日', title)
                if date_m:
                    month, day = int(date_m.group(1)), int(date_m.group(2))
                    year = datetime.now().year
                    try:
                        d = datetime(year, month, day)
                        if d < datetime.now() - timedelta(days=7):
                            d = datetime(year + 1, month, day)
                        comebacks.append({
                            'artist': m.group(1),
                            'date': d.strftime('%Y-%m-%d'),
                            'title': re.sub(r'<[^>]+>', '', title)[:60],
                        })
                    except ValueError:
                        pass
    except Exception as e:
        print(f"WP API error: {e}")

    return comebacks


def main():
    # Combine manual seed + auto-extracted
    all_items = list(MANUAL_SEED)
    auto = fetch_comeback_articles()
    all_items.extend(auto)

    # Deduplicate by artist+date
    seen = set()
    unique = []
    for c in all_items:
        key = f"{c['artist']}-{c['date']}"
        if key in seen:
            continue
        seen.add(key)
        try:
            d = datetime.strptime(c['date'], '%Y-%m-%d')
            if d >= datetime.now() - timedelta(days=1):
                unique.append(c)
        except ValueError:
            pass

    unique.sort(key=lambda x: x['date'])
    unique = unique[:8]

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'updated_at': datetime.now().isoformat(),
            'items': unique,
        }, f, ensure_ascii=False, indent=2)

    print(f"comebacks.json: {len(unique)}件")
    for c in unique:
        print(f"  {c['date']} {c['artist']}: {c.get('title', '')[:40]}")


if __name__ == '__main__':
    import urllib.parse
    main()
