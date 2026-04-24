#!/usr/bin/env python3
"""Google Trends collector - K-POPアーティスト関連のRising検索"""
import json, os
from datetime import datetime

OUT = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'

ARTISTS = [
    'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'SEVENTEEN',
    'TWICE', 'IVE', 'LE SSERAFIM', 'ILLIT', 'Stray Kids',
]


def collect():
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("pytrends not installed")
        return 0

    try:
        pytrends = TrendReq(hl='ja-JP', tz=540, timeout=(10, 25))
    except Exception as e:
        print(f"pytrends init error: {e}")
        return 0

    signals = []
    for artist in ARTISTS[:5]:  # API rate limit考慮
        try:
            pytrends.build_payload([artist], timeframe='now 7-d', geo='JP')
            related = pytrends.related_queries()
            if not related or artist not in related:
                continue
            rising = related[artist].get('rising')
            if rising is None or rising.empty:
                continue
            for _, row in rising.head(5).iterrows():
                signals.append({
                    'timestamp': datetime.now().isoformat(),
                    'source': 'gtrends',
                    'source_id': 'google_trends_jp',
                    'keyword': artist,
                    'title': f"{artist} {row['query']}",
                    'url': f"https://trends.google.co.jp/trends/explore?q={artist}",
                    'engagement_score': float(min(row.get('value', 100), 500)) / 100,
                    'language': 'ja',
                    'raw_data': {
                        'rising_query': row['query'],
                        'value': int(row.get('value', 0)),
                    },
                })
        except Exception as e:
            print(f"gtrends error for {artist}: {e}")

    with open(OUT, 'a', encoding='utf-8') as f:
        for s in signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f"Google Trends: {len(signals)} signals")
    return len(signals)


if __name__ == '__main__':
    collect()
