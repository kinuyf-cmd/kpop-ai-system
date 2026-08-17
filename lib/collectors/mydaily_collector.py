#!/usr/bin/env python3
"""MyDaily (music + entertainment) scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log

SECTIONS = [
    ('mydaily_ent', 'https://www.mydaily.co.kr/news/newslist.html?cate=E'),
]


def collect():
    signals = []
    for source_id, url in SECTIONS:
        try:
            html = fetch_html(url)
        except Exception as e:
            log(f"{source_id} fetch error: {e}")
            continue

        patterns = [
            r'<a[^>]+href="(/page/view/\d+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>',
            r'<a[^>]+href="(https?://www\.mydaily\.co\.kr/page/view/\d+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>',
        ]
        seen = set()
        count = 0
        for pat in patterns:
            for m in re.finditer(pat, html, re.DOTALL):
                path, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
                full_url = path if path.startswith('http') else 'https://www.mydaily.co.kr' + path
                if full_url in seen or len(title) < 5:
                    continue
                seen.add(full_url)
                keywords = is_kpop_related(title)
                if not keywords:
                    continue
                signals.append(make_signal(source_id, title, full_url, keywords, is_urgent(title)))
                count += 1
                if count >= 20:
                    break
            if count >= 20:
                break

    save_signals(signals, source_id='mydaily_ent')
    log(f"MyDaily total: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
