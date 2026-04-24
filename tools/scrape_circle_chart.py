#!/usr/bin/env python3
"""Circle Chart (circlechart.kr) 週次Top10スクレイパー

API: POST /data/api/chart/onoff
  - serviceGbn=S1020 (ストリーミングチャート)
  - termGbn=week
  - targetTime=<週番号> (ISO week)

失敗時: chart_weekly_manual.json を現状維持で継続使用
"""
import json, os, subprocess, urllib.parse, urllib.request
from datetime import datetime

API_URL = 'https://circlechart.kr/data/api/chart/onoff'
MANUAL_OUT = '/home/aiuser/kpop-ai-system/data/chart_weekly_manual.json'


def fetch_chart(year, week):
    """Circle Chart APIから週次ストリーミングチャートを取得"""
    params = {
        'nationGbn': 'T',
        'serviceGbn': 'S1020',
        'termGbn': 'week',
        'hitYear': str(year),
        'targetTime': str(week),
        'yearTime': '3',
        'curUrl': '/page_chart/onoff.circle?serviceGbn=S1020',
    }
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API_URL, data=data, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://circlechart.kr/page_chart/onoff.circle?serviceGbn=S1020',
        'X-Requested-With': 'XMLHttpRequest',
    })
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode('utf-8', errors='replace'))


def scrape():
    now = datetime.now()
    year = now.year
    week = now.isocalendar().week

    # 当週→前週の順で試行（チャート公開に1週ラグがある場合）
    for w in [week, week - 1]:
        if w < 1:
            continue
        try:
            j = fetch_chart(year, w)
        except Exception as e:
            print(f"  fetch error week {w}: {e}")
            continue

        if j.get('ResultStatus') != 'OK':
            print(f"  week {w}: API returned {j.get('ResultStatus')}")
            continue

        lst = j.get('List', {})
        if not lst:
            continue

        items = list(lst.values())
        items.sort(key=lambda x: int(x.get('SERVICE_RANKING', 999)))

        entries = []
        for item in items[:10]:
            rank = int(item.get('SERVICE_RANKING', 0))
            prev_raw = item.get('PRE_SERVICE_RANKING', '')
            prev_rank = int(prev_raw) if prev_raw and prev_raw.isdigit() else None
            entries.append({
                'rank': rank,
                'prevRank': prev_rank,
                'title': item.get('SONG_NAME', '')[:40],
                'artist': item.get('ARTIST_NAME', '')[:30],
                'weeksOnChart': None,
            })

        if len(entries) >= 5:
            print(f"  week {w}: {len(entries)}件取得")
            return entries, year, w

    return None, year, week


def update_manual_json(entries, year, week):
    """chart_weekly_manual.json を更新"""
    now = datetime.now()
    data = {
        '_comment': '週次チャート (Circle Chart API自動取得)',
        '_source_reference': 'circlechart.kr/data/api/chart/onoff (S1020 streaming)',
        '_last_updated_by': 'scraper',
        'week': f'{year}-W{week:02d}',
        'week_label': f'{year}年{now.month}月第{((now.day - 1) // 7) + 1}週',
        'source': 'Circle Chart (Korea Official)',
        'updated_at': now.isoformat(),
        'entries': entries,
    }
    with open(MANUAL_OUT, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    entries, year, week = scrape()
    if entries and len(entries) >= 5:
        update_manual_json(entries, year, week)
        print(f"✅ Circle Chart取得成功: {len(entries)}件 ({year}-W{week:02d})")
        for e in entries:
            print(f"  {e['rank']}. {e['title']} - {e['artist']}")

        # build_chart_weekly.py を呼んで public/data に反映
        r = subprocess.run(
            ['python3', '/home/aiuser/kpop-ai-system/tools/build_chart_weekly.py'],
            capture_output=True, text=True,
        )
        print(r.stdout)
        if r.stderr:
            print(r.stderr)
    else:
        print("🔴 Circle Chart取得失敗 or データ不足")
        print("  → chart_weekly_manual.json を現状維持")
