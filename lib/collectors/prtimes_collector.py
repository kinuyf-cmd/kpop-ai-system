#!/usr/bin/env python3
"""PRTIMES collector - K-POP関連プレスリリース収集"""
import json, os, re, urllib.request
from datetime import datetime
from xml.etree import ElementTree as ET

OUT = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

FEEDS = [
    'https://prtimes.jp/index.rdf',
]
KEYWORDS = [
    'K-POP', 'KPOP', 'K-Pop', 'BTS', 'BLACKPINK', 'NewJeans', 'aespa',
    'SEVENTEEN', 'TWICE', 'IVE', 'LE SSERAFIM', '韓国', 'カムバック',
    '来日', 'ファンミーティング', '新曲', 'リリース', 'アルバム', 'ライブ',
]


def collect():
    signals = []
    for url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 KPOPJournal-Collector/1.0'
            })
            data = urllib.request.urlopen(req, timeout=30).read()

            try:
                root = ET.fromstring(data)
                ns = {
                    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                    'rss': 'http://purl.org/rss/1.0/',
                }
                items = root.findall('.//rss:item', ns) or root.findall('.//item')
            except ET.ParseError:
                text = data.decode('utf-8', errors='replace')
                matches = re.findall(
                    r'<item[^>]*>.*?<title>(.*?)</title>.*?<link>(.*?)</link>',
                    text, re.DOTALL,
                )
                items = [{'title': m[0], 'link': m[1]} for m in matches]

            for item in items[:50]:
                if isinstance(item, dict):
                    title = re.sub(r'<[^>]+>', '', item['title']).strip()
                    link = item['link'].strip()
                else:
                    title_el = item.find('rss:title', ns)
                    if title_el is None:
                        title_el = item.find('title')
                    link_el = item.find('rss:link', ns)
                    if link_el is None:
                        link_el = item.find('link')
                    title = (title_el.text or '').strip() if title_el is not None else ''
                    link = (link_el.text or '').strip() if link_el is not None else ''

                if not title:
                    continue

                matched = [kw for kw in KEYWORDS if kw.lower() in title.lower()]
                if not matched:
                    continue

                signals.append({
                    'timestamp': datetime.now().isoformat(),
                    'source': 'prtimes',
                    'source_id': 'prtimes',
                    'keyword': matched[0],
                    'title': title[:200],
                    'url': link,
                    'engagement_score': 1.5,
                    'language': 'ja',
                    'raw_data': {'all_keywords': matched},
                })
        except Exception as e:
            print(f"PRTIMES fetch error: {e}")

    with open(OUT, 'a', encoding='utf-8') as f:
        for s in signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f"PRTIMES: {len(signals)} signals")
    return len(signals)


if __name__ == '__main__':
    collect()
