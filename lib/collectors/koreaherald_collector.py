#!/usr/bin/env python3
"""Korea Herald K-POP (koreaherald.com) — 韓国最大の英字紙"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log, clean_title
from datetime import datetime

KPOP_KW = [
    'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'EXO', 'RIIZE', 'BABYMONSTER', 'NMIXX', 'GOT7', 'MAMAMOO',
    'HYBE', 'SM Entertainment', 'YG', 'JYP', 'K-pop', 'idol', 'comeback',
    'debut', 'album', 'concert', 'tour', 'Billboard', 'Grammy',
]


def collect():
    signals = []
    try:
        html = fetch_html('https://www.koreaherald.com/Kpop')
    except Exception as e:
        log(f"KoreaHerald fetch error: {e}")
        return 0

    patterns = [
        re.compile(r'href="(https://www\.koreaherald\.com/article/\d+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>', re.DOTALL),
        re.compile(r'href="(/article/\d+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>', re.DOTALL),
    ]
    seen = set()
    for pat in patterns:
        for m in pat.finditer(html):
            link, title = m.group(1), clean_title(m.group(2))
            if link in seen or len(title) < 10:
                continue
            seen.add(link)
            full_url = link if link.startswith('http') else 'https://www.koreaherald.com' + link
            matched = [k for k in KPOP_KW if k.lower() in title.lower()]
            if not matched:
                continue
            signals.append({
                'timestamp': datetime.now().isoformat(),
                'source': 'korean_media',
                'source_id': 'koreaherald',
                'keyword': matched[0],
                'title': title[:300],
                'url': full_url,
                'engagement_score': 3.0,
                'language': 'en',
                'urgency': 'normal',
                'raw_data': {'all_keywords': matched},
            })
    save_signals(signals[:20])
    log(f"KoreaHerald: {len(signals[:20])}")
    return len(signals[:20])


if __name__ == '__main__':
    collect()
