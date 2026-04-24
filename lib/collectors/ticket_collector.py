#!/usr/bin/env python3
"""チケットガイドcollector - K-POP公演情報"""
import json, os, re, urllib.request
from datetime import datetime

OUT = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'

SOURCES = [
    ('https://t.pia.jp/pia/events/kpop/', 'pia'),
]

KEYWORDS = [
    'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'SEVENTEEN', 'TWICE',
    'IVE', 'LE SSERAFIM', 'ILLIT', 'Stray Kids', 'TXT', 'ENHYPEN',
    'ATEEZ', 'ITZY', 'NCT', 'K-POP',
]


def collect():
    signals = []
    for url, source_id in SOURCES:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 KPOPJournal/1.0'
            })
            data = urllib.request.urlopen(req, timeout=20).read().decode(
                'utf-8', errors='replace'
            )

            # RSS items
            items = re.findall(
                r'<item[^>]*>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>'
                r'.*?<link>(.*?)</link>',
                data, re.DOTALL,
            )
            if not items:
                # HTML fallback
                items = re.findall(
                    r'<a\s+href="([^"]*(?:concert|event|artist)[^"]*)"'
                    r'[^>]*>([^<]{5,80})</a>',
                    data,
                )
                items = [(title, link) for link, title in items]

            for title_raw, link in items[:30]:
                title = re.sub(r'<[^>]+>', '', title_raw).strip()
                matched = [k for k in KEYWORDS if k.lower() in title.lower()]
                if not matched:
                    continue
                signals.append({
                    'timestamp': datetime.now().isoformat(),
                    'source': 'ticket_guide',
                    'source_id': source_id,
                    'keyword': matched[0],
                    'title': title[:200],
                    'url': link.strip(),
                    'engagement_score': 2.0,
                    'language': 'ja',
                    'raw_data': {'all_keywords': matched, 'category': 'event'},
                })
        except Exception as e:
            print(f"{source_id} error: {e}")

    with open(OUT, 'a', encoding='utf-8') as f:
        for s in signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f"Ticket guide: {len(signals)} signals")
    return len(signals)


if __name__ == '__main__':
    collect()
