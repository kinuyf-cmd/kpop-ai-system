#!/usr/bin/env python3
"""Kstyle (kstyle.com) Japanese K-POP media scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log
from datetime import datetime

KPOP_KW_JP = [
    'K-POP', 'KPOP', 'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'Red Velvet', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'TWS', 'KISS OF LIFE', 'IU', 'LISA', 'JENNIE', 'JISOO', 'HYBE', 'SM', 'YG', 'JYP',
    'カムバック', 'ライブ', 'ツアー', 'ファンミ', 'アルバム', '新曲', 'リリース',
]
URGENT_JP = ['速報', '緊急', '公式', '発表', '逮捕', '解散', '脱退', '訃報', '結婚', '熱愛']


def collect():
    signals = []
    try:
        html = fetch_html('https://kstyle.com/main.ksn')
    except Exception as e:
        log(f"Kstyle fetch error: {e}")
        return 0

    pattern = re.compile(
        r'<a[^>]+href="([^"]*?article\.ksn\?[^"]*?)"[^>]*>\s*((?:<[^>]*>|[^<]){10,200})\s*</a>',
        re.DOTALL,
    )
    seen = set()
    for m in pattern.finditer(html):
        path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        url = path if path.startswith('http') else 'https://kstyle.com/' + path.lstrip('/')
        if url in seen or len(title) < 5:
            continue
        seen.add(url)
        matched = [k for k in KPOP_KW_JP if k.lower() in title.lower()]
        if not matched:
            continue
        urgent = any(k in title for k in URGENT_JP)
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'japanese_media',
            'source_id': 'kstyle',
            'keyword': matched[0],
            'title': title[:300],
            'url': url,
            'engagement_score': 3.0 if urgent else 2.0,
            'language': 'ja',
            'urgency': 'high' if urgent else 'normal',
            'raw_data': {'all_keywords': matched},
        })
        if len(signals) >= 20:
            break
    save_signals(signals)
    log(f"Kstyle: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
