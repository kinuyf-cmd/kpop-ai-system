#!/usr/bin/env python3
"""allkpop (allkpop.com) — 速報性の高い英語K-POPニュースサイト"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log
from datetime import datetime

KPOP_KW = [
    'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'Red Velvet', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'EXO', 'RIIZE', 'KATSEYE', 'BABYMONSTER', 'GOT7', 'MAMAMOO', 'NMIXX',
    'TWS', 'KISS OF LIFE', 'fromis_9', 'TREASURE', 'MONSTA X', 'DAY6', 'PLAVE',
    'HYBE', 'SM', 'YG', 'JYP', 'comeback', 'debut', 'concert', 'tour',
    'Billboard', 'chart', 'album', 'MV', 'music video', 'Spotify', 'Grammy',
]
URGENT_KW = ['breaking', 'confirmed', 'announces', 'wins', 'arrested',
             'disbands', 'leaves', 'dating', 'married', 'controversy']


def collect():
    signals = []
    try:
        html = fetch_html('https://www.allkpop.com/')
    except Exception as e:
        log(f"allkpop fetch error: {e}")
        return 0

    patterns = [
        # <div class="title"><a href='/article/...' >Title</a></div>
        re.compile(r"""class=["']title["'][^>]*>\s*<a[^>]+href=["'](/article/[^"']+)["'][^>]*>([^<]{10,200})</a>""", re.DOTALL),
        re.compile(r"""href=["'](/article/2026/[^"']+)["'][^>]*>([^<]{15,200})</a>""", re.DOTALL),
    ]
    seen = set()
    for pat in patterns:
        for m in pat.finditer(html):
            link, title = m.group(1), m.group(2).strip()
            if link in seen or len(title) < 10:
                continue
            seen.add(link)
            full_url = link if link.startswith('http') else 'https://www.allkpop.com' + link
            matched = [k for k in KPOP_KW if k.lower() in title.lower()]
            if not matched:
                continue
            urgent = any(k.lower() in title.lower() for k in URGENT_KW)
            signals.append({
                'timestamp': datetime.now().isoformat(),
                'source': 'english_media',
                'source_id': 'allkpop',
                'keyword': matched[0],
                'title': title[:300],
                'url': full_url,
                'engagement_score': 3.5 if urgent else 2.0,
                'language': 'en',
                'urgency': 'high' if urgent else 'normal',
                'raw_data': {'all_keywords': matched},
            })
    save_signals(signals[:30])
    log(f"allkpop: {len(signals[:30])}")
    return len(signals[:30])


if __name__ == '__main__':
    collect()
