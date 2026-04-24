#!/usr/bin/env python3
"""build_chart_weekly.py — 週次チャートJSON生成

優先度:
1. data/chart_weekly_manual.json (手動キュレーション)
2. Soompi週次記事自動パース (fallback)
3. 前回のJSONを継続使用 (両方失敗時)
"""
import json, os, re, urllib.request, urllib.parse, base64
from datetime import datetime

OUT = '/home/aiuser/kpopjournal-frontend/public/data/chart_weekly.json'
MANUAL = '/home/aiuser/kpop-ai-system/data/chart_weekly_manual.json'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

chart_data = None
source_used = 'unknown'

# 1) 手動キュレーション優先
if os.path.exists(MANUAL):
    try:
        m = json.load(open(MANUAL, encoding='utf-8'))
        if m.get('entries') and len(m['entries']) > 0:
            chart_data = {
                'updated_at': datetime.now().isoformat(),
                'week_label': m.get('week_label', ''),
                'source': m.get('source', 'manual'),
                'entries': m['entries'][:10],
            }
            source_used = 'manual'
    except Exception as e:
        print(f"manual read error: {e}")

# 2) Soompi週次記事から自動パース (fallback)
if not chart_data:
    try:
        auth = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
        q = urllib.parse.urlencode({
            'search': 'チャート',
            'per_page': 3,
            'status': 'publish',
            'orderby': 'date',
            'order': 'desc',
            '_fields': 'id,title,content,date',
        })
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?{q}"
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}'})
        posts = json.loads(urllib.request.urlopen(req, timeout=20).read())
        if posts:
            content = posts[0].get('content', {}).get('rendered', '')
            entries = []
            patterns = [
                r'第?\s*(\d{1,2})\s*位[\s\S]{0,10}?([^<\n「」／\-\/]{2,40})\s*[/\-／][\s\S]{0,5}?([^<\n「」\-\/]{2,30})',
            ]
            for pat in patterns:
                for m in re.finditer(pat, content):
                    rank = int(m.group(1))
                    if rank > 10:
                        continue
                    title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                    artist = re.sub(r'<[^>]+>', '', m.group(3)).strip()
                    if title and artist:
                        entries.append({
                            'rank': rank, 'prevRank': None,
                            'title': title[:40], 'artist': artist[:30],
                            'weeksOnChart': None,
                        })
                if entries:
                    break

            if len(entries) >= 5:
                entries.sort(key=lambda e: e['rank'])
                chart_data = {
                    'updated_at': datetime.now().isoformat(),
                    'week_label': posts[0]['date'][:10],
                    'source': 'Soompi週次記事自動抽出',
                    'entries': entries[:10],
                }
                source_used = 'soompi_article'
    except Exception as e:
        print(f"soompi parse error: {e}")

# 3) 何もなければ空データ
if not chart_data:
    chart_data = {
        'updated_at': datetime.now().isoformat(),
        'week_label': '',
        'source': 'none',
        'entries': [],
    }
    source_used = 'empty'

json.dump(chart_data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"chart_weekly.json: source={source_used}, entries={len(chart_data['entries'])}")
for e in chart_data['entries'][:5]:
    print(f"  {e['rank']}. {e['title']} - {e['artist']}")
