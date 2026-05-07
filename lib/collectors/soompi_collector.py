#!/usr/bin/env python3
"""Soompi (soompi.com) — 最も信頼性の高い英語K-POPニュースサイト"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log
from datetime import datetime

KPOP_KW = [
    'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'Red Velvet', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'EXO', 'RIIZE', 'KATSEYE', 'BABYMONSTER', 'GOT7', 'MAMAMOO', 'NMIXX',
    'TWS', 'KISS OF LIFE', 'fromis_9', 'TREASURE', 'MONSTA X', 'DAY6', 'PLAVE',
    'HYBE', 'SM Entertainment', 'YG', 'JYP', 'comeback', 'debut', 'concert', 'tour',
    'Billboard', 'chart', 'album', 'MV', 'music video',
]
URGENT_KW = ['breaking', 'confirmed', 'announces', 'wins', 'No.1', '#1', 'arrested',
             'disbands', 'leaves', 'dating', 'married', 'enlist',
             'KCON', 'kcon', 'setlist', 'lineup']

FEED_URL = 'https://www.soompi.com/feed'


def collect():
    signals = []
    try:
        html = fetch_html(FEED_URL)
    except Exception as e:
        log(f"Soompi feed error: {e}")
        return 0

    # RSS XML: <item><title>...</title><link>...</link></item>
    items = re.findall(r'<item>\s*<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>\s*<link>(.*?)</link>', html, re.DOTALL)
    seen = set()
    for title_raw, link in items:
        title = re.sub(r'<[^>]+>', '', title_raw).strip()
        link = link.strip()
        if link in seen or len(title) < 10:
            continue
        seen.add(link)
        matched = [k for k in KPOP_KW if k.lower() in title.lower()]
        if not matched:
            continue
        urgent = any(k.lower() in title.lower() for k in URGENT_KW)
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'english_media',
            'source_id': 'soompi',
            'keyword': matched[0],
            'title': title[:300],
            'url': link,
            'engagement_score': 4.0 if urgent else 2.5,
            'language': 'en',
            'urgency': 'high' if urgent else 'normal',
            'raw_data': {'all_keywords': matched},
        })
        if len(signals) >= 30:
            break
    save_signals(signals)
    log(f"Soompi: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
